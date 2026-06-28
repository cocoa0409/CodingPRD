"""VacationFeedingPlan + logical clock endpoints (PRD §3.11)."""

from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import get_auth, require_roles
from response import object_response
from serializers import feeding_plan_view
import common as C

bp = Blueprint("feeding_plans", __name__)


def evaluate_feeding_plans():
    """Auto-transition feeding plans whose window boundaries the clock crossed.

    SCHEDULED -> ACTIVE when current_utc >= window_start and home system ACTIVE.
    ACTIVE    -> COMPLETED when current_utc >= window_end.
    """
    now = store.current_utc
    for plan in store.feeding_plans.values():
        if plan["status"] == "SCHEDULED":
            start = C.parse_iso(plan["window_start"])
            if now >= start:
                home = store.systems.get(plan["system_id"])
                if home is not None and home["status"] == "ACTIVE":
                    plan["status"] = "ACTIVE"
                    C.touch(plan)
        if plan["status"] == "ACTIVE":
            end = C.parse_iso(plan["window_end"])
            if now >= end:
                plan["status"] = "COMPLETED"
                C.touch(plan)


@bp.post("/aquatics/feeding-plans")
def create_feeding_plan():
    _, role = get_auth()
    require_roles(role, {"CustomerOwner", "AccountManager"})
    data = C.require_body(request.get_json(silent=True))
    system_id = C.req_str(data, "system_id")
    window_start = C.req_datetime(data, "window_start")
    window_end = C.req_datetime(data, "window_end")
    feedings_per_day = C.req_int(data, "feedings_per_day", minimum=1, maximum=6)

    system = store.systems.get(system_id)
    if system is None:
        raise ApiError("ERR_NOT_FOUND", "System not found.")

    # window ordering: window_start < window_end (half-open)
    s_dt = C.parse_iso(window_start)
    e_dt = C.parse_iso(window_end)
    if not (s_dt < e_dt):
        raise ApiError("ERR_BAD_WINDOW", "window_start must be before window_end.")

    rec = C.make_record({
        "system_id": system_id,
        "window_start": window_start,
        "window_end": window_end,
        "feedings_per_day": feedings_per_day,
        "status": "SCHEDULED",
    })
    store.feeding_plans[rec["id"]] = rec
    return object_response(feeding_plan_view(rec), 201)


@bp.get("/aquatics/feeding-plans/<pid>")
def get_feeding_plan(pid):
    _, role = get_auth()
    require_roles(role, {"CustomerOwner", "AccountManager", "Dispatcher"})
    rec = store.feeding_plans.get(pid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Feeding plan not found.")
    return object_response(feeding_plan_view(rec))


@bp.post("/aquatics/feeding-plans/<pid>/cancel")
def cancel_feeding_plan(pid):
    user_id, role = get_auth()
    require_roles(role, {"CustomerOwner"})
    rec = store.feeding_plans.get(pid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Feeding plan not found.")
    # ownership (priority 3): caller must own the plan's contract
    system = store.systems.get(rec["system_id"])
    contract = store.contracts.get(system["contract_id"]) if system else None
    if contract is None or contract["customer_user_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Caller does not own this contract.")
    if rec["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "Only a SCHEDULED plan may be cancelled.")
    rec["status"] = "CANCELLED"
    C.touch(rec)
    return object_response(feeding_plan_view(rec))


# ===========================================================================
# Logical clock (PRD §3.11) — mounted outside the /aquatics prefix
# ===========================================================================
clock_bp = Blueprint("clock", __name__)


@clock_bp.post("/_clock/set_current_utc")
def set_current_utc():
    _, role = get_auth()
    require_roles(role, {"AccountManager", "Dispatcher"})
    data = C.require_body(request.get_json(silent=True))
    to_iso = C.req_datetime(data, "to_iso8601")
    store.current_utc = C.parse_iso(to_iso)
    # auto-evaluate feeding plans
    evaluate_feeding_plans()
    return object_response({})
