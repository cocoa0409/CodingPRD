"""InclusionProgram endpoints: create/get/open/lock-allocation/
clear-climate-review/impact-report."""
from flask import Blueprint

from db import STORE
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE_TRANSITION, ERR_NOT_FOUND,
)
from middleware import (
    authenticate, body, req_int, req_str, sort_and_page,  # noqa: F401
)
from services import (
    allocation_waterfall, new_entity, program_json, standing_score, touch,
)
from util import fmt_dt, ok_list, ok_object, rhu2
from db import clock_now

bp = Blueprint("programs", __name__)

ALL_ROLES = ("DeiAdmin", "ExecutiveSponsor", "GroupLeader", "Employee")
GOAL_METRICS = {
    "TOTAL_ACTIVE_MEMBERS", "EVENTS_COMPLETED", "AVG_CAPACITY_UTILIZATION",
    "LATEST_CLIMATE_INDEX", "MENTORING_COMPLETED_COUNT",
}


def _get_program(program_id):
    p = STORE["programs"].get(program_id)
    if p is None:
        raise ApiError(ERR_NOT_FOUND, 404, "program not found")
    return p


def _validate_goals(raw):
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ApiError(ERR_INVALID_REQUEST, 400, "goals must be an array")
    goals = []
    for item in raw:
        if not isinstance(item, dict):
            raise ApiError(ERR_INVALID_REQUEST, 400, "each goal must be an object")
        metric = item.get("metric")
        if metric not in GOAL_METRICS:
            raise ApiError(ERR_INVALID_REQUEST, 400, "goal metric is not recognized")
        target = item.get("target_value")
        if isinstance(target, bool) or not isinstance(target, (int, float)):
            raise ApiError(ERR_INVALID_REQUEST, 400, "goal target_value must be numeric")
        goals.append({"metric": metric, "target_value": target})
    return goals


@bp.post("/v1/programs")
def create_program():
    authenticate(("DeiAdmin",))
    data = body()
    fiscal_year = req_int(data, "fiscal_year")
    pool_total_cents = req_int(data, "pool_total_cents", min_v=0)
    goals = _validate_goals(data.get("goals"))
    p = new_entity("programs", {
        "fiscal_year": fiscal_year,
        "pool_total_cents": pool_total_cents,
        "goals": goals,
        "status": "SETUP",
        "posture": "NORMAL",
    })
    resp, code = ok_object(program_json(p), 201)
    return resp, code


@bp.get("/v1/programs/<program_id>")
def get_program(program_id):
    authenticate(ALL_ROLES)
    return ok_object(program_json(_get_program(program_id)))


@bp.post("/v1/programs/<program_id>/open")
def open_program(program_id):
    authenticate(("DeiAdmin",))
    p = _get_program(program_id)
    if p["status"] != "SETUP":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "program can only be opened from SETUP")
    p["status"] = "OPEN"
    touch(p)
    return ok_object(program_json(p))


@bp.post("/v1/programs/<program_id>/lock-allocation")
def lock_allocation(program_id):
    authenticate(("DeiAdmin",))
    p = _get_program(program_id)
    if p["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "allocation can only be locked from OPEN")
    allocation_waterfall(p)
    p["status"] = "ALLOCATION_LOCKED"
    touch(p)
    return ok_object(program_json(p))


@bp.post("/v1/programs/<program_id>/clear-climate-review")
def clear_climate_review(program_id):
    authenticate(("DeiAdmin",))
    data = body()
    req_str(data, "remediation_note")
    p = _get_program(program_id)
    if p["posture"] != "CLIMATE_REVIEW":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "program posture is not CLIMATE_REVIEW")
    p["posture"] = "NORMAL"
    touch(p)
    return ok_object(program_json(p))


@bp.get("/v1/programs/<program_id>/impact-report")
def impact_report(program_id):
    authenticate(ALL_ROLES)
    p = _get_program(program_id)
    pid = p["id"]
    groups = [g for g in STORE["groups"].values() if g["program_id"] == pid]
    group_ids = {g["id"] for g in groups}
    results = []
    for goal in p["goals"]:
        metric = goal["metric"]
        target = goal["target_value"]
        if metric == "TOTAL_ACTIVE_MEMBERS":
            from services import active_member_count
            actual = sum(active_member_count(g["id"]) for g in groups
                         if g["status"] in ("ACTIVE", "SUSPENDED"))
        elif metric == "EVENTS_COMPLETED":
            actual = sum(1 for e in STORE["events"].values()
                         if e["group_id"] in group_ids and e["status"] == "COMPLETED")
        elif metric == "AVG_CAPACITY_UTILIZATION":
            utils = [e["capacity_utilization_pct"] for e in STORE["events"].values()
                     if e["group_id"] in group_ids and e["status"] == "COMPLETED"]
            if utils:
                from decimal import Decimal
                actual = rhu2(sum(Decimal(str(u)) for u in utils) / Decimal(len(utils)))
            else:
                actual = 0
        elif metric == "LATEST_CLIMATE_INDEX":
            closed = [s for s in STORE["surveys"].values()
                      if s["program_id"] == pid and s["status"] == "CLOSED"]
            if closed:
                latest = max(closed, key=lambda s: (s["closes_at"], s["_seq"]))
                actual = latest["final_index"]
            else:
                actual = None
        elif metric == "MENTORING_COMPLETED_COUNT":
            actual = sum(1 for e in STORE["engagements"].values()
                         if e["program_id"] == pid and e["status"] == "COMPLETED")
        else:
            actual = None
        if actual is None:
            attainment = "MISSED"
        else:
            attainment = "ACHIEVED" if float(actual) >= float(target) else "MISSED"
        results.append({
            "metric": metric,
            "target_value": target,
            "actual_value": actual,
            "attainment": attainment,
        })
    return ok_object({
        "program_id": pid,
        "program_posture": p["posture"],
        "goal_results": results,
        "generated_at": fmt_dt(clock_now()),
    })
