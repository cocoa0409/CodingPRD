from flask import Blueprint

import db
import errors
import serializers
import services
from middleware import ALL_ROLES, require_roles
from response import ok_list, ok_object
from util import get_body, paginate, require_enum, require_fields

bp = Blueprint("verification", __name__)

COORD = "MedicalStaffCoordinator"
CHAIR = "CredentialsCommitteeChair"

ITEM_KINDS = ("MEDICAL_SCHOOL", "RESIDENCY", "BOARD_CERT", "STATE_LICENSE",
              "DEA", "MALPRACTICE_HISTORY", "WORK_HISTORY", "NPDB_QUERY",
              "REFERENCES")


def _get_item(item_id):
    rec = db.verification_items.get(item_id)
    if rec is None:
        errors.raise_err(errors.ERR_NOT_FOUND, "VerificationItem not found")
    return rec


@bp.route("/mso/verification-items", methods=["POST"])
@require_roles(COORD)
def create_item():
    body = get_body()
    # Rung 3: existence.
    app_id = body.get("application_id")
    app = None
    if app_id is not None:
        app = db.applications.get(app_id)
        if app is None:
            errors.raise_err(errors.ERR_NOT_FOUND,
                             "AppointmentApplication not found")
    # Rung 11: input shape.
    require_fields(body, ["application_id", "item_kind", "is_primary_source"])
    require_enum(body, "item_kind", ITEM_KINDS)
    if not isinstance(body["is_primary_source"], bool):
        errors.raise_err(errors.ERR_INVALID_REQUEST,
                         "is_primary_source must be a boolean")
    # The verification file is built while the application sits in DRAFT.
    if app["application_status"] != "DRAFT":
        errors.raise_err(errors.ERR_INVALID_STATE,
                         "Verification items may only be attached while the "
                         "application is in DRAFT")
    rec = services.base_record()
    rec.update({
        "application_id": app_id,
        "item_kind": body["item_kind"],
        "item_status": "PENDING",
        "requested_at": None,
        "verified_at": None,
        "discrepancy_note": None,
        "waiver_justification": None,
        "is_primary_source": body["is_primary_source"],
    })
    db.verification_items[rec["id"]] = rec
    services.recompute_verification_counts(app)
    return ok_object(serializers.verification_item(rec), 201)


@bp.route("/mso/verification-items", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_items():
    items, limit, offset, total = paginate(
        db.verification_items.values(), serializers.verification_item,
        ["application_id", "item_status"])
    return ok_list(items, limit, offset, total)


@bp.route("/mso/verification-items/<iid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_item(iid):
    return ok_object(serializers.verification_item(_get_item(iid)))


@bp.route("/mso/verification-items/<iid>/mark-received", methods=["POST"])
@require_roles(COORD)
def mark_received(iid):
    get_body()
    item = _get_item(iid)
    if item["item_status"] not in ("REQUESTED", "DISCREPANCY"):
        errors.raise_err(errors.ERR_VERIFICATION_NOT_REQUESTED,
                         "Item is not in REQUESTED or DISCREPANCY")
    item["item_status"] = "RECEIVED"
    services.touch(item)
    app = db.applications.get(item["application_id"])
    if app is not None:
        if app["application_status"] == "SUBMITTED":
            app["application_status"] = "PSV_IN_PROGRESS"
            services.touch(app)
        services.recompute_verification_counts(app)
        services.maybe_complete_psv(app)
    return ok_object(serializers.verification_item(item))


@bp.route("/mso/verification-items/<iid>/verify", methods=["POST"])
@require_roles(COORD)
def verify_item(iid):
    get_body()
    item = _get_item(iid)
    if item["item_status"] != "RECEIVED":
        errors.raise_err(errors.ERR_VERIFICATION_NOT_RECEIVED,
                         "Item is not in RECEIVED")
    # NPDB query gate.
    if item["item_kind"] == "NPDB_QUERY":
        app = db.applications.get(item["application_id"])
        wanted = ("QUERY_INITIAL" if app and
                  app["application_kind"] == "INITIAL"
                  else "QUERY_REAPPOINTMENT")
        member_id = app["member_id"] if app else None
        found = any(
            r["member_id"] == member_id and r["report_kind"] == wanted
            and r["report_status"] in ("SUBMITTED", "ACKNOWLEDGED")
            for r in db.npdb_reports.values()
        )
        if not found:
            errors.raise_err(errors.ERR_NPDB_QUERY_MISSING,
                             "No filed NPDB query report for the member")
    item["item_status"] = "VERIFIED"
    item["verified_at"] = services.now_iso()
    services.touch(item)
    app = db.applications.get(item["application_id"])
    if app is not None:
        services.recompute_verification_counts(app)
        services.maybe_complete_psv(app)
    return ok_object(serializers.verification_item(item))


@bp.route("/mso/verification-items/<iid>/flag-discrepancy", methods=["POST"])
@require_roles(COORD)
def flag_discrepancy(iid):
    body = get_body()
    item = _get_item(iid)
    if item["item_status"] != "RECEIVED":
        errors.raise_err(errors.ERR_VERIFICATION_NOT_RECEIVED,
                         "Item is not in RECEIVED")
    note = body.get("discrepancy_note")
    if not isinstance(note, str) or len(note) < 10:
        errors.raise_err(errors.ERR_INVALID_REQUEST,
                         "discrepancy_note must be at least 10 characters")
    item["item_status"] = "DISCREPANCY"
    item["discrepancy_note"] = note
    services.touch(item)
    return ok_object(serializers.verification_item(item))


@bp.route("/mso/verification-items/<iid>/waive", methods=["POST"])
@require_roles(CHAIR)
def waive_item(iid):
    body = get_body()
    item = _get_item(iid)
    if item["item_status"] not in ("REQUESTED", "RECEIVED"):
        errors.raise_err(errors.ERR_VERIFICATION_NOT_WAIVABLE,
                         "Item is not in REQUESTED or RECEIVED")
    # Safety gate: primary-source NPDB items can never be waived.
    if item["is_primary_source"] and item["item_kind"] == "NPDB_QUERY":
        errors.raise_err(errors.ERR_PRIMARY_SOURCE_NOT_WAIVABLE,
                         "A primary-source NPDB_QUERY item cannot be waived")
    justification = body.get("waiver_justification")
    if not isinstance(justification, str) or len(justification) < 20:
        errors.raise_err(errors.ERR_INVALID_REQUEST,
                         "waiver_justification must be at least 20 characters")
    item["item_status"] = "WAIVED"
    item["waiver_justification"] = justification
    services.touch(item)
    app = db.applications.get(item["application_id"])
    if app is not None:
        services.recompute_verification_counts(app)
        services.maybe_complete_psv(app)
    return ok_object(serializers.verification_item(item))
