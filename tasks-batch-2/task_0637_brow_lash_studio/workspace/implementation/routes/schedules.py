"""RecurringFillSchedule routes (PRD §3.6, §3.7)."""
from datetime import timedelta

from flask import Blueprint, request

import errors
from common import (bad_request, get_json_body, parse_pagination, paginate,
                    require_int, require_str, sort_by_created, stamp_create, touch)
from db import store
from lookups import (get_member_or_404, get_schedule_or_404, get_service_type_or_404,
                     ownership_member, parse_dt_or_400)
from middleware import get_user_context, require_role
from response import success_list, success_object
from services import booking
import serialize

bp = Blueprint("schedules", __name__)

MIN_FILL_GAP_DAYS = 5
MAX_FILL_WINDOW_DAYS = 21


@bp.route("/recurring-schedules", methods=["POST"])
def create_schedule():
    user_id, role = get_user_context()
    require_role(role, {"StudioManager", "FrontDesk", "Member"})
    body = get_json_body()
    member_id = require_str(body, "member_id")
    member = get_member_or_404(member_id)
    ownership_member(role, user_id, member["id"])

    service_type_id = require_str(body, "service_type_id")
    service_type = get_service_type_or_404(service_type_id)
    if service_type["studio_id"] != member["studio_id"]:
        raise errors.ApiError(errors.ERR_SERVICE_TYPE_NOT_FOUND, 404,
                              "Service type not in member's studio.")
    # service_type must reference a FILL service (PRD §3.6).
    if service_type["code"] != "FILL":
        raise errors.ApiError(errors.ERR_SCHEDULE_NOT_FILL_SERVICE, 409,
                              "Recurring schedule service must be a FILL service.")

    cadence_days = require_int(body, "cadence_days")
    if not (MIN_FILL_GAP_DAYS <= cadence_days <= MAX_FILL_WINDOW_DAYS):
        raise bad_request("cadence_days must be between 5 and 21 inclusive.")
    first_start = parse_dt_or_400(body, "first_start_utc")

    rec = {
        "member_id": member["id"],
        "service_type_id": service_type["id"],
        "cadence_days": cadence_days,
        "first_start_utc": first_start,
        "next_due_utc": first_start,
        "spawned_count": 0,
        "status": "ACTIVE",
    }
    stamp_create(rec)
    store.recurring_schedules[rec["id"]] = rec
    return success_object(serialize.recurring_schedule_out(rec), status=201)


@bp.route("/recurring-schedules", methods=["GET"])
def list_schedules():
    user_id, role = get_user_context()
    require_role(role, {"StudioManager", "FrontDesk", "Member"})
    limit, offset = parse_pagination()
    member_id = request.args.get("member_id")
    service_type_id = request.args.get("service_type_id")
    items = list(store.recurring_schedules.values())
    if member_id is not None:
        items = [s for s in items if s["member_id"] == member_id]
    if service_type_id is not None:
        items = [s for s in items if s["service_type_id"] == service_type_id]
    if role == "Member":
        items = [s for s in items if s["member_id"] == user_id]
    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([serialize.recurring_schedule_out(s) for s in page], limit, offset, total)


@bp.route("/recurring-schedules/<sid>", methods=["GET"])
def get_schedule(sid):
    user_id, role = get_user_context()
    require_role(role, {"StudioManager", "FrontDesk", "Member"})
    s = get_schedule_or_404(sid)
    ownership_member(role, user_id, s["member_id"])
    return success_object(serialize.recurring_schedule_out(s))


@bp.route("/recurring-schedules/<sid>/spawn-next", methods=["POST"])
def spawn_next(sid):
    _, role = get_user_context()
    require_role(role, {"FrontDesk", "StudioManager"})
    sched = get_schedule_or_404(sid)
    body = get_json_body()
    expected_version = require_int(body, "expected_membership_version")

    # State (priority 5): schedule must be ACTIVE.
    if sched["status"] != "ACTIVE":
        raise errors.ApiError(errors.ERR_INVALID_SCHEDULE_STATE, 409,
                              "Schedule must be ACTIVE to spawn.")

    member = store.members[sched["member_id"]]
    service_type = store.service_types.get(sched["service_type_id"])

    # The member's membership is resolved here (spawn pays with credits). The
    # ACTIVE-state gate (ERR_MEMBERSHIP_NOT_BOOKABLE) is enforced at its proper
    # priority (11) inside run_booking, after patch-test/fill/sanitation/overlap.
    membership = _membership_for_member(member["id"])
    if membership is None:
        raise errors.ApiError(errors.ERR_MEMBERSHIP_NOT_BOOKABLE, 409,
                              "Member has no membership to charge credits against.")

    start_utc = sched["next_due_utc"]

    appt = booking.run_booking(
        member=member,
        service_type=service_type,
        start_utc=start_utc,
        pay_with_credits=True,
        membership=membership,
        expected_membership_version=expected_version,
        recurring_schedule_id=sched["id"],
        schedule_context=True,
    )
    # After a successful spawn: next_due_utc += cadence_days; spawned_count += 1.
    sched["next_due_utc"] = sched["next_due_utc"] + timedelta(days=sched["cadence_days"])
    sched["spawned_count"] = sched["spawned_count"] + 1
    touch(sched)
    return success_object(serialize.appointment_out(appt), status=201)


def _membership_for_member(member_id):
    """Resolve the member's membership to charge for a spawn. Prefer an ACTIVE
    one; otherwise the earliest-created so the priority-11 ACTIVE gate inside
    run_booking surfaces ERR_MEMBERSHIP_NOT_BOOKABLE on a non-ACTIVE state."""
    candidates = [m for m in store.memberships.values() if m["member_id"] == member_id]
    if not candidates:
        return None
    active = [m for m in candidates if m["status"] == "ACTIVE"]
    pool = active if active else candidates
    pool.sort(key=lambda m: m.get("_seq", 0))
    return pool[0]


@bp.route("/recurring-schedules/<sid>/pause", methods=["POST"])
def pause_schedule(sid):
    user_id, role = get_user_context()
    require_role(role, {"Member", "FrontDesk", "StudioManager"})
    s = get_schedule_or_404(sid)
    ownership_member(role, user_id, s["member_id"])
    if s["status"] != "ACTIVE":
        raise errors.ApiError(errors.ERR_INVALID_SCHEDULE_STATE, 409, "Schedule must be ACTIVE to pause.")
    s["status"] = "PAUSED"
    touch(s)
    return success_object(serialize.recurring_schedule_out(s))


@bp.route("/recurring-schedules/<sid>/resume", methods=["POST"])
def resume_schedule(sid):
    user_id, role = get_user_context()
    require_role(role, {"Member", "FrontDesk", "StudioManager"})
    s = get_schedule_or_404(sid)
    ownership_member(role, user_id, s["member_id"])
    if s["status"] != "PAUSED":
        raise errors.ApiError(errors.ERR_INVALID_SCHEDULE_STATE, 409, "Schedule must be PAUSED to resume.")
    s["status"] = "ACTIVE"
    touch(s)
    return success_object(serialize.recurring_schedule_out(s))


@bp.route("/recurring-schedules/<sid>/end", methods=["POST"])
def end_schedule(sid):
    user_id, role = get_user_context()
    require_role(role, {"Member", "FrontDesk", "StudioManager"})
    s = get_schedule_or_404(sid)
    ownership_member(role, user_id, s["member_id"])
    # ACTIVE or PAUSED -> ENDED.
    if s["status"] not in ("ACTIVE", "PAUSED"):
        raise errors.ApiError(errors.ERR_INVALID_SCHEDULE_STATE, 409, "Schedule cannot be ended from its current state.")
    s["status"] = "ENDED"
    touch(s)
    return success_object(serialize.recurring_schedule_out(s))
