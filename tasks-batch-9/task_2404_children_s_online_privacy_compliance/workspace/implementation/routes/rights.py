"""ParentalRightsRequest endpoints (PRD §3.8)."""
from flask import Blueprint, g

import calculations as calc
from constants import (
    CONSENT_METHODS,
    LIVE_RECORD_STATUSES,
    MAX_VERIFICATION_ATTEMPTS,
    METHOD_ASSURANCE_TIER,
    RIGHT_TYPES,
    RIGHTS_STATUSES,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_PARENT,
    ROLE_PRIVACY_ENGINEER,
    SCOPE_MODES,
)
from db import db, now, ordered, touch
from errors import fail
from helpers import (
    apply_filters,
    base_row,
    bump_service,
    disclosure_loss_cascade,
    lookup,
    resolve,
    resolve_body_fk,
    revoke_consent,
)
from middleware import authenticate, body, opt_string, req_enum, req_string
from response import created, ok, paginate
from serializers import rights_out

bp = Blueprint("rights", __name__)

# from -> to : the single role permitted for that transition (PRD §3.8)
TRANSITION_ACTOR = {
    ("SUBMITTED", "VERIFYING"): ROLE_COMPLIANCE_OFFICER,
    ("VERIFYING", "VERIFIED"): ROLE_COMPLIANCE_OFFICER,
    ("VERIFYING", "VERIFICATION_FAILED"): ROLE_COMPLIANCE_OFFICER,
    ("VERIFICATION_FAILED", "SUBMITTED"): ROLE_PARENT,
    ("VERIFICATION_FAILED", "REJECTED"): ROLE_COMPLIANCE_OFFICER,
    ("VERIFIED", "FULFILLED"): ROLE_COMPLIANCE_OFFICER,
}


def _parent_guard(request_row):
    """Precedence step 3: a Parent addresses only its own rights requests."""
    if g.role == ROLE_PARENT and request_row["consent_request_id"] != g.user_id:
        fail("ERR_NOT_CONSENT_HOLDER")


@bp.post("/parental-rights-requests")
@authenticate(ROLE_PARENT)
def create_rights_request():
    data = body()

    # Ownership (step 3) is evaluated on the raw body value, before the foreign
    # keys are resolved (step 5).
    if data.get("consent_request_id") != g.user_id:
        fail("ERR_NOT_CONSENT_HOLDER")

    service = resolve_body_fk("service", data, "service_id")
    consent = resolve_body_fk("consent", data, "consent_request_id")

    if consent["service_id"] != service["id"]:
        fail("ERR_SERVICE_SCOPE_MISMATCH")

    right_type = req_enum(data, "right_type", RIGHT_TYPES)
    requester_email = req_string(data, "requester_email")

    row = base_row()
    row.update(
        {
            "service_id": service["id"],
            "consent_request_id": consent["id"],
            "right_type": right_type,
            "requester_email": requester_email,
            "verification_method": None,
            "verification_attempt_count": 0,
            "scope_mode": None,
            "in_scope_record_count": None,
            "status": "SUBMITTED",
            "fulfilled_at": None,
            "rejection_reason": None,
        }
    )
    db.parental_rights_requests[row["id"]] = row
    return created(rights_out(row))


@bp.get("/parental-rights-requests")
@authenticate(ROLE_COMPLIANCE_OFFICER, ROLE_PRIVACY_ENGINEER)
def list_rights_requests():
    rows = ordered(list(db.parental_rights_requests.values()))
    rows = apply_filters(
        rows,
        {
            "service_id": "service_id",
            "consent_request_id": "consent_request_id",
            "right_type": "right_type",
            "status": "status",
        },
    )
    return paginate(rows, rights_out)


@bp.get("/parental-rights-requests/<request_id>")
@authenticate(ROLE_COMPLIANCE_OFFICER, ROLE_PARENT)
def get_rights_request(request_id):
    row = lookup("rights_request", request_id)
    if row is not None:
        _parent_guard(row)
    row = resolve("rights_request", request_id)
    return ok(rights_out(row))


@bp.post("/parental-rights-requests/<request_id>/status")
@authenticate(ROLE_COMPLIANCE_OFFICER, ROLE_PARENT)
def set_rights_status(request_id):
    row = lookup("rights_request", request_id)
    if row is not None:
        _parent_guard(row)
    row = resolve("rights_request", request_id)

    data = body()
    to_status = req_enum(data, "to_status", RIGHTS_STATUSES)

    # step 8: conditionally required body fields
    verification_method = None
    scope_mode = None
    if to_status == "VERIFYING":
        verification_method = req_enum(data, "verification_method", CONSENT_METHODS)
    elif to_status == "FULFILLED":
        scope_mode = req_enum(data, "scope_mode", SCOPE_MODES)

    current = row["status"]
    transition = (current, to_status)

    # step 9: transition legality
    if to_status == "FULFILLED" and current != "VERIFIED":
        fail("ERR_RIGHTS_REQUEST_NOT_VERIFIED")
    if transition not in TRANSITION_ACTOR:
        fail("ERR_INVALID_STATE")

    # step 10: per-transition role restriction
    if g.role != TRANSITION_ACTOR[transition]:
        fail("ERR_TRANSITION_ROLE_NOT_PERMITTED")

    consent = db.consent_requests[row["consent_request_id"]]
    service = db.online_services[row["service_id"]]

    if transition == ("SUBMITTED", "VERIFYING"):
        row["verification_method"] = verification_method
        row["status"] = to_status
        touch(row)
        return ok(rights_out(row))

    if transition == ("VERIFYING", "VERIFIED"):
        # step 13 clauses (a), (d), (e)
        if consent["notice_delivered_at"] is None:
            fail("ERR_DIRECT_NOTICE_NOT_DELIVERED")
        method_tier = METHOD_ASSURANCE_TIER[row["verification_method"]]
        if method_tier < METHOD_ASSURANCE_TIER[consent["consent_method"]]:
            fail("ERR_RIGHTS_VERIFICATION_TIER_INSUFFICIENT")
        if row["requester_email"] != consent["parent_email"]:
            fail("ERR_REQUESTER_EMAIL_MISMATCH")
        row["status"] = to_status
        touch(row)
        return ok(rights_out(row))

    if transition == ("VERIFYING", "VERIFICATION_FAILED"):
        row["verification_attempt_count"] += 1
        row["status"] = to_status
        touch(row)
        return ok(rights_out(row))

    if transition == ("VERIFICATION_FAILED", "SUBMITTED"):
        # step 22: bounded loop
        if row["verification_attempt_count"] >= MAX_VERIFICATION_ATTEMPTS:
            fail("ERR_VERIFICATION_ATTEMPTS_EXHAUSTED")
        row["verification_method"] = None
        row["status"] = to_status
        touch(row)
        return ok(rights_out(row))

    if transition == ("VERIFICATION_FAILED", "REJECTED"):
        row["rejection_reason"] = opt_string(data, "rejection_reason")
        row["status"] = to_status
        touch(row)
        return ok(rights_out(row))

    # ("VERIFIED", "FULFILLED")
    in_scope = calc.resolve_rights_scope(consent, scope_mode)
    row["scope_mode"] = scope_mode
    row["in_scope_record_count"] = len(in_scope)
    row["status"] = "FULFILLED"
    row["fulfilled_at"] = now()
    touch(row)

    if row["right_type"] == "REFUSE_FURTHER_COLLECTION":
        if consent["status"] == "GRANTED":
            revoke_consent(consent, "PARENT_REFUSAL")
            disclosure_loss_cascade(service)
    elif row["right_type"] == "DELETE":
        stamp = now()
        for record in in_scope:
            if record["status"] in LIVE_RECORD_STATUSES:
                record["status"] = "DISPOSED"
                record["disposed_at"] = stamp
                touch(record)
        # A consent with nothing left to authorise is spent.
        siblings = [
            r
            for r in db.child_data_records.values()
            if r["consent_request_id"] == consent["id"]
        ]
        if all(r["status"] == "DISPOSED" for r in siblings) and consent["status"] == "GRANTED":
            revoke_consent(consent, "DELETION_FULFILLED")
            disclosure_loss_cascade(service)

    bump_service(service)
    return ok(rights_out(row))
