"""Onboarding endpoints + Section 1/2, finalize, override, advance-lifecycle."""

from flask import Blueprint, request

from errors import err
from db import db, stamp_create, touch
from middleware import require_roles, require_read_role, parse_pagination
from response import object_response
from listing import sorted_collection, paginate_and_respond
from validation import (get_json_body, require_str, require_enum, optional_bool,
                        optional_datetime, require_int)
from clock import now, format_iso8601, section2_deadline_from_hire_date, parse_iso8601
import serializers
from services import audit, calculations, lifecycle

bp = Blueprint("onboardings", __name__)

CITIZENSHIP = {"US_CITIZEN", "NONCITIZEN_NATIONAL", "LPR", "ALIEN_AUTHORIZED"}
ONBOARDING_STATUSES = {
    "CREATED", "SECTION1_COMPLETE", "SECTION2_COMPLETE", "EVERIFY_PENDING",
    "AUTHORIZED", "TERMINATED_NONCONFIRMED", "REVERIFICATION_DUE",
    "EXPIRED_UNAUTHORIZED",
}


def _get_onboarding_or_404(onboarding_id):
    ob = db.onboardings.get(onboarding_id)
    if ob is None:
        raise err("ERR_NOT_FOUND", "Onboarding not found")
    return ob


def _form_for(onboarding_id):
    return next((f for f in db.i9_forms.values()
                 if f.get("onboarding_id") == onboarding_id), None)


# ---------------------------------------------------------------------------
# POST /onboardings
# ---------------------------------------------------------------------------
@bp.route("/onboardings", methods=["POST"])
def create_onboarding():
    require_roles({"HRReviewer", "ComplianceOfficer"})
    body = get_json_body()

    employee_full_name = require_str(body, "employee_full_name")
    employee_email = require_str(body, "employee_email")
    citizenship_status = require_enum(body, "citizenship_status", CITIZENSHIP)
    hire_date_dt = None
    # hire_date is required and must be ISO 8601.
    require_str(body, "hire_date")
    try:
        hire_date_dt = parse_iso8601(body["hire_date"])
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "hire_date must be ISO 8601")

    requires_everify = optional_bool(body, "requires_everify", True)
    work_auth_expiration = optional_datetime(body, "work_auth_expiration", None)

    onboarding = {
        "employee_full_name": employee_full_name,
        "employee_email": employee_email,
        "citizenship_status": citizenship_status,
        "hire_date": format_iso8601(hire_date_dt),
        "work_auth_expiration": format_iso8601(work_auth_expiration)
        if work_auth_expiration else None,
        "status": "CREATED",
        "section2_deadline": format_iso8601(
            section2_deadline_from_hire_date(hire_date_dt)),
        "is_overdue": False,
        "requires_everify": requires_everify,
    }
    stamp_create(onboarding)
    db.onboardings[onboarding["id"]] = onboarding

    # Side effect: create the backing I9Form in SECTION1_PENDING (PRD §3.1).
    form = {
        "onboarding_id": onboarding["id"],
        "section1_attested_at": None,
        "section1_preparer_used": False,
        "chosen_document_path": "UNSET",
        "section2_reviewer_id": None,
        "section2_completed_at": None,
        "current_section3_count": 0,
        "status": "SECTION1_PENDING",
    }
    stamp_create(form)
    db.i9_forms[form["id"]] = form

    return object_response(serializers.onboarding(onboarding), status=201)


# ---------------------------------------------------------------------------
# GET /onboardings
# ---------------------------------------------------------------------------
@bp.route("/onboardings", methods=["GET"])
def list_onboardings():
    require_read_role()
    limit, offset = parse_pagination()
    status = request.args.get("status")
    records = sorted_collection(db.onboardings)
    # Recompute the latching is_overdue flag for each onboarding on read.
    for ob in records:
        lifecycle.recompute_is_overdue(ob, _form_for(ob["id"]))
    if status is not None:
        records = [r for r in records if r.get("status") == status]
    return paginate_and_respond(records, limit, offset, serializers.onboarding)


# ---------------------------------------------------------------------------
# GET /onboardings/{id}
# ---------------------------------------------------------------------------
@bp.route("/onboardings/<onboarding_id>", methods=["GET"])
def get_onboarding(onboarding_id):
    require_read_role()
    ob = _get_onboarding_or_404(onboarding_id)
    # is_overdue is a computed, latching flag (PRD §3.2). Recompute the latch on
    # read so a clock advance past section2_deadline is reflected without a
    # separate mutation. This never bumps version (it is read-derived).
    lifecycle.recompute_is_overdue(ob, _form_for(onboarding_id))
    return object_response(serializers.onboarding(ob))


# ---------------------------------------------------------------------------
# GET /onboardings/{id}/risk
# ---------------------------------------------------------------------------
@bp.route("/onboardings/<onboarding_id>/risk", methods=["GET"])
def onboarding_risk(onboarding_id):
    require_read_role()
    ob = _get_onboarding_or_404(onboarding_id)
    form = _form_for(onboarding_id)
    lifecycle.recompute_is_overdue(ob, form)

    case = lifecycle.everify_case_for(onboarding_id)
    receipt_docs = [d for d in db.identity_documents.values()
                    if d.get("onboarding_id") == onboarding_id]
    auths = [w for w in lifecycle.work_auths_for(onboarding_id)
             if w.get("status") != "SUPERSEDED"]
    clock = now()
    risk_score = calculations.compliance_risk(ob, case, receipt_docs, auths, clock)

    open_tnc = bool(case is not None
                    and case.get("tnc_type", "NONE") != "NONE"
                    and ob.get("status") != "AUTHORIZED")
    return object_response({
        "risk_score": risk_score,
        "is_overdue": ob.get("is_overdue", False),
        "open_tnc": open_tnc,
    })


# ---------------------------------------------------------------------------
# POST /onboardings/{id}/section1-attest
# ---------------------------------------------------------------------------
@bp.route("/onboardings/<onboarding_id>/section1-attest", methods=["POST"])
def section1_attest(onboarding_id):
    require_roles({"HRReviewer"})
    ob = _get_onboarding_or_404(onboarding_id)
    body = get_json_body()
    preparer = optional_bool(body, "section1_preparer_used", None)

    # priority 5: state guard
    if ob.get("status") != "CREATED":
        raise err("ERR_INVALID_STATE",
                  "Section 1 attestation requires status CREATED")

    # priority 8: ALIEN_AUTHORIZED needs work_auth_expiration.
    if ob.get("citizenship_status") == "ALIEN_AUTHORIZED" \
            and not ob.get("work_auth_expiration"):
        raise err("ERR_SECTION1_INCOMPLETE",
                  "ALIEN_AUTHORIZED Section 1 requires work_auth_expiration")

    form = _form_for(onboarding_id)
    form["section1_attested_at"] = format_iso8601(now())
    if preparer is not None:
        form["section1_preparer_used"] = preparer
    form["status"] = "SECTION1_DONE"
    touch(form)

    ob["status"] = "SECTION1_COMPLETE"
    touch(ob)

    return object_response(serializers.onboarding(ob))


# ---------------------------------------------------------------------------
# POST /onboardings/{id}/section2-complete
# ---------------------------------------------------------------------------
@bp.route("/onboardings/<onboarding_id>/section2-complete", methods=["POST"])
def section2_complete(onboarding_id):
    user_id, role = require_roles({"HRReviewer"})
    ob = _get_onboarding_or_404(onboarding_id)
    body = get_json_body()

    # Body shape (priority-15 generic) for document_ids: needed early because
    # ownership/existence checks (higher priority) iterate it. Per §2.8 the
    # existence checks outrank generic body validation, so resolve documents
    # first and treat malformed document_ids as ERR_INVALID_REQUEST only when
    # they are absent/ill-typed.
    document_ids = body.get("document_ids")
    if document_ids is None or not isinstance(document_ids, list) \
            or not all(isinstance(x, str) for x in document_ids):
        # expected_onboarding_version is also required; but existence/state
        # outrank generic validation. We still need document_ids to proceed, so
        # this is the generic body failure (lowest priority) — defer it until
        # after the higher-priority checks below would have a chance to fire.
        document_ids = None

    # priority 4: existence of every referenced document (left-to-right).
    chosen = []
    if document_ids is not None:
        for did in document_ids:
            doc = db.identity_documents.get(did)
            if doc is None:
                raise err("ERR_NOT_FOUND", "IdentityDocument %s not found" % did)
            chosen.append(doc)

    # priority 5: state guard.
    if ob.get("status") != "SECTION1_COMPLETE":
        raise err("ERR_INVALID_STATE",
                  "Section 2 completion requires status SECTION1_COMPLETE")

    # priority 7: ownership — every chosen document belongs to this onboarding.
    if document_ids is not None:
        for doc in chosen:
            if doc.get("onboarding_id") != onboarding_id:
                raise err("ERR_DOCUMENT_NOT_OWNED",
                          "Document %s does not belong to this onboarding"
                          % doc["id"])
            # Each chosen document must currently be PRESENTED (PRD §3.3).
            if doc.get("status") != "PRESENTED":
                raise err("ERR_DOCUMENT_COMBINATION_INVALID",
                          "Document %s is not in PRESENTED status" % doc["id"])

    # priority 9: documentary-combination rule.
    if document_ids is None:
        # generic body failure deferred to here (after higher-priority checks).
        raise err("ERR_INVALID_REQUEST",
                  "document_ids must be a list of document id strings")
    path = calculations.section2_path(chosen)
    if path is None:
        raise err("ERR_DOCUMENT_COMBINATION_INVALID",
                  "Chosen documents must be exactly List A or List B + List C")

    # priority 10: document expiry (non-receipt chosen docs).
    clock = now()
    for doc in chosen:
        if not calculations.is_document_valid(
                doc.get("expiration_date"), doc.get("is_receipt", False), clock):
            raise err("ERR_DOCUMENT_EXPIRED",
                      "Document %s is expired as of the clock" % doc["id"])

    # priority 14: OCC.
    expected = body.get("expected_onboarding_version")
    if expected is None:
        raise err("ERR_INVALID_REQUEST",
                  "expected_onboarding_version is required")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err("ERR_INVALID_REQUEST",
                  "expected_onboarding_version must be an integer")
    if expected != ob.get("version"):
        raise err("ERR_STALE_ONBOARDING_VERSION",
                  "expected_onboarding_version does not match current version")

    # --- All guards passed: apply side effects ---
    chosen_ids = {d["id"] for d in chosen}
    completed_at = format_iso8601(clock)

    for doc in chosen:
        doc["accepted_for_section2"] = True
        doc["status"] = "ACCEPTED"
        if doc.get("is_receipt"):
            doc["receipt_resolution_deadline"] = format_iso8601(
                calculations.receipt_resolution_deadline(completed_at))
        touch(doc)

    # Supersede every other still-PRESENTED document for this onboarding.
    for doc in db.identity_documents.values():
        if doc.get("onboarding_id") != onboarding_id:
            continue
        if doc["id"] in chosen_ids:
            continue
        if doc.get("status") == "PRESENTED":
            doc["status"] = "SUPERSEDED"
            touch(doc)

    form = _form_for(onboarding_id)
    form["chosen_document_path"] = path
    form["section2_reviewer_id"] = user_id
    form["section2_completed_at"] = completed_at
    form["status"] = "SECTION2_DONE"
    touch(form)

    ob["status"] = "SECTION2_COMPLETE"
    touch(ob)
    lifecycle.recompute_is_overdue(ob, form)

    audit.append(onboarding_id, role, user_id, "SECTION2_COMPLETED",
                 "Section 2 completed via %s path" % path)

    return object_response(serializers.onboarding(ob))


# ---------------------------------------------------------------------------
# POST /onboardings/{id}/finalize
# ---------------------------------------------------------------------------
@bp.route("/onboardings/<onboarding_id>/finalize", methods=["POST"])
def finalize(onboarding_id):
    user_id, role = require_roles({"ComplianceOfficer"})
    ob = _get_onboarding_or_404(onboarding_id)

    # state + requires_everify guard (PRD §3.5).
    if ob.get("status") != "SECTION2_COMPLETE" or ob.get("requires_everify"):
        raise err("ERR_INVALID_STATE",
                  "Finalize requires SECTION2_COMPLETE and requires_everify=false")

    ob["status"] = "AUTHORIZED"
    touch(ob)
    audit.append(onboarding_id, role, user_id, "AUTHORIZED_NO_EVERIFY",
                 "Non-E-Verify onboarding finalized to AUTHORIZED")
    return object_response(serializers.onboarding(ob))


# ---------------------------------------------------------------------------
# POST /onboardings/{id}/override
# ---------------------------------------------------------------------------
@bp.route("/onboardings/<onboarding_id>/override", methods=["POST"])
def override(onboarding_id):
    user_id, role = require_roles({"ComplianceOfficer"})

    # priority 3: segregation of duties — override actor must differ from the
    # Section 2 reviewer of this onboarding's form. Existence (priority 4) is
    # lower priority than SoD per §2.8, BUT SoD needs the onboarding's form to
    # know the reviewer; if the onboarding does not exist there is no reviewer
    # to compare, so SoD cannot fire and 404 is the correct outcome. We resolve
    # the form's reviewer and only raise SoD when it matches.
    ob = db.onboardings.get(onboarding_id)
    if ob is not None:
        form = _form_for(onboarding_id)
        reviewer_id = form.get("section2_reviewer_id") if form else None
        if reviewer_id is not None and reviewer_id == user_id:
            raise err("ERR_SEGREGATION_OF_DUTIES",
                      "Override actor must differ from the Section 2 reviewer")

    # priority 4: existence.
    ob = _get_onboarding_or_404(onboarding_id)
    body = get_json_body()
    require_str(body, "override_reason")

    ob["is_overdue"] = False
    touch(ob)
    audit.append(onboarding_id, role, user_id, "OVERRIDE_APPLIED",
                 "Compliance override applied: %s" % body["override_reason"])
    return object_response(serializers.onboarding(ob))


# ---------------------------------------------------------------------------
# POST /onboardings/{id}/advance-lifecycle
# ---------------------------------------------------------------------------
@bp.route("/onboardings/<onboarding_id>/advance-lifecycle", methods=["POST"])
def advance_lifecycle(onboarding_id):
    user_id, role = require_roles({"ComplianceOfficer", "EVerifyOperator"})
    ob = _get_onboarding_or_404(onboarding_id)
    lifecycle.advance(ob, role, user_id)
    return object_response(serializers.onboarding(ob))
