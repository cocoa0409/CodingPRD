"""Development plan and workload outing endpoints (PRD Section 3.7)."""
from decimal import Decimal

from flask import Blueprint

import auth
import calc
import common
import config
import derive
import envelope
import serialize
import store
import validate
from errors import ApiError

bp = Blueprint("plans", __name__)

LIVE_ASSIGNMENT_STATUSES = ("PENDING_CLEARANCE", "ACTIVE", "SUSPENDED")

TRANSITIONS = {
    "ACTIVATE": ("DRAFT",),
    "RECORD_PROGRESS": ("ACTIVE",),
    "REQUEST_REVISION": ("ACTIVE",),
    "RESUBMIT": ("REVISION_REQUESTED",),
    "MARK_ACHIEVED": ("ACTIVE",),
}


@bp.post("/assignments/<assignment_id>/development-plans")
def create_plan(assignment_id):
    auth.require(config.ROLE_FARM)
    assignment = common.need("assignments", assignment_id)
    body = validate.json_body()
    target_level = validate.enum_field(body, "target_level", config.LEVELS)
    curriculum = validate.str_field(body, "curriculum_version", min_len=1)
    modules = validate.enum_list_field(body, "curriculum_modules", None,
                                       min_len=1, max_len=12)
    limit = validate.dec_field(body, "workload_limit_weekly_index",
                               lo=Decimal("0.00"), hi=Decimal("10.00"),
                               required=False, default=Decimal("1.50"), places=2,
                               exclusive_lo=True)

    if assignment["status"] not in LIVE_ASSIGNMENT_STATUSES:
        raise ApiError("ERR_INVALID_ASSIGNMENT_STATE",
                       "A development plan cannot be attached to an assignment in status %s."
                       % assignment["status"])
    if curriculum != config.ORG_CURRICULUM_VERSION:
        raise ApiError("ERR_CURRICULUM_VERSION_MISMATCH")

    record = store.base_record()
    record.update({
        "assignment_id": assignment_id,
        "target_level": target_level,
        "curriculum_version": curriculum,
        "curriculum_modules": modules,
        "workload_limit_weekly_index": limit,
        "completed_module_count": 0,
        "completion_pct": Decimal("0.00"),
        "status": "DRAFT",
        "review_cycle_count": 0,
        "revision_note": None,
    })
    store.plans[record["id"]] = record
    common.commit()
    return envelope.object_response(serialize.plan(record), 201)


@bp.get("/assignments/<assignment_id>/development-plans")
def list_plans(assignment_id):
    auth.require(config.ROLE_FARM, config.ROLE_COMPLIANCE)
    common.need("assignments", assignment_id)
    rows = derive.plans_of_assignment(assignment_id)
    rows = common.apply_filters(rows, (("status", "status"),))
    return envelope.paginate(rows, serialize.plan)


@bp.post("/development-plans/<plan_id>/disposition")
def dispose_plan(plan_id):
    _user_id, role = auth.require(config.ROLE_FARM, config.ROLE_COMPLIANCE)
    raw = auth.raw_body()
    auth.check_action_role(raw.get("action"), role, config.PLAN_ACTION_ROLES)
    plan = common.need("plans", plan_id)
    body = validate.json_body()
    action = auth.require_action(body, config.PLAN_ACTION_ROLES)
    completed = validate.int_field(body, "completed_module_count", lo=0,
                                  required=False, default=None)
    revision_note = validate.str_field(body, "revision_note", required=False,
                                       default=None, allow_blank=True)

    if plan["status"] not in TRANSITIONS[action]:
        raise ApiError("ERR_INVALID_PLAN_STATE",
                       "A plan in status %s does not accept %s."
                       % (plan["status"], action))

    assignment = store.assignments.get(plan["assignment_id"])
    module_count = len(plan["curriculum_modules"])

    if action in ("ACTIVATE", "RESUBMIT"):
        if assignment is None or assignment["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_ASSIGNMENT_STATE",
                           "The owning assignment must be ACTIVE.")

    if action == "ACTIVATE":
        for other in derive.plans_of_assignment(plan["assignment_id"]):
            if other["id"] != plan["id"] and other["status"] == "ACTIVE":
                raise ApiError("ERR_DUPLICATE_ACTIVE_PLAN")
        if plan["curriculum_version"] != config.ORG_CURRICULUM_VERSION:
            raise ApiError("ERR_CURRICULUM_VERSION_MISMATCH")

    if action == "RECORD_PROGRESS":
        if completed is None:
            raise validate.bad("Field 'completed_module_count' is required.")
        if completed <= plan["completed_module_count"] or completed > module_count:
            raise validate.bad(
                "completed_module_count must be greater than the stored value and "
                "no greater than the number of curriculum modules.")

    if action == "REQUEST_REVISION":
        if plan["review_cycle_count"] >= config.MAX_PLAN_REVISIONS:
            raise ApiError("ERR_CYCLE_LIMIT_REACHED")

    if action == "MARK_ACHIEVED":
        if plan["completion_pct"] != Decimal("100.00"):
            raise ApiError("ERR_INVALID_PLAN_STATE",
                           "Every curriculum module must be completed first.")

    store.touch(plan)
    if action == "ACTIVATE":
        plan["status"] = "ACTIVE"
    elif action == "RECORD_PROGRESS":
        plan["completed_module_count"] = completed
    elif action == "REQUEST_REVISION":
        plan["status"] = "REVISION_REQUESTED"
        plan["revision_note"] = revision_note
        plan["review_cycle_count"] = plan["review_cycle_count"] + 1
    elif action == "RESUBMIT":
        plan["status"] = "ACTIVE"
    elif action == "MARK_ACHIEVED":
        plan["status"] = "ACHIEVED"

    common.commit()
    return envelope.object_response(serialize.plan(plan))


@bp.post("/assignments/<assignment_id>/workload-logs")
def create_workload_log(assignment_id):
    auth.require(config.ROLE_FARM, config.ROLE_MEDICAL)
    assignment = common.need("assignments", assignment_id)
    body = validate.json_body()
    log_date = validate.date_field(body, "log_date")
    pitches = validate.int_field(body, "pitches_thrown", lo=0, hi=250,
                                required=False, default=0)
    innings = validate.dec_field(body, "innings_pitched", lo=Decimal("0.0"),
                                 hi=Decimal("15.0"), required=False,
                                 default=Decimal("0.0"), places=1)
    minutes = validate.int_field(body, "high_intensity_minutes", lo=0, hi=300,
                                 required=False, default=0)
    is_rehab = validate.bool_field(body, "is_rehab_outing", required=False,
                                   default=False)

    if assignment["status"] not in LIVE_ASSIGNMENT_STATUSES:
        raise ApiError("ERR_INVALID_ASSIGNMENT_STATE",
                       "A workload outing cannot be logged against an assignment in status %s."
                       % assignment["status"])

    record = store.base_event_record()
    record.update({
        "assignment_id": assignment_id,
        "log_date": log_date,
        "pitches_thrown": pitches,
        "innings_pitched": innings,
        "high_intensity_minutes": minutes,
        "is_rehab_outing": is_rehab,
    })
    store.workload_logs[record["id"]] = record

    player = store.players.get(assignment["player_id"])
    if player is not None:
        actual, _projected = derive.player_workload(player)
        if actual > derive.effective_ceiling(assignment):
            del store.workload_logs[record["id"]]
            raise ApiError("ERR_WORKLOAD_CEILING_EXCEEDED")

    common.commit()
    return envelope.object_response(serialize.workload_log(record), 201)


@bp.get("/assignments/<assignment_id>/workload-logs")
def list_workload_logs(assignment_id):
    auth.require(config.ROLE_FARM, config.ROLE_MEDICAL, config.ROLE_COMPLIANCE)
    common.need("assignments", assignment_id)
    rows = derive.logs_of_assignment(assignment_id)
    wanted = common.bool_arg("is_rehab_outing")
    if wanted is not None:
        rows = [r for r in rows if r["is_rehab_outing"] == wanted]
    return envelope.paginate(rows, serialize.workload_log)
