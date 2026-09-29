"""Engagements: chartering, the two state axes, emergency stop and resumption."""
from decimal import Decimal

from flask import Blueprint, g, request

import core
import serialize
from auth import authorize, require_role
from core import new_record, recompute_coverage, recompute_ranks, touch
from envelope import object_response
from errors import ApiError
from resolve import filtered, get_engagement, get_scope_item, get_test_plan, paginate
from store import store
from validate import body, get_datetime, get_enum, get_number, get_str

bp = Blueprint("engagements", __name__)

ENGAGEMENT_TYPES = ("APPLICATION_TEST", "NETWORK_TEST", "CLOUD_REVIEW")
EXECUTION_ACTIONS = ("START", "COMPLETE_FIELDWORK", "REPORT", "CLOSE")
STOP_CODES = ("PAUSE", "TERMINATE")
READ_ROLES = ("ProgramManager", "ComplianceOfficer", "PlatformAdmin", "Tester")

EXECUTION_TRANSITIONS = {
    "START": ("PLANNED", "EXECUTING"),
    "COMPLETE_FIELDWORK": ("EXECUTING", "FIELDWORK_COMPLETE"),
    "REPORT": ("FIELDWORK_COMPLETE", "REPORTED"),
    "CLOSE": ("REPORTED", "CLOSED"),
}


@bp.post("/engagements")
def charter_engagement():
    authorize("ProgramManager")
    data = body()
    plan_id = get_str(data, "test_plan_id")
    item_id = get_str(data, "scope_item_id")
    engagement_type = get_enum(data, "engagement_type", ENGAGEMENT_TYPES)
    start_raw, window_start = get_datetime(data, "window_start")
    end_raw, window_end = get_datetime(data, "window_end")
    hours = get_number(data, "hours_allocated", minimum=0, exclusive_min=True, maximum=2000)
    if not window_end > window_start:
        raise ApiError("ERR_INVALID_REQUEST", "window_end must fall strictly after window_start.")
    plan = get_test_plan(plan_id)
    item = get_scope_item(item_id)
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_PLAN_NOT_ACTIVE")
    if item["status"] != "APPROVED" or item["test_plan_id"] != plan["id"]:
        raise ApiError("ERR_SCOPE_ITEM_NOT_APPROVED")
    if len(core.plan_engagements(plan["id"])) >= plan["planned_engagement_count"]:
        raise ApiError("ERR_PLAN_ENGAGEMENT_LIMIT_REACHED")
    record = new_record(
        test_plan_id=plan["id"],
        scope_item_id=item["id"],
        engagement_type=engagement_type,
        window_start=window_start,
        window_start_raw=start_raw,
        window_end=window_end,
        window_end_raw=end_raw,
        hours_allocated=hours,
        hours_reserved=Decimal("0"),
        hours_consumed=Decimal("0"),
        hours_available=hours,
        execution_state="PLANNED",
        authorization_state="ROE_PENDING",
        suspension_reason=None,
        provisional_assurance_score=None,
        final_assurance_score=None,
    )
    store.engagements[record["id"]] = record
    item["status"] = "CONSUMED"
    item["priority_rank"] = None
    touch(item)
    recompute_ranks(plan["id"])
    recompute_coverage(plan)
    touch(plan)
    return object_response(serialize.engagement(record), 201)


@bp.get("/engagements/<engagement_id>")
def read_engagement(engagement_id):
    authorize(*READ_ROLES)
    return object_response(serialize.engagement(get_engagement(engagement_id)))


@bp.get("/engagements")
def list_engagements():
    authorize(*READ_ROLES)
    rows = filtered(
        list(store.engagements.values()),
        test_plan_id=request.args.get("test_plan_id"),
        scope_item_id=request.args.get("scope_item_id"),
        execution_state=request.args.get("execution_state"),
        authorization_state=request.args.get("authorization_state"),
    )
    return paginate(rows, serialize.engagement)


@bp.post("/engagements/<engagement_id>/execution")
def drive_execution(engagement_id):
    authorize("ProgramManager", "Tester")
    engagement = get_engagement(engagement_id)
    data = body()
    action = get_enum(data, "action", EXECUTION_ACTIONS)
    if action in ("REPORT", "CLOSE"):
        require_role("ProgramManager")
    if engagement["authorization_state"] == "SUSPENDED":
        raise ApiError("ERR_ENGAGEMENT_SUSPENDED")
    if action == "START" and engagement["authorization_state"] != "AUTHORIZED":
        raise ApiError("ERR_ENGAGEMENT_NOT_AUTHORIZED")
    source, target = EXECUTION_TRANSITIONS[action]
    if engagement["execution_state"] != source:
        raise ApiError("ERR_INVALID_EXECUTION_TRANSITION")
    if action == "REPORT":
        for finding in core.engagement_findings(engagement["id"]):
            if finding["status"] == "REPORTED":
                raise ApiError("ERR_FINDING_NOT_TRIAGED")
    if action in ("COMPLETE_FIELDWORK", "CLOSE"):
        for alert in core.engagement_alerts(engagement["id"]):
            if alert["state"] == "RAISED":
                raise ApiError("ERR_UNACKNOWLEDGED_CRITICAL_ALERT")
    if action == "START":
        now = store.now()
        if now < engagement["window_start"] or now > engagement["window_end"]:
            raise ApiError("ERR_OUTSIDE_TESTING_WINDOW")
    engagement["execution_state"] = target
    if action == "COMPLETE_FIELDWORK":
        core.stamp_provisional_assurance(engagement)
    touch(engagement)
    if action == "CLOSE":
        core.stamp_final_assurance(engagement)
        core.revoke_live_assignments(engagement["id"])
        core.bubble_up(core.plan_of_engagement(engagement))
    return object_response(serialize.engagement(engagement))


@bp.post("/engagements/<engagement_id>/emergency-stop")
def emergency_stop(engagement_id):
    authorize("ProgramManager", "ComplianceOfficer")
    engagement = get_engagement(engagement_id)
    data = body()
    stop_code = get_enum(data, "stop_code", STOP_CODES)
    if stop_code == "TERMINATE":
        require_role("ComplianceOfficer")
    reason = get_str(data, "reason", min_len=1)
    if engagement["authorization_state"] not in ("AUTHORIZED", "SUSPENDED"):
        raise ApiError("ERR_ENGAGEMENT_ALREADY_TERMINATED")
    if stop_code == "PAUSE":
        if engagement["authorization_state"] != "AUTHORIZED":
            raise ApiError("ERR_ENGAGEMENT_SUSPENDED")
        core.cascade_pause(engagement, reason)
    else:
        core.cascade_terminate(engagement, reason)
    return object_response(serialize.engagement(engagement))


@bp.post("/engagements/<engagement_id>/resume")
def resume_engagement(engagement_id):
    authorize("ComplianceOfficer")
    engagement = get_engagement(engagement_id)
    data = body()
    get_str(data, "resume_note", required=False)
    if (
        engagement["authorization_state"] != "SUSPENDED"
        or engagement["execution_state"] == "CLOSED"
    ):
        raise ApiError("ERR_ENGAGEMENT_NOT_SUSPENDED")
    core.cascade_resume(engagement)
    return object_response(serialize.engagement(engagement))
