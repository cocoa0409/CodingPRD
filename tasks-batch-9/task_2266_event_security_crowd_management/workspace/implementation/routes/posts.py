"""Post endpoints (PRD 3.4)."""

from flask import Blueprint

import engine
import serial
import valid
from auth import authenticate
from db import db, make_record, parse_iso, touch
from errors import ApiError
from response import object_response
from routes._common import get_plan, get_post, match_filters, paginated

bp = Blueprint("posts", __name__)

POST_TYPES = ("PERIMETER", "INGRESS_SCREENING", "FLOOR", "EMERGENCY_EXIT", "SUPERVISOR")
POST_STATUSES = ("OPEN", "PARTIALLY_STAFFED", "FILLED", "UNDERSTAFFED", "CLOSED")
READ_ROLES = {"SecurityDirector", "StaffingCoordinator", "IncidentCommander", "PostSupervisor"}
SPAN_OF_CONTROL_LIMIT = 10


def _check_span_of_control(plan_id, supervisor_post_id, required_guard_count, exclude_post_id=None):
    if not supervisor_post_id:
        return
    total = required_guard_count
    for post in db.posts.values():
        if post.get("id") == exclude_post_id:
            continue
        if (
            post.get("staffing_plan_id") == plan_id
            and post.get("reports_to_post_id") == supervisor_post_id
        ):
            total += post.get("required_guard_count") or 0
    if total > SPAN_OF_CONTROL_LIMIT:
        raise ApiError("ERR_SPAN_OF_CONTROL_EXCEEDED")


def _check_zone_slots(zone, window_start, window_end, required_guard_count, exclude_post_id=None):
    """Closed-interval aggregate occupancy check (PRD 3.4)."""
    existing = []
    for post in db.posts.values():
        if post.get("zone_id") != zone["id"]:
            continue
        if post.get("id") == exclude_post_id:
            continue
        if post.get("status") == "CLOSED":
            continue
        plan = db.plans.get(post.get("staffing_plan_id"))
        if plan is None or plan.get("status") == "SUPERSEDED":
            continue
        existing.append(post)
    candidate = {
        "window_start": window_start,
        "window_end": window_end,
        "required_guard_count": required_guard_count,
    }
    windows = []
    for post in existing:
        windows.append(
            (
                parse_iso(post["window_start"]),
                parse_iso(post["window_end"]),
                post.get("required_guard_count") or 0,
            )
        )
    windows.append((window_start, window_end, required_guard_count))
    instants = set()
    for start, end, _ in windows:
        instants.add(start)
        instants.add(end)
    capacity = zone.get("post_slot_capacity") or 0
    for instant in instants:
        total = 0
        for start, end, count in windows:
            if start <= instant <= end:
                total += count
        if total > capacity:
            raise ApiError("ERR_ZONE_POST_CAPACITY_EXCEEDED")
    return candidate


@bp.post("/staffing-plans/<plan_id>/posts")
def create_post(plan_id):
    authenticate({"StaffingCoordinator"})
    payload = valid.body()
    zone_id = valid.req_string(payload, "zone_id")
    post_code = valid.req_string(payload, "post_code")
    post_type = valid.req_enum(payload, "post_type", POST_TYPES)
    required_guard_count = valid.req_int(payload, "required_guard_count", minimum=1)
    min_credential_level = valid.req_int(payload, "min_credential_level", minimum=1, maximum=4)
    window_start = valid.req_datetime(payload, "window_start")
    window_end = valid.req_datetime(payload, "window_end")
    if window_end[1] <= window_start[1]:
        valid.bad("Field 'window_end' must be strictly after 'window_start'.")
    reports_to_post_id = valid.opt_string(payload, "reports_to_post_id")
    lane_id = valid.opt_string(payload, "lane_id")

    plan = get_plan(plan_id)
    event = db.events.get(plan.get("event_id"))

    zone = db.zones.get(zone_id)
    if zone is None:
        raise ApiError("ERR_ZONE_NOT_FOUND")
    lane = None
    if lane_id is not None:
        lane = db.lanes.get(lane_id)
        if lane is None:
            raise ApiError("ERR_LANE_NOT_FOUND")
    supervisor_post = None
    if reports_to_post_id is not None:
        supervisor_post = db.posts.get(reports_to_post_id)
        if supervisor_post is None:
            raise ApiError("ERR_POST_NOT_FOUND")

    if event is None or zone.get("venue_id") != event.get("venue_id"):
        raise ApiError(
            "ERR_ZONE_VENUE_MISMATCH", "The referenced zone does not belong to the event's venue."
        )
    if lane is not None and lane.get("event_id") != plan.get("event_id"):
        raise ApiError(
            "ERR_ZONE_VENUE_MISMATCH", "The referenced lane belongs to a different event."
        )
    if supervisor_post is not None and (
        supervisor_post.get("staffing_plan_id") != plan["id"]
        or supervisor_post.get("post_type") != "SUPERVISOR"
    ):
        raise ApiError(
            "ERR_ZONE_VENUE_MISMATCH",
            "reports_to_post_id must name a SUPERVISOR post in the same plan.",
        )

    for existing in db.posts.values():
        if (
            existing.get("staffing_plan_id") == plan["id"]
            and existing.get("post_code") == post_code
        ):
            raise ApiError(
                "ERR_INVALID_REQUEST", "Field 'post_code' must be unique within the plan."
            )

    if plan.get("status") == "LOCKED":
        raise ApiError("ERR_PLAN_LOCKED")
    if not plan.get("is_current"):
        raise ApiError("ERR_PLAN_NOT_CURRENT")
    if event.get("gate_posture") == "FROZEN":
        raise ApiError("ERR_EVENT_GATE_FROZEN")

    _check_span_of_control(plan["id"], reports_to_post_id, required_guard_count)
    _check_zone_slots(zone, window_start[1], window_end[1], required_guard_count)

    record = make_record(
        {
            "staffing_plan_id": plan["id"],
            "zone_id": zone["id"],
            "reports_to_post_id": reports_to_post_id,
            "lane_id": lane_id,
            "post_code": post_code,
            "post_type": post_type,
            "required_guard_count": required_guard_count,
            "min_credential_level": min_credential_level,
            "window_start": window_start[0],
            "window_end": window_end[0],
            "filled_guard_count": 0,
            "status": "OPEN",
        }
    )
    db.posts[record["id"]] = record
    engine.recompute_post(record, plan)
    if engine.recompute_plan(plan):
        touch(plan)
    engine.cascade_event_only(event)
    return object_response(serial.post(record), 201)


@bp.get("/posts/<post_id>")
def read_post(post_id):
    authenticate(READ_ROLES)
    post = get_post(post_id)
    return object_response(serial.post(post))


@bp.get("/posts")
def list_posts():
    authenticate(READ_ROLES)
    filters = {
        "staffing_plan_id": valid.query_string("staffing_plan_id"),
        "zone_id": valid.query_string("zone_id"),
        "reports_to_post_id": valid.query_string("reports_to_post_id"),
        "lane_id": valid.query_string("lane_id"),
        "post_type": valid.query_enum("post_type", POST_TYPES),
        "status": valid.query_enum("status", POST_STATUSES),
    }
    records = [p for p in db.posts.values() if match_filters(p, filters)]
    return paginated(records, serial.post)


@bp.patch("/posts/<post_id>")
def patch_post(post_id):
    authenticate({"StaffingCoordinator"})
    payload = valid.body()
    expected_version = valid.req_int(payload, "expected_post_version")
    required_guard_count = valid.opt_int(payload, "required_guard_count", minimum=1)
    min_credential_level = valid.opt_int(payload, "min_credential_level", minimum=1, maximum=4)
    window_start = valid.opt_datetime(payload, "window_start")
    window_end = valid.opt_datetime(payload, "window_end")

    post = get_post(post_id)
    plan = db.plans.get(post.get("staffing_plan_id"))
    event = db.events.get(plan.get("event_id")) if plan else None

    new_start_raw = window_start[0] if window_start else post["window_start"]
    new_end_raw = window_end[0] if window_end else post["window_end"]
    new_start = parse_iso(new_start_raw)
    new_end = parse_iso(new_end_raw)
    if new_end <= new_start:
        valid.bad("Field 'window_end' must be strictly after 'window_start'.")

    if expected_version != post.get("version"):
        raise ApiError("ERR_STALE_POST_VERSION")
    if plan is not None and plan.get("status") == "LOCKED":
        raise ApiError("ERR_PLAN_LOCKED")
    if plan is not None and not plan.get("is_current"):
        raise ApiError("ERR_PLAN_NOT_CURRENT")
    if event is not None and event.get("gate_posture") == "FROZEN":
        raise ApiError("ERR_EVENT_GATE_FROZEN")

    new_count = (
        required_guard_count
        if required_guard_count is not None
        else post.get("required_guard_count")
    )
    _check_span_of_control(
        post.get("staffing_plan_id"),
        post.get("reports_to_post_id"),
        new_count,
        exclude_post_id=post["id"],
    )
    zone = db.zones.get(post.get("zone_id"))
    if zone is not None:
        _check_zone_slots(zone, new_start, new_end, new_count, exclude_post_id=post["id"])

    post["required_guard_count"] = new_count
    if min_credential_level is not None:
        post["min_credential_level"] = min_credential_level
    post["window_start"] = new_start_raw
    post["window_end"] = new_end_raw
    engine.recompute_post(post, plan)
    touch(post)
    if plan is not None and engine.recompute_plan(plan):
        touch(plan)
    engine.cascade_event_only(event)
    return object_response(serial.post(post))
