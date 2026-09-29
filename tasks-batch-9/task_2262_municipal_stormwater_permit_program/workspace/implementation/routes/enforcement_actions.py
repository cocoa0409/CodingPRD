"""The enforcement ladder and the penalty ledger."""

from flask import Blueprint

import enums
import middleware as mw
from db import DB, CLOCK, touch
from errors import ApiError
from middleware import body, get_enum, get_int, get_str, require
from routes.common import find, listing, one, require_active, settle, snapshot
from services import calc, derive, enforce

bp = Blueprint("enforcement_actions", __name__)

READERS = mw.OPERATIONAL_ROLES

SUBJECT_KEYS = (
    "illicit_discharge_case_id",
    "construction_site_id",
    "post_construction_facility_id",
)
COLLECTION_OF = {
    "illicit_discharge_case_id": "cases",
    "construction_site_id": "sites",
    "post_construction_facility_id": "facilities",
}


@bp.post("/enforcement-actions")
def issue_action():
    user_id, _role = require([mw.OFFICER])
    payload = body()
    action_type = get_enum(payload, "action_type", enums.ACTION_TYPE)
    violation_days = get_int(payload, "violation_days", required=False, default=0, minimum=0)
    supplied = {}
    for key in SUBJECT_KEYS:
        value = get_str(payload, key, required=False, default=None)
        if value is not None:
            supplied[key] = value
    source_inspection_id = get_str(payload, "source_inspection_id", required=False, default=None)

    for key, value in supplied.items():
        find(COLLECTION_OF[key], value)
    inspection = (
        find("inspections", source_inspection_id) if source_inspection_id is not None else None
    )

    term = None
    if len(supplied) == 1:
        subject_key, subject_id = next(iter(supplied.items()))
        term = enforce.term_of(subject_key, subject_id)
        require_active(term)
    if len(supplied) != 1:
        raise ApiError("ERR_ENFORCEMENT_SUBJECT_INVALID")

    if inspection is not None:
        if inspection["status"] != "FINALIZED":
            raise ApiError("ERR_SOURCE_INSPECTION_NOT_FINALIZED")
        if inspection.get(subject_key) != subject_id:
            raise ApiError("ERR_ENFORCEMENT_SUBJECT_INVALID")
        if inspection.get("finalized_by_user_id") == user_id:
            raise ApiError("ERR_INSPECTOR_CANNOT_ENFORCE")

    if subject_key == "illicit_discharge_case_id":
        case = DB.cases[subject_id]
        if case["status"] == "RESOLVED" or not case.get("responsible_party"):
            raise ApiError("ERR_CASE_INVALID_STATE")

    before = snapshot(term)
    row = enforce.issue(
        action_type,
        subject_key,
        subject_id,
        violation_days=violation_days,
        source_inspection_id=source_inspection_id,
        user_id=user_id,
    )
    settle(term, before, CLOCK.now())
    return one(row, 201)


@bp.get("/enforcement-actions")
def list_actions():
    require(READERS)
    spec = {
        "illicit_discharge_case_id": ("illicit_discharge_case_id", None),
        "construction_site_id": ("construction_site_id", None),
        "post_construction_facility_id": ("post_construction_facility_id", None),
        "source_inspection_id": ("source_inspection_id", None),
        "status": ("status", enums.ENFORCEMENT_STATUS),
        "action_type": ("action_type", enums.ACTION_TYPE),
    }
    return listing(spec, lambda: list(DB.enforcement_actions.values()))


@bp.get("/enforcement-actions/<action_id>")
def read_action(action_id):
    require(READERS)
    return one(find("enforcement_actions", action_id))


@bp.post("/enforcement-actions/<action_id>/escalate")
def escalate_action(action_id):
    require([mw.OFFICER])
    payload = body()
    supplied_days = get_int(payload, "violation_days", required=False, default=None, minimum=0)
    action = find("enforcement_actions", action_id)
    if action["status"] not in enums.ENFORCEMENT_LIVE:
        raise ApiError("ERR_ENFORCEMENT_NOT_OPEN")
    rung = enums.LADDER.index(action["action_type"])
    if rung >= len(enums.LADDER) - 1:
        raise ApiError("ERR_LADDER_EXHAUSTED")

    reference = action.get("last_escalated_at") or action.get("issued_at")
    baseline = derive.to_dt(reference)
    if baseline is not None and CLOCK.now() - baseline < calc.COOLING_OFF:
        raise ApiError("ERR_ESCALATION_COOLING_OFF")

    stored_days = int(action.get("violation_days") or 0)
    if supplied_days is not None and supplied_days < stored_days:
        raise ApiError("ERR_PENALTY_DECREASE_FORBIDDEN")
    days = stored_days if supplied_days is None else supplied_days

    subject_key, subject_id = derive.subject_key_of(action)
    term = enforce.term_of(subject_key, subject_id)
    before = snapshot(term)

    new_type = enums.LADDER[rung + 1]
    prior = enforce.prior_total(subject_key, subject_id, exclude_id=action["id"])
    billable, prior_cents, multiplier, amount = calc.penalty(new_type, days, prior)
    action["action_type"] = new_type
    action["violation_days"] = days
    action["billable_violation_days"] = billable
    action["prior_assessed_total_cents"] = prior_cents
    action["escalation_multiplier"] = float(multiplier)
    action["penalty_cents"] = amount
    action["status"] = "ESCALATED"
    action["escalation_count"] = int(action.get("escalation_count") or 0) + 1
    action["last_escalated_at"] = CLOCK.stamp()
    touch(action)
    settle(term, before, CLOCK.now())
    return one(action)


@bp.post("/enforcement-actions/<action_id>/close")
def close_action(action_id):
    require([mw.OFFICER])
    payload = body()
    note = get_str(payload, "compliance_note")
    action = find("enforcement_actions", action_id)
    if action["status"] not in enums.ENFORCEMENT_LIVE:
        raise ApiError("ERR_ENFORCEMENT_NOT_OPEN")

    subject_key, subject_id = derive.subject_key_of(action)
    term = enforce.term_of(subject_key, subject_id)
    before = snapshot(term)
    action["status"] = "CLOSED"
    action["closed_at"] = CLOCK.stamp()
    action["compliance_note"] = note
    touch(action)
    settle(term, before, CLOCK.now())
    return one(action)


@bp.post("/enforcement-actions/<action_id>/rescind")
def rescind_action(action_id):
    require([mw.OFFICER])
    payload = body()
    reason = get_str(payload, "reason")
    action = find("enforcement_actions", action_id)
    if action["status"] not in enums.ENFORCEMENT_LIVE:
        raise ApiError("ERR_ENFORCEMENT_NOT_OPEN")
    if int(action.get("escalation_count") or 0) > 0:
        raise ApiError("ERR_RESCIND_AFTER_ESCALATION")

    subject_key, subject_id = derive.subject_key_of(action)
    term = enforce.term_of(subject_key, subject_id)
    before = snapshot(term)
    action["status"] = "RESCINDED"
    action["rescinded_at"] = CLOCK.stamp()
    action["rescinded_reason"] = reason
    action["penalty_cents"] = 0
    touch(action)
    settle(term, before, CLOCK.now())
    return one(action)
