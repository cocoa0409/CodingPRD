"""Enrollment (test-drive scoring) endpoints (PRD §3.3)."""
from flask import Blueprint, request

import calculations as calc
import clock
import db
from common import (
    find_or_404,
    get_body,
    new_record,
    pagination,
    paginate,
    require_int,
    require_str,
    serialize,
    touch,
)
from errors import ApiError
from middleware import auth_context, require_owner, require_role
from response import array_response, object_response

bp = Blueprint("enrollments", __name__)


@bp.post("/enrollments")
def create_enrollment():
    user_id, role = auth_context()
    require_role(role, ["DriverUser"])
    body = get_body()
    driver_id = require_str(body, "driver_id")
    rate_plan_id = require_str(body, "rate_plan_id")
    scoring_days = require_int(body, "scoring_days")
    if scoring_days < 1 or scoring_days > 90:
        raise ApiError("ERR_VALIDATION", "scoring_days must be between 1 and 90.")

    driver = find_or_404(db.drivers, driver_id)
    require_owner(role, user_id, driver["id"])
    find_or_404(db.rate_plans, rate_plan_id)

    started_at = clock.now()
    deadline = clock.add_days(started_at, scoring_days)
    rec = new_record(
        {
            "driver_id": driver_id,
            "rate_plan_id": rate_plan_id,
            "scoring_days": scoring_days,
            "scoring_started_at": clock.format_iso(started_at),
            "scoring_deadline": clock.format_iso(deadline),
            "captured_trip_count": 0,
            "provisional_risk_score": 0,
            "status": "SCORING",
        }
    )
    db.enrollments[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.get("/enrollments")
def list_enrollments():
    _, role = auth_context()
    require_role(role, ["DriverUser", "UnderwritingOps"])
    limit, offset = pagination()
    items = list(db.enrollments.values())
    for key in ("driver_id", "rate_plan_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [e for e in items if e[key] == val]
    data, total = paginate(items, limit, offset)
    return array_response(data, limit, offset, total)


@bp.get("/enrollments/<rid>")
def get_enrollment(rid):
    _, role = auth_context()
    require_role(role, ["DriverUser", "UnderwritingOps"])
    rec = find_or_404(db.enrollments, rid)
    return object_response(serialize(rec), 200)


def _accepted_enrollment_trips(enrollment_id):
    return [
        t
        for t in db.trips.values()
        if t.get("enrollment_id") == enrollment_id and t["status"] == "ACCEPTED"
    ]


@bp.post("/enrollments/<rid>/finalize-scoring")
def finalize_scoring(rid):
    user_id, role = auth_context()
    require_role(role, ["DriverUser"])
    enr = find_or_404(db.enrollments, rid)
    require_owner(role, user_id, enr["driver_id"])

    if enr["status"] != "SCORING":
        raise ApiError("ERR_ENROLLMENT_NOT_SCORING")
    if enr["captured_trip_count"] < calc.MIN_SCORING_TRIPS:
        raise ApiError("ERR_INSUFFICIENT_SCORING_TRIPS")
    if clock.now() > clock.parse_iso(enr["scoring_deadline"]):
        raise ApiError("ERR_SCORING_WINDOW_EXPIRED")

    plan = db.rate_plans[enr["rate_plan_id"]]
    trips = _accepted_enrollment_trips(enr["id"])
    enr["provisional_risk_score"] = calc.provisional_risk_score(trips, plan)
    enr["status"] = "READY_TO_QUOTE"
    touch(enr)
    return object_response(serialize(enr), 200)


@bp.post("/enrollments/<rid>/reopen-scoring")
def reopen_scoring(rid):
    user_id, role = auth_context()
    require_role(role, ["DriverUser"])
    enr = find_or_404(db.enrollments, rid)
    require_owner(role, user_id, enr["driver_id"])

    if enr["status"] != "READY_TO_QUOTE":
        raise ApiError("ERR_ENROLLMENT_NOT_READY")
    if clock.now() > clock.parse_iso(enr["scoring_deadline"]):
        raise ApiError("ERR_SCORING_WINDOW_EXPIRED")

    enr["status"] = "SCORING"  # provisional_risk_score left stale (PRD §3.3)
    touch(enr)
    return object_response(serialize(enr), 200)


@bp.post("/enrollments/<rid>/abandon")
def abandon_enrollment(rid):
    user_id, role = auth_context()
    require_role(role, ["DriverUser"])
    enr = find_or_404(db.enrollments, rid)
    require_owner(role, user_id, enr["driver_id"])

    if enr["status"] != "SCORING":
        raise ApiError("ERR_ENROLLMENT_NOT_SCORING")
    enr["status"] = "ABANDONED"
    touch(enr)
    return object_response(serialize(enr), 200)


@bp.post("/enrollments/<rid>/expire")
def expire_enrollment(rid):
    _, role = auth_context()
    require_role(role, ["UnderwritingOps"])
    enr = find_or_404(db.enrollments, rid)

    if enr["status"] != "SCORING":
        raise ApiError("ERR_ENROLLMENT_NOT_SCORING")
    if clock.now() <= clock.parse_iso(enr["scoring_deadline"]):
        raise ApiError("ERR_SCORING_WINDOW_NOT_EXPIRED")
    enr["status"] = "EXPIRED"
    touch(enr)
    return object_response(serialize(enr), 200)
