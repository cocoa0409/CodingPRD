"""Trip + TripEvent endpoints (PRD §3.5)."""
from flask import Blueprint, request

import calculations as calc
import clock
import db
from common import (
    find_or_404,
    get_body,
    new_record,
    optional_str,
    pagination,
    paginate,
    require_int,
    require_number,
    require_str,
    serialize,
    touch,
)
from errors import ApiError
from middleware import auth_context, require_owner, require_role
from response import array_response, object_response
from services import trip_service

bp = Blueprint("trips", __name__)

ALL_ROLES = ["DriverUser", "UnderwritingOps", "ClaimsAdjuster"]
EVENT_TYPES = ("HARD_BRAKE", "SPEEDING", "PHONE_USE", "CRASH")
EVENT_COUNT_FIELD = {
    "HARD_BRAKE": "hard_brake_count",
    "SPEEDING": "speeding_count",
    "PHONE_USE": "phone_use_count",
}


def _driver_for_trip(trip):
    if trip.get("policy_id"):
        return db.policies[trip["policy_id"]]["driver_id"]
    if trip.get("enrollment_id"):
        return db.enrollments[trip["enrollment_id"]]["driver_id"]
    return None


# ---------------------------------------------------------------------------
# Create trip
# ---------------------------------------------------------------------------
@bp.post("/trips")
def create_trip():
    user_id, role = auth_context()
    require_role(role, ["DriverUser"])
    body = get_body()

    policy_id = body.get("policy_id")
    enrollment_id = body.get("enrollment_id")
    # Exactly one parent (PRD §3.5).
    if policy_id is not None and not isinstance(policy_id, str):
        raise ApiError("ERR_VALIDATION", "policy_id must be a string.")
    if enrollment_id is not None and not isinstance(enrollment_id, str):
        raise ApiError("ERR_VALIDATION", "enrollment_id must be a string.")

    started_at = require_str(body, "started_at")
    ended_at = require_str(body, "ended_at")
    distance_miles = require_number(body, "distance_miles")

    try:
        started_dt = clock.parse_iso(started_at)
        ended_dt = clock.parse_iso(ended_at)
    except ValueError:
        raise ApiError("ERR_VALIDATION", "started_at/ended_at must be ISO 8601 instants.")

    has_policy = bool(policy_id)
    has_enrollment = bool(enrollment_id)
    if has_policy == has_enrollment:
        # both set or neither set
        raise ApiError("ERR_TRIP_PARENT_AMBIGUOUS")

    # Resolve the parent so ownership can be checked (existence is part of the
    # chain; a non-existent parent id is ERR_NOT_FOUND).
    if has_policy:
        parent = find_or_404(db.policies, policy_id)
        driver_id = parent["driver_id"]
    else:
        parent = find_or_404(db.enrollments, enrollment_id)
        driver_id = parent["driver_id"]
    require_owner(role, user_id, driver_id)

    # ended_at strictly after started_at (PRD §3.5).
    if ended_dt <= started_dt:
        raise ApiError("ERR_TRIP_TIME_ORDER")
    # distance_miles > 0 (PRD §3.5).
    if distance_miles <= 0:
        raise ApiError("ERR_INVALID_TRIP_DISTANCE")

    rec = new_record(
        {
            "policy_id": policy_id if has_policy else None,
            "enrollment_id": enrollment_id if has_enrollment else None,
            "started_at": clock.format_iso(started_dt),
            "ended_at": clock.format_iso(ended_dt),
            "distance_miles": distance_miles,
            "hard_brake_count": 0,
            "speeding_count": 0,
            "phone_use_count": 0,
            "crash_detected": False,
            "billed_period_index": -1,
            "status": "OPEN",
        }
    )
    db.trips[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.get("/trips")
def list_trips():
    _, role = auth_context()
    require_role(role, ["DriverUser", "UnderwritingOps"])
    limit, offset = pagination()
    items = list(db.trips.values())
    for key in ("policy_id", "enrollment_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [t for t in items if t.get(key) == val]
    data, total = paginate(items, limit, offset)
    return array_response(data, limit, offset, total)


@bp.get("/trips/<rid>")
def get_trip(rid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    rec = find_or_404(db.trips, rid)
    return object_response(serialize(rec), 200)


# ---------------------------------------------------------------------------
# Trip events
# ---------------------------------------------------------------------------
@bp.post("/trips/<rid>/events")
def create_event(rid):
    user_id, role = auth_context()
    require_role(role, ["DriverUser"])
    trip = find_or_404(db.trips, rid)
    require_owner(role, user_id, _driver_for_trip(trip))

    body = get_body()
    event_type = require_str(body, "event_type")
    severity = require_int(body, "severity")
    occurred_at = require_str(body, "occurred_at")

    if event_type not in EVENT_TYPES or severity < 1 or severity > 5:
        raise ApiError("ERR_INVALID_EVENT")
    try:
        occurred_dt = clock.parse_iso(occurred_at)
    except ValueError:
        raise ApiError("ERR_VALIDATION", "occurred_at must be an ISO 8601 instant.")

    # Half-open interval [started_at, ended_at) (PRD §3.5).
    started_dt = clock.parse_iso(trip["started_at"])
    ended_dt = clock.parse_iso(trip["ended_at"])
    if occurred_dt < started_dt or occurred_dt >= ended_dt:
        raise ApiError("ERR_EVENT_OUTSIDE_TRIP")

    rec = new_record(
        {
            "trip_id": trip["id"],
            "event_type": event_type,
            "severity": severity,
            "occurred_at": clock.format_iso(occurred_dt),
        },
        common=False,
    )
    db.trip_events[rec["id"]] = rec

    # Increment the per-type counter (PRD §3.5).
    if event_type in EVENT_COUNT_FIELD:
        trip[EVENT_COUNT_FIELD[event_type]] += 1
        touch(trip)
    elif event_type == "CRASH":
        # A CRASH with severity >= threshold arms FNOL (PRD §3.5).
        if severity >= calc.CRASH_FNOL_SEVERITY:
            trip["crash_detected"] = True
            trip["_crash_severity"] = severity
            touch(trip)

    return object_response(serialize(rec), 201)


@bp.get("/trips/<rid>/events")
def list_events(rid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    trip = find_or_404(db.trips, rid)
    limit, offset = pagination()
    items = [e for e in db.trip_events.values() if e["trip_id"] == trip["id"]]
    data, total = paginate(items, limit, offset)
    return array_response(data, limit, offset, total)


# ---------------------------------------------------------------------------
# Accept / reject / void
# ---------------------------------------------------------------------------
@bp.post("/trips/<rid>/accept")
def accept_trip(rid):
    user_id, role = auth_context()
    require_role(role, ["DriverUser"])
    trip = find_or_404(db.trips, rid)
    require_owner(role, user_id, _driver_for_trip(trip))

    if trip["status"] != "OPEN":
        raise ApiError("ERR_TRIP_NOT_OPEN")

    if trip.get("policy_id"):
        policy = db.policies[trip["policy_id"]]
        if policy["telematics_status"] == "SUSPENDED":
            raise ApiError("ERR_TELEMATICS_SUSPENDED")
        if policy["billing_status"] != "PERIOD_OPEN":
            raise ApiError("ERR_PERIOD_NOT_OPEN")
    else:
        enr = db.enrollments[trip["enrollment_id"]]
        if enr["status"] != "SCORING" or clock.now() > clock.parse_iso(
            enr["scoring_deadline"]
        ):
            raise ApiError("ERR_SCORING_WINDOW_EXPIRED")

    if trip["distance_miles"] <= 0:
        raise ApiError("ERR_INVALID_TRIP_DISTANCE")

    trip_service.accept_cascade(trip)
    return object_response(serialize(trip), 200)


@bp.post("/trips/<rid>/reject")
def reject_trip(rid):
    user_id, role = auth_context()
    require_role(role, ["DriverUser"])
    trip = find_or_404(db.trips, rid)
    require_owner(role, user_id, _driver_for_trip(trip))
    if trip["status"] != "OPEN":
        raise ApiError("ERR_TRIP_NOT_OPEN")
    trip["status"] = "REJECTED"
    touch(trip)
    return object_response(serialize(trip), 200)


@bp.post("/trips/<rid>/void")
def void_trip(rid):
    _, role = auth_context()
    require_role(role, ["UnderwritingOps"])
    trip = find_or_404(db.trips, rid)
    if trip["status"] != "ACCEPTED":
        raise ApiError("ERR_TRIP_NOT_ACCEPTED")

    # No SETTLED statement may cover this trip's period (PRD §3.5).
    if trip.get("policy_id") and trip["billed_period_index"] >= 0:
        for s in db.statements.values():
            if (
                s["policy_id"] == trip["policy_id"]
                and s["period_index"] == trip["billed_period_index"]
                and s["status"] == "SETTLED"
            ):
                raise ApiError("ERR_TRIP_PERIOD_SETTLED")

    trip_service.void_cascade(trip)
    return object_response(serialize(trip), 200)
