"""TrainingPlan and TrainingSession endpoints."""

from flask import Blueprint, request

import errors
import validation as v
from db import store, new_entity, touch
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list

bp = Blueprint("training", __name__)


@bp.post("/api/training-plans")
def create_training_plan():
    require_roles(["VisionSpecialist"])
    body = v.require_body(request.get_json(silent=True))
    v.reject_unknown_fields(body, {"client_id", "device_order_id", "total_sessions"})
    client_id = v.req_string(body, "client_id")
    device_order_id = v.req_string(body, "device_order_id")
    total_sessions = v.req_int(body, "total_sessions", min_v=1, max_v=20)

    if client_id not in store.clients:
        raise errors.not_found("Client not found")
    order = store.device_orders.get(device_order_id)
    if order is None:
        raise errors.not_found("DeviceOrder not found")
    if order["client_id"] != client_id:
        raise errors.validation("device_order_id does not belong to client_id")
    if order["status"] not in ("ACTIVE", "CONVERTED"):
        raise errors.order_not_active()

    plan = new_entity()
    plan.update({
        "client_id": client_id,
        "device_order_id": device_order_id,
        "total_sessions": total_sessions,
        "completed_sessions": 0,
        "no_show_count": 0,
        "status": "PLANNED",
    })
    store.training_plans[plan["id"]] = plan
    return success_object(plan, status=201)


@bp.get("/api/training-plans/<pid>")
def get_training_plan(pid):
    require_roles(ALL_ROLES)
    plan = store.training_plans.get(pid)
    if plan is None:
        raise errors.not_found("TrainingPlan not found")
    return success_object(plan)


@bp.get("/api/training-plans")
def list_training_plans():
    require_roles(ALL_ROLES)
    limit, offset = v.parse_pagination(request.args)
    items = v.apply_filters(list(store.training_plans.values()), [
        (request.args.get("client_id"), "client_id"),
        (request.args.get("device_order_id"), "device_order_id"),
        (request.args.get("status"), "status"),
    ])
    items = v.sort_by_created(items)
    total = len(items)
    return success_list(items[offset:offset + limit], limit, offset, total)


@bp.post("/api/training-plans/<pid>/sessions")
def schedule_session(pid):
    require_roles(["VisionSpecialist"])
    body = v.require_body(request.get_json(silent=True))
    v.reject_unknown_fields(body, {"instructor_user_id", "scheduled_start", "scheduled_end"})
    instructor_user_id = v.req_string(body, "instructor_user_id")
    scheduled_start = v.req_datetime(body, "scheduled_start")
    scheduled_end = v.req_datetime(body, "scheduled_end")
    if not (scheduled_start < scheduled_end):
        raise errors.validation("scheduled_start must be strictly before scheduled_end")

    plan = store.training_plans.get(pid)
    if plan is None:
        raise errors.not_found("TrainingPlan not found")
    if plan["status"] in ("SUSPENDED", "COMPLETED"):
        raise errors.plan_suspended()
    if plan["status"] not in ("PLANNED", "ACTIVE"):
        raise errors.invalid_state("Plan cannot accept sessions in its current state")

    # PRD §2.7 funnel: temporal windows and overlaps (level 9) are checked
    # before domain constraints such as plan session caps (level 10).

    # instructor half-open [start, end) overlap vs SCHEDULED/COMPLETED sessions
    for s in store.training_sessions.values():
        if s["instructor_user_id"] != instructor_user_id:
            continue
        if s["status"] not in ("SCHEDULED", "COMPLETED"):
            continue
        s_start = v.parse_datetime(s["scheduled_start"]) if isinstance(s["scheduled_start"], str) else s["scheduled_start"]
        s_end = v.parse_datetime(s["scheduled_end"]) if isinstance(s["scheduled_end"], str) else s["scheduled_end"]
        # overlap if new.start < existing.end AND existing.start < new.end
        if scheduled_start < s_end and s_start < scheduled_end:
            raise errors.session_overlap()

    # session cap: non-cancelled count below total_sessions
    non_cancelled = sum(
        1 for s in store.training_sessions.values()
        if s["training_plan_id"] == pid and s["status"] != "CANCELLED"
    )
    if non_cancelled >= plan["total_sessions"]:
        raise errors.plan_session_cap()

    from db import format_instant
    session = new_entity()
    session.update({
        "training_plan_id": pid,
        "instructor_user_id": instructor_user_id,
        "scheduled_start": format_instant(scheduled_start),
        "scheduled_end": format_instant(scheduled_end),
        "status": "SCHEDULED",
    })
    store.training_sessions[session["id"]] = session

    if plan["status"] == "PLANNED":
        plan["status"] = "ACTIVE"
        touch(plan)

    return success_object(session, status=201)


@bp.get("/api/training-plans/<pid>/sessions")
def list_plan_sessions(pid):
    require_roles(ALL_ROLES)
    plan = store.training_plans.get(pid)
    if plan is None:
        raise errors.not_found("TrainingPlan not found")
    limit, offset = v.parse_pagination(request.args)
    items = v.sort_by_created([
        s for s in store.training_sessions.values() if s["training_plan_id"] == pid
    ])
    total = len(items)
    return success_list(items[offset:offset + limit], limit, offset, total)


@bp.post("/api/training-sessions/<sid>/resolve")
def resolve_session(sid):
    require_roles(["VisionSpecialist"])
    body = v.require_body(request.get_json(silent=True))
    v.reject_unknown_fields(body, {"outcome"})
    outcome = v.req_enum(body, "outcome", {"COMPLETED", "NO_SHOW", "CANCELLED"})

    session = store.training_sessions.get(sid)
    if session is None:
        raise errors.not_found("TrainingSession not found")
    if session["status"] != "SCHEDULED":
        raise errors.invalid_state("Session is not SCHEDULED")

    plan = store.training_plans.get(session["training_plan_id"])

    session["status"] = outcome
    touch(session)

    if outcome == "COMPLETED" and plan is not None:
        plan["completed_sessions"] += 1
        if plan["status"] == "ACTIVE" and plan["completed_sessions"] == plan["total_sessions"]:
            plan["status"] = "COMPLETED"
        touch(plan)
    elif outcome == "NO_SHOW" and plan is not None:
        plan["no_show_count"] += 1
        if plan["status"] == "ACTIVE" and plan["no_show_count"] >= 2:
            plan["status"] = "SUSPENDED"
            touch(plan)
            # cascade: remaining SCHEDULED sessions of this plan -> CANCELLED
            for s in store.training_sessions.values():
                if s["training_plan_id"] == plan["id"] and s["status"] == "SCHEDULED":
                    s["status"] = "CANCELLED"
                    touch(s)
        else:
            touch(plan)

    return success_object(session)
