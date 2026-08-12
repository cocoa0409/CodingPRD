"""Contingency plan and ignition plan routes."""
from flask import Blueprint

from core import (
    DB,
    ApiError,
    Validator,
    auth,
    body,
    ok,
    paginate,
    require_role,
    stamp_new,
    touch,
)
from domain import (
    get_contingency,
    get_ignition,
    get_plan,
    ser_contingency,
    ser_ignition,
)

bp = Blueprint("safety", __name__)


def _author_check(plan, uid):
    if uid != plan["author_boss_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Caller is not the plan's author")


def _sod_check(plan, uid):
    if uid == plan["author_boss_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES_VIOLATION",
            403,
            "Reviewer may not accept their own authored document",
        )


# ---------------------------------------------------------------------------
# Contingency plans
# ---------------------------------------------------------------------------


@bp.post("/burn-plans/<pid>/contingency-plans")
def create_contingency(pid):
    data = body()
    uid, role = auth()
    require_role(role, {"BurnBoss"})
    plan = get_plan(pid)
    _author_check(plan, uid)
    if plan["status"] != "APPROVED":
        raise ApiError("ERR_PLAN_NOT_APPROVED", 409, "Plan must be APPROVED")
    v = Validator(
        data,
        {
            "escape_trigger_points",
            "min_holding_personnel",
            "water_supply_description",
            "evacuation_route_description",
        },
    )
    v.req("escape_trigger_points", str)
    v.req("min_holding_personnel", int)
    if v.typed("min_holding_personnel", int) is not None and v.typed("min_holding_personnel", int) < 0:
        v.invalid("min_holding_personnel must be >= 0")
    v.req("water_supply_description", str)
    v.req("evacuation_route_description", str)
    v.finish()
    contingency = stamp_new(
        {
            "burn_plan_id": plan["id"],
            "escape_trigger_points": data["escape_trigger_points"],
            "min_holding_personnel": data["min_holding_personnel"],
            "water_supply_description": data["water_supply_description"],
            "evacuation_route_description": data["evacuation_route_description"],
            "status": "DRAFT",
        }
    )
    DB["contingencies"][contingency["id"]] = contingency
    return ok(ser_contingency(contingency), 201)


@bp.get("/contingency-plans/<cid>")
def get_one_contingency(cid):
    _, role = auth()
    require_role(role, None)
    return ok(ser_contingency(get_contingency(cid)))


@bp.get("/burn-plans/<pid>/contingency-plans")
def list_contingencies(pid):
    _, role = auth()
    require_role(role, None)
    plan = get_plan(pid)
    items = [c for c in DB["contingencies"].values() if c["burn_plan_id"] == plan["id"]]
    return paginate(items, ser_contingency)


@bp.post("/contingency-plans/<cid>/accept")
def accept_contingency(cid):
    body()
    uid, role = auth()
    require_role(role, {"AgencyReviewer"})
    contingency = get_contingency(cid)
    plan = DB["plans"].get(contingency["burn_plan_id"])
    if plan is not None:
        _sod_check(plan, uid)
    if contingency["status"] != "DRAFT":
        raise ApiError("ERR_CONTINGENCY_NOT_DRAFT", 409, "ContingencyPlan must be DRAFT")
    for other in DB["contingencies"].values():
        if (
            other["id"] != contingency["id"]
            and other["burn_plan_id"] == contingency["burn_plan_id"]
            and other["status"] == "ACCEPTED"
        ):
            raise ApiError(
                "ERR_CONTINGENCY_ALREADY_ACCEPTED",
                409,
                "Another contingency plan for the plan is already ACCEPTED",
            )
    contingency["status"] = "ACCEPTED"
    touch(contingency)
    return ok(ser_contingency(contingency))


@bp.post("/contingency-plans/<cid>/reject")
def reject_contingency(cid):
    data = body()
    _, role = auth()
    require_role(role, {"AgencyReviewer"})
    contingency = get_contingency(cid)
    if contingency["status"] != "DRAFT":
        raise ApiError("ERR_CONTINGENCY_NOT_DRAFT", 409, "ContingencyPlan must be DRAFT")
    v = Validator(data, {"reason"})
    v.opt("reason", str)
    v.finish()
    contingency["status"] = "REJECTED"
    touch(contingency)
    return ok(ser_contingency(contingency))


@bp.post("/contingency-plans/<cid>/revise")
def revise_contingency(cid):
    body()
    uid, role = auth()
    require_role(role, {"BurnBoss"})
    contingency = get_contingency(cid)
    plan = DB["plans"].get(contingency["burn_plan_id"])
    if plan is not None:
        _author_check(plan, uid)
    if contingency["status"] != "REJECTED":
        raise ApiError(
            "ERR_CONTINGENCY_NOT_REJECTED", 409, "ContingencyPlan must be REJECTED"
        )
    contingency["status"] = "DRAFT"
    touch(contingency)
    return ok(ser_contingency(contingency))


# ---------------------------------------------------------------------------
# Ignition plans
# ---------------------------------------------------------------------------


@bp.post("/burn-plans/<pid>/ignition-plans")
def create_ignition(pid):
    data = body()
    uid, role = auth()
    require_role(role, {"BurnBoss"})
    plan = get_plan(pid)
    _author_check(plan, uid)
    # OCC (priority 6) before business rules
    expected = data.get("expected_burn_plan_version")
    if expected is not None and isinstance(expected, int) and not isinstance(expected, bool):
        if expected != plan["version"]:
            raise ApiError(
                "ERR_STALE_VERSION",
                412,
                "expected_burn_plan_version does not match the plan's current version",
            )
    if plan["status"] != "APPROVED":
        raise ApiError("ERR_PLAN_NOT_APPROVED", 409, "Plan must be APPROVED")
    v = Validator(
        data,
        {"expected_burn_plan_version", "ignition_method", "test_fire_required", "steps"},
    )
    v.req("expected_burn_plan_version", int)
    v.enum("ignition_method", {"DRIP_TORCH", "AERIAL", "HAND_LINE"})
    v.req("test_fire_required", bool)
    steps = data.get("steps")
    if steps is None:
        v.invalid("Missing required field: steps")
    elif not isinstance(steps, list) or len(steps) < 1:
        v.invalid("steps must be a non-empty array")
    else:
        for idx, step in enumerate(steps):
            if not isinstance(step, dict):
                v.invalid(f"steps[{idx}] must be an object")
                break
            extra = set(step.keys()) - {"step_index", "zone_label", "technique"}
            if extra:
                v.invalid(f"steps[{idx}] has unknown field: {sorted(extra)[0]}")
                break
            si = step.get("step_index")
            zl = step.get("zone_label")
            tc = step.get("technique")
            if not (isinstance(si, int) and not isinstance(si, bool)):
                v.invalid(f"steps[{idx}].step_index must be an integer")
                break
            if not isinstance(zl, str) or not isinstance(tc, str):
                v.invalid(f"steps[{idx}] has an invalid type")
                break
            if si != idx + 1:
                v.invalid("steps step_index must be unique ascending from 1")
                break
    v.finish()
    # supersede all prior ignition plans on this plan (version-silent on them)
    for other in DB["ignition_plans"].values():
        if other["burn_plan_id"] == plan["id"] and other["status"] in (
            "DRAFT",
            "ACCEPTED",
            "REJECTED",
        ):
            other["status"] = "SUPERSEDED"
    ignition = stamp_new(
        {
            "burn_plan_id": plan["id"],
            "ignition_method": data["ignition_method"],
            "test_fire_required": data["test_fire_required"],
            "steps": data["steps"],
            "status": "DRAFT",
        }
    )
    DB["ignition_plans"][ignition["id"]] = ignition
    touch(plan)  # filing an ignition plan advances the burn plan's version
    return ok(ser_ignition(ignition), 201)


@bp.get("/ignition-plans/<iid>")
def get_one_ignition(iid):
    _, role = auth()
    require_role(role, None)
    return ok(ser_ignition(get_ignition(iid)))


@bp.get("/burn-plans/<pid>/ignition-plans")
def list_ignitions(pid):
    _, role = auth()
    require_role(role, None)
    plan = get_plan(pid)
    items = [i for i in DB["ignition_plans"].values() if i["burn_plan_id"] == plan["id"]]
    return paginate(items, ser_ignition)


@bp.post("/ignition-plans/<iid>/accept")
def accept_ignition(iid):
    body()
    uid, role = auth()
    require_role(role, {"AgencyReviewer"})
    ignition = get_ignition(iid)
    plan = DB["plans"].get(ignition["burn_plan_id"])
    if plan is not None:
        _sod_check(plan, uid)
    if ignition["status"] != "DRAFT":
        raise ApiError("ERR_IGNITION_PLAN_NOT_DRAFT", 409, "IgnitionPlan must be DRAFT")
    ignition["status"] = "ACCEPTED"
    touch(ignition)
    return ok(ser_ignition(ignition))


@bp.post("/ignition-plans/<iid>/reject")
def reject_ignition(iid):
    data = body()
    _, role = auth()
    require_role(role, {"AgencyReviewer"})
    ignition = get_ignition(iid)
    if ignition["status"] != "DRAFT":
        raise ApiError("ERR_IGNITION_PLAN_NOT_DRAFT", 409, "IgnitionPlan must be DRAFT")
    v = Validator(data, {"reason"})
    v.opt("reason", str)
    v.finish()
    ignition["status"] = "REJECTED"
    touch(ignition)
    return ok(ser_ignition(ignition))


@bp.post("/ignition-plans/<iid>/revise")
def revise_ignition(iid):
    body()
    uid, role = auth()
    require_role(role, {"BurnBoss"})
    ignition = get_ignition(iid)
    plan = DB["plans"].get(ignition["burn_plan_id"])
    if plan is not None:
        _author_check(plan, uid)
    if ignition["status"] != "REJECTED":
        raise ApiError(
            "ERR_IGNITION_PLAN_NOT_REJECTED", 409, "IgnitionPlan must be REJECTED"
        )
    ignition["status"] = "DRAFT"
    touch(ignition)
    return ok(ser_ignition(ignition))
