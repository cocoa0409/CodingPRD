"""Documents, photos and prepared forms -- the three readiness inputs."""
import datetime as _dt
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint

import clock
import serializers
import store
import validation
from calendar_util import add_calendar_months
from constants import (
    API_PREFIX,
    BACKGROUND_CODES,
    DOCUMENT_RESUBMISSION_CAP,
    DOC_TYPES,
    PHOTO_MAX_HEAD_HEIGHT_RATIO,
    PHOTO_MIN_HEAD_HEIGHT_RATIO,
    PHOTO_MIN_RESOLUTION_PX,
    PHOTO_RETAKE_CAP,
    PHOTO_VALIDITY_DAYS,
    REVIEW_DECISIONS,
)
from errors import fail
from routes.common import READ_ROLES, created, endpoint, listing, ok
from services import lookup, readiness
from validation import Body

bp = Blueprint("documents", __name__)
P = API_PREFIX


# ---------------------------------------------------------------- documents ---
@bp.route(P + "/applicants/<applicant_id>/documents", methods=["POST"])
@endpoint("applicants.documents.create", ["CaseManager", "Traveler"])
def submit_document(ctx, applicant_id):
    applicant = validation.need("applicants", applicant_id)
    order = lookup.order_of_applicant(applicant)
    slot = None
    raw_type = ctx.body.get("doc_type")
    # Rung 4 owns the "no slot for this doc_type" case, but only for a value
    # that IS a declared member -- otherwise ERR_INVALID_ENUM at rung 7 would
    # be unreachable on this field.
    if isinstance(raw_type, str) and raw_type in DOC_TYPES:
        for candidate in lookup.documents_of(applicant):
            if candidate["doc_type"] == raw_type:
                slot = candidate
                break
        if slot is None:
            fail("ERR_RESOURCE_NOT_FOUND", "The applicant holds no slot for this doc_type.")
    validation.check_membership(ctx, order)

    body = Body(ctx.body)
    body.enum("doc_type", DOC_TYPES)
    issue_date = body.date("issue_date")
    expiry_date = body.date("expiry_date", required=False)
    body.check()
    validation.guard_order(ctx, order)
    validation.require_state(slot["review_status"], ("MISSING",))

    slot["review_status"] = "RECEIVED"
    slot["issue_date"] = issue_date
    slot["expiry_date"] = expiry_date
    store.touch(slot)
    return ok(serializers.applicant_document(slot))


@bp.route(P + "/applicants/<applicant_id>/documents", methods=["GET"])
@endpoint("applicants.documents.list", READ_ROLES)
def list_documents(ctx, applicant_id):
    applicant = validation.need("applicants", applicant_id)
    validation.check_membership(ctx, lookup.order_of_applicant(applicant))
    rows = lookup.documents_of(applicant)
    rows = validation.apply_filter(rows, "review_status")
    return listing(rows, serializers.applicant_document)


@bp.route(P + "/documents/<document_id>", methods=["GET"])
@endpoint("documents.read", READ_ROLES)
def read_document(ctx, document_id):
    row = validation.need("documents", document_id)
    validation.check_membership(ctx, lookup.order_of_document(row))
    return ok(serializers.applicant_document(row))


def document_is_valid(slot, order):
    rule = slot["validity_rule"]
    if rule == "NONE":
        return True
    param = slot["validity_param"]
    if rule == "VALID_BEYOND_RETURN_MONTHS":
        if slot["expiry_date"] is None or param is None:
            return False
        required_min = add_calendar_months(order["return_date"], param)
        return slot["expiry_date"] >= required_min
    if rule == "EXPIRES_AFTER_ISSUE_DAYS":
        if slot["issue_date"] is None or param is None:
            return False
        doc_expiry = slot["issue_date"] + _dt.timedelta(days=param)
        return doc_expiry >= order["travel_date"]
    return True


@bp.route(P + "/documents/<document_id>/review", methods=["POST"])
@endpoint("documents.review", ["CaseManager"])
def review_document(ctx, document_id):
    slot = validation.need("documents", document_id)
    applicant = store.get("applicants", slot["applicant_id"])
    order = lookup.order_of_applicant(applicant)
    body = Body(ctx.body)
    decision = body.enum("decision", REVIEW_DECISIONS)
    rejection_reason = body.string("rejection_reason", required=False)
    body.check()
    validation.guard_order(ctx, order)
    validation.require_state(slot["review_status"], ("RECEIVED",))

    if decision == "ACCEPT":
        if not document_is_valid(slot, order):
            fail("ERR_DOCUMENT_VALIDITY_INSUFFICIENT")
        slot["review_status"] = "ACCEPTED"
        slot["rejection_reason"] = None
    else:
        slot["review_status"] = "REJECTED"
        slot["rejection_reason"] = rejection_reason
    slot["reviewed_by_user_id"] = ctx.user_id
    store.touch(slot)

    readiness.recompute_readiness(applicant)
    readiness.reevaluate_gate(order)
    return ok(serializers.applicant_document(slot))


@bp.route(P + "/documents/<document_id>/resubmit", methods=["POST"])
@endpoint("documents.resubmit", ["CaseManager", "Traveler"])
def resubmit_document(ctx, document_id):
    slot = validation.need("documents", document_id)
    order = lookup.order_of_document(slot)
    validation.check_membership(ctx, order)
    body = Body(ctx.body)
    issue_date = body.date("issue_date")
    expiry_date = body.date("expiry_date", required=False)
    body.check()
    validation.guard_order(ctx, order)
    validation.require_state(slot["review_status"], ("REJECTED",))
    if slot["resubmission_count"] >= DOCUMENT_RESUBMISSION_CAP:
        fail("ERR_RESUBMISSION_CAP_EXCEEDED")

    slot["review_status"] = "RECEIVED"
    slot["issue_date"] = issue_date
    slot["expiry_date"] = expiry_date
    slot["rejection_reason"] = None
    slot["resubmission_count"] += 1
    store.touch(slot)
    return ok(serializers.applicant_document(slot))


# ------------------------------------------------------------------- photos ---
def _photo_row(applicant_id, taken_on, ratio, background, resolution, retake_count):
    return {
        "applicant_id": applicant_id,
        "taken_on": taken_on,
        "head_height_ratio": ratio,
        "background_code": background,
        "resolution_px": resolution,
        "compliance_status": "PENDING",
        "retake_count": retake_count,
        "failure_reasons": [],
    }


def _read_photo_payload(ctx):
    body = Body(ctx.body)
    taken_on = body.date("taken_on")
    ratio = body.number("head_height_ratio", exclusive_min=0, exclusive_max=1)
    background = body.enum("background_code", BACKGROUND_CODES)
    resolution = body.integer("resolution_px", minimum=1)
    return body, taken_on, ratio, background, resolution


@bp.route(P + "/applicants/<applicant_id>/photos", methods=["POST"])
@endpoint("applicants.photos.create", ["CaseManager", "Traveler"])
def upload_photo(ctx, applicant_id):
    applicant = validation.need("applicants", applicant_id)
    order = lookup.order_of_applicant(applicant)
    validation.check_membership(ctx, order)
    body, taken_on, ratio, background, resolution = _read_photo_payload(ctx)
    body.check()
    validation.guard_order(ctx, order)
    row = store.insert(
        "photos", _photo_row(applicant["id"], taken_on, ratio, background, resolution, 0)
    )
    return created(serializers.photo(row))


@bp.route(P + "/applicants/<applicant_id>/photos", methods=["GET"])
@endpoint("applicants.photos.list", READ_ROLES)
def list_photos(ctx, applicant_id):
    applicant = validation.need("applicants", applicant_id)
    validation.check_membership(ctx, lookup.order_of_applicant(applicant))
    rows = lookup.photos_of(applicant)
    rows = validation.apply_filter(rows, "compliance_status")
    return listing(rows, serializers.photo)


@bp.route(P + "/photos/<photo_id>/compliance-check", methods=["POST"])
@endpoint("photos.compliance_check", ["CaseManager"])
def compliance_check(ctx, photo_id):
    photo = validation.need("photos", photo_id)
    applicant = store.get("applicants", photo["applicant_id"])
    order = lookup.order_of_applicant(applicant)
    Body(ctx.body).check()
    validation.guard_order(ctx, order)
    validation.require_state(photo["compliance_status"], ("PENDING",))

    failures = []
    ratio = photo["head_height_ratio"]
    if not isinstance(ratio, Decimal):
        ratio = Decimal(str(ratio))
    ratio2 = ratio.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if not (PHOTO_MIN_HEAD_HEIGHT_RATIO <= ratio2 <= PHOTO_MAX_HEAD_HEIGHT_RATIO):
        failures.append("HEAD_HEIGHT")
    if photo["background_code"] == "COLORED":
        failures.append("BACKGROUND")
    if photo["resolution_px"] < PHOTO_MIN_RESOLUTION_PX:
        failures.append("RESOLUTION")

    photo["failure_reasons"] = failures
    if failures:
        photo["compliance_status"] = "FAILED"
    else:
        horizon = photo["taken_on"] + _dt.timedelta(days=PHOTO_VALIDITY_DAYS)
        photo["compliance_status"] = "EXPIRED" if horizon < order["travel_date"] else "PASSED"
    store.touch(photo)

    readiness.recompute_readiness(applicant)
    readiness.reevaluate_gate(order)
    return ok(serializers.photo(photo))


@bp.route(P + "/photos/<photo_id>/retake", methods=["POST"])
@endpoint("photos.retake", ["CaseManager", "Traveler"])
def retake_photo(ctx, photo_id):
    photo = validation.need("photos", photo_id)
    applicant = store.get("applicants", photo["applicant_id"])
    order = lookup.order_of_applicant(applicant)
    validation.check_membership(ctx, order)
    body, taken_on, ratio, background, resolution = _read_photo_payload(ctx)
    body.check()
    validation.guard_order(ctx, order)
    validation.require_state(photo["compliance_status"], ("FAILED", "EXPIRED"))
    if photo["retake_count"] >= PHOTO_RETAKE_CAP:
        fail("ERR_PHOTO_RETAKE_CAP_EXCEEDED")

    photo["compliance_status"] = "SUPERSEDED"
    store.touch(photo)
    fresh = store.insert("photos", _photo_row(
        applicant["id"], taken_on, ratio, background, resolution, photo["retake_count"] + 1
    ))
    readiness.recompute_readiness(applicant)
    readiness.reevaluate_gate(order)
    return created(serializers.photo(fresh))


# ----------------------------------------------------------- prepared forms ---
@bp.route(P + "/applicants/<applicant_id>/prepared-forms", methods=["POST"])
@endpoint("applicants.prepared_forms.create", ["CaseManager"])
def prepare_form(ctx, applicant_id):
    applicant = validation.need("applicants", applicant_id)
    order = lookup.order_of_applicant(applicant)
    raw_form_id = ctx.body.get("agency_form_id")
    agency_form = None
    if isinstance(raw_form_id, str):
        agency_form = validation.need("agency_forms", raw_form_id)

    body = Body(ctx.body)
    body.string("agency_form_id")
    # Adjudication of friction 11: BOTH declared numeric bounds are carried --
    # at least 0, and at least the referenced revision's required_field_count.
    filled = body.integer("filled_field_count", minimum=0)
    if agency_form is not None and isinstance(filled, int):
        body.invalid(
            filled < agency_form["required_field_count"],
            "filled_field_count must be at least the revision's required_field_count.",
        )
    expected = body.integer("expected_applicant_version")
    body.check()
    validation.guard_order(ctx, order)
    validation.check_occ(expected, applicant)

    catalog = lookup.catalog_of(order)
    if agency_form["status"] != "ACTIVE" or agency_form["form_code"] != catalog["form_code"]:
        fail("ERR_FORM_REVISION_STALE")

    for prior in lookup.prepared_forms_of(applicant):
        if prior["form_code"] == agency_form["form_code"] and prior["prep_status"] != "VOID":
            prior["prep_status"] = "VOID"
            store.touch(prior)

    row = store.insert("prepared_forms", {
        "applicant_id": applicant["id"],
        "agency_form_id": agency_form["id"],
        "form_code": agency_form["form_code"],
        "revision_used": agency_form["revision"],
        "filled_field_count": filled,
        "prep_status": "PREPARED",
        "signed_at": None,
        "signed_by_user_id": None,
    })
    readiness.recompute_readiness(applicant, bump=False)
    store.touch(applicant)
    readiness.reevaluate_gate(order)
    return created(serializers.prepared_form(row))


@bp.route(P + "/applicants/<applicant_id>/prepared-forms", methods=["GET"])
@endpoint("applicants.prepared_forms.list", READ_ROLES)
def list_prepared_forms(ctx, applicant_id):
    applicant = validation.need("applicants", applicant_id)
    validation.check_membership(ctx, lookup.order_of_applicant(applicant))
    rows = lookup.prepared_forms_of(applicant)
    rows = validation.apply_filter(rows, "prep_status")
    return listing(rows, serializers.prepared_form)


@bp.route(P + "/prepared-forms/<form_id>/sign", methods=["POST"])
@endpoint("prepared_forms.sign", ["CaseManager", "Traveler"])
def sign_prepared_form(ctx, form_id):
    row = validation.need("prepared_forms", form_id)
    order = lookup.order_of_prepared_form(row)
    validation.check_membership(ctx, order)
    Body(ctx.body).check()
    validation.guard_order(ctx, order)
    validation.require_state(row["prep_status"], ("PREPARED",))
    revision = store.get("agency_forms", row["agency_form_id"])
    if revision is None or revision["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "The referenced form revision is no longer ACTIVE.")

    row["prep_status"] = "SIGNED"
    row["signed_at"] = clock.now()
    row["signed_by_user_id"] = ctx.user_id
    store.touch(row)
    return ok(serializers.prepared_form(row))
