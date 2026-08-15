"""ErgEvent endpoints (plan/publish/reschedule/cancel/complete) and
EventRsvp endpoints (create/cancel/check-in) with waitlist promotion."""
from flask import Blueprint, request

from db import STORE, clock_now
from errors import (
    ApiError, ERR_ALREADY_RSVPED, ERR_CHECKIN_TOO_EARLY, ERR_EVENT_NOT_ENDED,
    ERR_EVENT_NOT_PUBLISHED, ERR_FUNDING_REQUEST_NOT_APPROVED,
    ERR_FUNDING_REQUEST_WRONG_GROUP, ERR_GROUP_NOT_ACTIVE, ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION, ERR_NOT_FOUND, ERR_NOT_GROUP_LEADER,
    ERR_STALE_EVENT_VERSION, ERR_VENUE_CAPACITY_EXCEEDED, ERR_VENUE_DOUBLE_BOOKED,
)
from middleware import (
    authenticate, body, opt_str, req_dt, req_enum, req_int, req_str, sort_and_page,
)
from services import (
    active_member_count, active_term_of, cancel_event_cascade, checked_in_count,
    event_impact_points, event_json, new_entity, registered_count, rsvp_json, touch,
)
from util import ok_list, ok_object, rhu2

bp = Blueprint("events", __name__)

ALL_ROLES = ("DeiAdmin", "ExecutiveSponsor", "GroupLeader", "Employee")
EVENT_CATEGORIES = ("WORKSHOP", "SOCIAL", "RECRUITING", "COMMUNITY")
EVENT_MANAGERS = ("GroupLeader", "DeiAdmin")


def get_event(event_id):
    e = STORE["events"].get(event_id)
    if e is None:
        raise ApiError(ERR_NOT_FOUND, 404, "event not found")
    return e


def get_rsvp(rsvp_id):
    r = STORE["rsvps"].get(rsvp_id)
    if r is None:
        raise ApiError(ERR_NOT_FOUND, 404, "rsvp not found")
    return r


def require_event_manager(user_id, role, group_id):
    """DeiAdmin always; GroupLeader must hold the group's ACTIVE term."""
    if role == "DeiAdmin":
        return
    term = active_term_of(group_id)
    if term is None or term["leader_employee_id"] != user_id:
        raise ApiError(ERR_NOT_GROUP_LEADER, 403, "caller does not lead this group")


def venue_conflict(venue_id, starts_at, ends_at, exclude_event_id=None):
    """Half-open overlap: conflict iff new.starts < existing.ends AND
    existing.starts < new.ends; touching endpoints do not conflict."""
    for e in STORE["events"].values():
        if e["venue_id"] != venue_id:
            continue
        if exclude_event_id is not None and e["id"] == exclude_event_id:
            continue
        if e["status"] not in ("PLANNED", "PUBLISHED"):
            continue
        if starts_at < e["ends_at"] and e["starts_at"] < ends_at:
            return True
    return False


@bp.post("/v1/events")
def create_event():
    user_id, role = authenticate(EVENT_MANAGERS)
    data = body()
    group_id = req_str(data, "group_id")
    venue_id = req_str(data, "venue_id")
    title = req_str(data, "title")
    category = req_enum(data, "category", EVENT_CATEGORIES)
    starts_at = req_dt(data, "starts_at")
    ends_at = req_dt(data, "ends_at")
    capacity = req_int(data, "capacity", min_v=1)
    funding_request_id = opt_str(data, "funding_request_id")
    now = clock_now()
    # 3 schema-range
    if ends_at <= starts_at:
        raise ApiError(ERR_INVALID_REQUEST, 400, "ends_at must be after starts_at")
    if starts_at <= now:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "starts_at must be after the current time")
    # 4 existence (left to right: group, venue, funding request)
    group = STORE["groups"].get(group_id)
    if group is None:
        raise ApiError(ERR_NOT_FOUND, 404, "group not found")
    venue = STORE["venues"].get(venue_id)
    if venue is None:
        raise ApiError(ERR_NOT_FOUND, 404, "venue not found")
    fr = None
    if funding_request_id is not None:
        fr = STORE["funding_requests"].get(funding_request_id)
        if fr is None:
            raise ApiError(ERR_NOT_FOUND, 404, "funding request not found")
    # 5 state
    if group["status"] != "ACTIVE":
        raise ApiError(ERR_GROUP_NOT_ACTIVE, 409, "group is not ACTIVE")
    # ownership
    require_event_manager(user_id, role, group_id)
    # 6 referential: linked funding request
    if fr is not None:
        if fr["group_id"] != group_id:
            raise ApiError(ERR_FUNDING_REQUEST_WRONG_GROUP, 409,
                           "funding request belongs to a different group")
        if fr["status"] != "APPROVED":
            raise ApiError(ERR_FUNDING_REQUEST_NOT_APPROVED, 409,
                           "linked funding request is not APPROVED")
    # 7 temporal: venue exclusivity
    if venue_conflict(venue_id, starts_at, ends_at):
        raise ApiError(ERR_VENUE_DOUBLE_BOOKED, 409,
                       "venue has an overlapping PLANNED or PUBLISHED event")
    # 9 capacity ceiling
    if capacity > venue["capacity"]:
        raise ApiError(ERR_VENUE_CAPACITY_EXCEEDED, 409,
                       "event capacity exceeds venue capacity")
    e = new_entity("events", {
        "group_id": group_id,
        "venue_id": venue_id,
        "funding_request_id": funding_request_id,
        "title": title,
        "category": category,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "capacity": capacity,
        "status": "PLANNED",
        "funding_status": "RESERVED" if fr is not None else "UNFUNDED",
        "capacity_utilization_pct": None,
        "member_engagement_pct": None,
        "impact_points": None,
        "low_attendance_flag": None,
    })
    return ok_object(event_json(e), 201)


@bp.get("/v1/events/<event_id>")
def read_event(event_id):
    authenticate(ALL_ROLES)
    return ok_object(event_json(get_event(event_id)))


@bp.get("/v1/events")
def list_events():
    authenticate(ALL_ROLES)
    items = list(STORE["events"].values())
    for param, field in (("group_id", "group_id"), ("venue_id", "venue_id"),
                         ("funding_request_id", "funding_request_id"),
                         ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            items = [e for e in items if e.get(field) == v]
    page, limit, offset, total = sort_and_page(items, event_json)
    return ok_list(page, limit, offset, total)


@bp.post("/v1/events/<event_id>/publish")
def publish_event(event_id):
    user_id, role = authenticate(EVENT_MANAGERS)
    e = get_event(event_id)
    if e["status"] != "PLANNED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "only a PLANNED event can be published")
    group = STORE["groups"][e["group_id"]]
    if group["status"] != "ACTIVE":
        raise ApiError(ERR_GROUP_NOT_ACTIVE, 409, "group is no longer ACTIVE")
    require_event_manager(user_id, role, e["group_id"])
    e["status"] = "PUBLISHED"
    touch(e)
    return ok_object(event_json(e))


@bp.post("/v1/events/<event_id>/reschedule")
def reschedule_event(event_id):
    user_id, role = authenticate(EVENT_MANAGERS)
    data = body()
    starts_at = req_dt(data, "starts_at")
    ends_at = req_dt(data, "ends_at")
    venue_id = opt_str(data, "venue_id")
    expected_event_version = req_int(data, "expected_event_version")
    now = clock_now()
    if ends_at <= starts_at:
        raise ApiError(ERR_INVALID_REQUEST, 400, "ends_at must be after starts_at")
    if starts_at <= now:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "starts_at must be after the current time")
    e = get_event(event_id)
    new_venue = None
    if venue_id is not None:
        new_venue = STORE["venues"].get(venue_id)
        if new_venue is None:
            raise ApiError(ERR_NOT_FOUND, 404, "venue not found")
    # 4.5 OCC
    if expected_event_version != e["version"]:
        raise ApiError(ERR_STALE_EVENT_VERSION, 412, "event version is stale")
    # 5 state: reschedule supersedes while PLANNED or PUBLISHED
    if e["status"] not in ("PLANNED", "PUBLISHED"):
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "event cannot be rescheduled in its current state")
    require_event_manager(user_id, role, e["group_id"])
    target_venue_id = venue_id if venue_id is not None else e["venue_id"]
    target_venue = new_venue if new_venue is not None else STORE["venues"][e["venue_id"]]
    # 7 temporal: overlap re-evaluated excluding self
    if venue_conflict(target_venue_id, starts_at, ends_at, exclude_event_id=e["id"]):
        raise ApiError(ERR_VENUE_DOUBLE_BOOKED, 409,
                       "venue has an overlapping PLANNED or PUBLISHED event")
    # 9 capacity ceiling when the venue changes
    if new_venue is not None and e["capacity"] > target_venue["capacity"]:
        raise ApiError(ERR_VENUE_CAPACITY_EXCEEDED, 409,
                       "event capacity exceeds venue capacity")
    e["starts_at"] = starts_at
    e["ends_at"] = ends_at
    if venue_id is not None:
        e["venue_id"] = venue_id
    touch(e)
    return ok_object(event_json(e))


@bp.post("/v1/events/<event_id>/cancel")
def cancel_event(event_id):
    user_id, role = authenticate(EVENT_MANAGERS)
    e = get_event(event_id)
    if e["status"] not in ("PLANNED", "PUBLISHED"):
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "event cannot be cancelled in its current state")
    require_event_manager(user_id, role, e["group_id"])
    cancel_event_cascade(e)
    return ok_object(event_json(e))


@bp.post("/v1/events/<event_id>/complete")
def complete_event(event_id):
    user_id, role = authenticate(EVENT_MANAGERS)
    e = get_event(event_id)
    if e["status"] != "PUBLISHED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "only a PUBLISHED event can be completed")
    require_event_manager(user_id, role, e["group_id"])
    if clock_now() < e["ends_at"]:
        raise ApiError(ERR_EVENT_NOT_ENDED, 409, "event has not ended yet")
    group = STORE["groups"][e["group_id"]]
    checked_in = checked_in_count(e["id"])
    e["capacity_utilization_pct"] = rhu2(
        100 * checked_in / e["capacity"]) if e["capacity"] else 0.0
    members = active_member_count(e["group_id"])
    e["member_engagement_pct"] = rhu2(100 * checked_in / members) if members else 0.0
    e["impact_points"] = event_impact_points(e, group)
    e["low_attendance_flag"] = e["capacity_utilization_pct"] < 25.00
    if e["funding_status"] == "RESERVED":
        e["funding_status"] = "SPENT"
    e["status"] = "COMPLETED"
    touch(e)
    return ok_object(event_json(e))


# ---------------------------------------------------------------------------
# RSVPs
# ---------------------------------------------------------------------------
@bp.post("/v1/rsvps")
def create_rsvp():
    user_id, _ = authenticate(("Employee",))
    data = body()
    event_id = req_str(data, "event_id")
    e = STORE["events"].get(event_id)
    if e is None:
        raise ApiError(ERR_NOT_FOUND, 404, "event not found")
    if e["status"] != "PUBLISHED":
        raise ApiError(ERR_EVENT_NOT_PUBLISHED, 409, "event is not PUBLISHED")
    for r in STORE["rsvps"].values():
        if (r["event_id"] == event_id and r["employee_id"] == user_id
                and r["status"] in ("REGISTERED", "WAITLISTED", "CHECKED_IN")):
            raise ApiError(ERR_ALREADY_RSVPED, 409,
                           "a live RSVP already exists for this pair")
    if registered_count(event_id) < e["capacity"]:
        r = new_entity("rsvps", {
            "event_id": event_id,
            "employee_id": user_id,
            "status": "REGISTERED",
            "waitlist_position": None,
        })
    else:
        positions = [x["waitlist_position"] for x in STORE["rsvps"].values()
                     if x["event_id"] == event_id and x["waitlist_position"] is not None]
        position = (max(positions) if positions else 0) + 1
        r = new_entity("rsvps", {
            "event_id": event_id,
            "employee_id": user_id,
            "status": "WAITLISTED",
            "waitlist_position": position,
        })
    return ok_object(rsvp_json(r), 201)


@bp.get("/v1/rsvps/<rsvp_id>")
def read_rsvp(rsvp_id):
    authenticate(ALL_ROLES)
    return ok_object(rsvp_json(get_rsvp(rsvp_id)))


@bp.get("/v1/rsvps")
def list_rsvps():
    authenticate(ALL_ROLES)
    items = list(STORE["rsvps"].values())
    for param, field in (("event_id", "event_id"), ("employee_id", "employee_id"),
                         ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if r.get(field) == v]
    page, limit, offset, total = sort_and_page(items, rsvp_json)
    return ok_list(page, limit, offset, total)


@bp.post("/v1/rsvps/<rsvp_id>/cancel")
def cancel_rsvp(rsvp_id):
    user_id, role = authenticate(("Employee", "GroupLeader", "DeiAdmin"))
    r = get_rsvp(rsvp_id)
    if r["status"] not in ("REGISTERED", "WAITLISTED"):
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "only a REGISTERED or WAITLISTED RSVP can be cancelled")
    e = STORE["events"].get(r["event_id"])
    if role == "Employee":
        if r["employee_id"] != user_id:
            raise ApiError(ERR_NOT_GROUP_LEADER, 403,
                           "employees may only cancel their own RSVP")
    elif role == "GroupLeader":
        term = active_term_of(e["group_id"]) if e else None
        if term is None or term["leader_employee_id"] != user_id:
            raise ApiError(ERR_NOT_GROUP_LEADER, 403,
                           "caller does not lead this event's group")
    was_registered = r["status"] == "REGISTERED"
    r["status"] = "CANCELLED"
    touch(r)
    if was_registered:
        # waitlist_promotion selector: lowest waitlist_position among
        # WAITLISTED rows flips to REGISTERED (position retained for audit).
        waiting = [x for x in STORE["rsvps"].values()
                   if x["event_id"] == r["event_id"] and x["status"] == "WAITLISTED"]
        if waiting:
            head = min(waiting, key=lambda x: (x["waitlist_position"], x["_seq"]))
            head["status"] = "REGISTERED"
            touch(head)
    return ok_object(rsvp_json(r))


@bp.post("/v1/rsvps/<rsvp_id>/check-in")
def check_in_rsvp(rsvp_id):
    user_id, role = authenticate(EVENT_MANAGERS)
    r = get_rsvp(rsvp_id)
    e = STORE["events"].get(r["event_id"])
    if e is None or e["status"] != "PUBLISHED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "check-in requires a PUBLISHED event")
    if r["status"] != "REGISTERED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "only a REGISTERED RSVP can be checked in")
    require_event_manager(user_id, role, e["group_id"])
    if clock_now() < e["starts_at"]:
        raise ApiError(ERR_CHECKIN_TOO_EARLY, 409, "event has not started yet")
    r["status"] = "CHECKED_IN"
    touch(r)
    return ok_object(rsvp_json(r))
