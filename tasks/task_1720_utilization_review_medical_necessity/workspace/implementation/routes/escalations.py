"""EscalationCase endpoints."""
from flask import Blueprint

import db
from errors import ApiError, ERR_CASE_CLOSED, ERR_INVALID_STATE
from middleware import require_roles
from response import success_object
from routes.helpers import paginate, lookup, any_authenticated
from services.calculations import tier_of
from services.case_service import refresh_escalation_effective
from services.common import touch, append_audit
from services.validation import (
    get_json_body, reject_unknown_fields, validate_int, validate_string,
)

bp = Blueprint("escalations", __name__)


@bp.get("/api/utilization-cases/<cid>/escalation-cases")
def list_escalations(cid):
    any_authenticated()
    lookup(db.utilization_cases, cid, "UtilizationCase")
    items = sorted(
        (e for e in db.escalation_cases.values() if e["case_id"] == cid),
        key=lambda e: e["created_at"],
    )
    return paginate(items)


@bp.post("/api/escalation-cases/<eid>/acknowledge")
def acknowledge_escalation(eid):
    user_id, role = require_roles(["CaseManager"])
    get_json_body()

    esc = lookup(db.escalation_cases, eid, "EscalationCase")
    case = db.utilization_cases[esc["case_id"]]
    if case["review_status"] == "CLOSED":
        raise ApiError(ERR_CASE_CLOSED, "Case is CLOSED", 409)
    if esc["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, f"Escalation is {esc['status']}, not OPEN", 409)
    esc["status"] = "ACKNOWLEDGED"
    touch(esc)
    append_audit(case["id"], "ESCALATION_ACKNOWLEDGED", role, user_id,
                 f"Escalation {eid} acknowledged")
    return success_object(esc, 200)


@bp.post("/api/escalation-cases/<eid>/resolve")
def resolve_escalation(eid):
    user_id, role = require_roles(["CaseManager"])
    body = get_json_body()
    reject_unknown_fields(body, ["resolution_note"])
    validate_string(body, "resolution_note")

    esc = lookup(db.escalation_cases, eid, "EscalationCase")
    case = db.utilization_cases[esc["case_id"]]
    if case["review_status"] == "CLOSED":
        raise ApiError(ERR_CASE_CLOSED, "Case is CLOSED", 409)
    if esc["status"] not in ("OPEN", "ACKNOWLEDGED"):
        raise ApiError(ERR_INVALID_STATE,
                       f"Escalation is {esc['status']}; only OPEN or ACKNOWLEDGED may be resolved", 409)
    esc["status"] = "RESOLVED"
    esc["resolution_note"] = body["resolution_note"]
    touch(esc)
    append_audit(case["id"], "ESCALATION_RESOLVED", role, user_id,
                 f"Escalation {eid} resolved")
    return success_object(esc, 200)


@bp.post("/api/escalation-cases/<eid>/apply-credit")
def apply_credit(eid):
    user_id, role = require_roles(["URDirector"])
    body = get_json_body()
    reject_unknown_fields(body, ["credit_days"])
    validate_int(body, "credit_days", min_val=1)

    esc = lookup(db.escalation_cases, eid, "EscalationCase")
    case = db.utilization_cases[esc["case_id"]]
    if case["review_status"] == "CLOSED":
        raise ApiError(ERR_CASE_CLOSED, "Case is CLOSED", 409)
    if esc["status"] not in ("OPEN", "ACKNOWLEDGED"):
        raise ApiError(ERR_INVALID_STATE,
                       f"Escalation is {esc['status']}; credits apply only to active escalations", 409)

    # Pinned evaluation order: eligibility against the RAW tier (pre-credit), must be 3.
    open_dates = {
        a["day_date"]
        for a in db.avoidable_days.values()
        if a["case_id"] == case["id"] and a["status"] == "OPEN"
    }
    raw_tier = tier_of(len(open_dates))
    if raw_tier != 3:
        raise ApiError(ERR_INVALID_STATE,
                       "Mitigation credit requires raw escalation tier 3", 409)

    esc["director_credit_days"] += body["credit_days"]
    # effective_tier recomputed from net count; stored raw tier untouched
    refresh_escalation_effective(case)
    touch(esc)
    append_audit(case["id"], "ESCALATION_CREDIT_APPLIED", role, user_id,
                 f"Credit of {body['credit_days']} day(s) applied to escalation {eid}")
    return success_object(esc, 200)
