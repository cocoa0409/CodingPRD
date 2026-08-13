"""Installation work orders: schedule, emergency review, mark installed
(PRD §3.7)."""
from datetime import datetime, time, timezone

from flask import Blueprint, g, request

from auth import require_roles, ALL_ROLES
from calc import crew_conflict
from envelope import object_response
from errors import (
    ApiError, ERR_WORK_ORDER_INVALID_STATE, ERR_EMERGENCY_REVIEW_BLOCKED,
    ERR_SCHEDULE_DATE_IN_PAST, ERR_CREW_SCHEDULE_CONFLICT,
    ERR_EMERGENCY_REVIEW_NOT_CLEARED, ERR_INSTALLATION_DATE_NOT_REACHED,
)
from helpers import get_work_order, paginated
from store import store, touch
from validate import parse_body, Struct

bp = Blueprint("workorders", __name__)

DECISIONS = ("CLEARED", "BLOCKED")


@bp.get("/api/installation-work-orders/<woId>")
@require_roles(*ALL_ROLES)
def get_one(woId):
    return object_response(get_work_order(woId))


@bp.get("/api/installation-work-orders")
@require_roles(*ALL_ROLES)
def list_work_orders():
    return paginated(list(store.work_orders.values()), {
        "request_id": request.args.get("request_id"),
        "crew_ref": request.args.get("crew_ref"),
        "schedule_status": request.args.get("schedule_status"),
    })


@bp.post("/api/installation-work-orders/<woId>/schedule")
@require_roles("TrafficEngineer")
def schedule(woId):
    wo = get_work_order(woId)
    data, perr = parse_body()
    s = Struct(data, perr)
    sched_date = s.get_date("scheduled_date")
    duration = s.get_int("duration_days", min=1)
    # Tier 5: schedule dimension must be UNSCHEDULED
    if wo["schedule_status"] != "UNSCHEDULED":
        raise ApiError(409, ERR_WORK_ORDER_INVALID_STATE,
                       "Only an UNSCHEDULED work order can be scheduled")
    # Tier 6: scheduling refused while the emergency review is BLOCKED
    if wo["emergency_review_status"] == "BLOCKED":
        raise ApiError(409, ERR_EMERGENCY_REVIEW_BLOCKED,
                       "Scheduling attempted while the emergency review is BLOCKED")
    # Tier 7: scheduled_date must not be earlier than the logical current date
    if sched_date is not None and sched_date < store.now.date():
        raise ApiError(409, ERR_SCHEDULE_DATE_IN_PAST,
                       "scheduled_date is before the logical current date")
    # Tier 8: structural
    s.raise_if_errors()
    # Tier 8: half-open crew overlap; adjacency allowed (PRD §3.7)
    if crew_conflict(wo["crew_ref"], sched_date, duration,
                     store.work_orders.values(), exclude_id=wo["id"]):
        raise ApiError(409, ERR_CREW_SCHEDULE_CONFLICT,
                       "The crew already has a SCHEDULED work order overlapping this interval")
    wo["scheduled_date"] = sched_date
    wo["duration_days"] = duration
    wo["schedule_status"] = "SCHEDULED"
    touch(wo)
    return object_response(wo)


@bp.post("/api/installation-work-orders/<woId>/emergency-review")
@require_roles("EmergencyReviewer")
def emergency_review(woId):
    wo = get_work_order(woId)
    data, perr = parse_body()
    s = Struct(data, perr)
    decision = s.get_enum("decision", DECISIONS)
    # Re-review of a blocked order is explicitly allowed (PRD §3.7)
    if wo["emergency_review_status"] not in ("PENDING_REVIEW", "BLOCKED"):
        raise ApiError(409, ERR_WORK_ORDER_INVALID_STATE,
                       "The emergency review dimension does not accept a decision now")
    s.raise_if_errors()
    wo["emergency_review_status"] = decision
    wo["reviewed_by_user_id"] = g.user_id
    # Blocking pulls a SCHEDULED order back off the calendar
    if decision == "BLOCKED" and wo["schedule_status"] == "SCHEDULED":
        wo["schedule_status"] = "UNSCHEDULED"
        wo["scheduled_date"] = None
        wo["duration_days"] = None
    touch(wo)
    return object_response(wo)


@bp.post("/api/installation-work-orders/<woId>/mark-installed")
@require_roles("TrafficEngineer")
def mark_installed(woId):
    wo = get_work_order(woId)
    if wo["schedule_status"] != "SCHEDULED":
        raise ApiError(409, ERR_WORK_ORDER_INVALID_STATE,
                       "Only a SCHEDULED work order can be marked installed")
    if wo["emergency_review_status"] != "CLEARED":
        raise ApiError(409, ERR_EMERGENCY_REVIEW_NOT_CLEARED,
                       "The emergency review dimension is not CLEARED")
    midnight = datetime.combine(wo["scheduled_date"], time.min, tzinfo=timezone.utc)
    if store.now < midnight:
        raise ApiError(409, ERR_INSTALLATION_DATE_NOT_REACHED,
                       "The scheduled date has not yet been reached")
    # Link 1: work order SCHEDULED -> INSTALLED
    wo["installed_at"] = store.now
    wo["schedule_status"] = "INSTALLED"
    touch(wo)
    # Link 2: bubble the request up to INSTALLED with the same instant
    req = store.requests[wo["request_id"]]
    req["status"] = "INSTALLED"
    req["installed_at"] = wo["installed_at"]
    touch(req)
    return object_response(wo)
