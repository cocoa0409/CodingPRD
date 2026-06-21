"""SurgicalDay routes and posture state machine (PRD §3.3)."""
from flask import Blueprint

from db import db, stamp_common, touch
from errors import err
from middleware import get_user_context, require_role
from response import success, list_response
from services.helpers import (
    lookup, get_body, require_str, paginate, sorted_by_created, ser_default,
)
from services.calculations import recompute_day

bp = Blueprint("days", __name__)

ALL_ROLES = {"Scheduler", "PreOpNurse", "ORManager", "BillingAnalyst"}

ACTIVE_CASE_STATES = {"IN_OR", "IN_RECOVERY", "COMPLETED"}


def _day_cases(day_id):
    return [c for c in db.surgical_cases.values() if c["surgical_day_id"] == day_id]


def _noncancelled(cases):
    return [c for c in cases if c["case_status"] != "CANCELLED"]


@bp.route("/asc/surgical-days", methods=["POST"])
def create_day():
    _, role = get_user_context()
    require_role(role, {"Scheduler"})
    body = get_body()
    facility_id = require_str(body, "facility_id")
    lookup("facilities", facility_id)
    service_date = require_str(body, "service_date")
    # facility-scoped uniqueness on service_date
    for d in db.surgical_days.values():
        if d["facility_id"] == facility_id and d["service_date"] == service_date:
            raise err("ERR_DUPLICATE_KEY", "service_date already exists in this facility.")

    rec = stamp_common({
        "facility_id": facility_id,
        "service_date": service_date,
        "posture": "OPEN",
        "booked_minutes": 0,
        "utilization_pct": 0.0,
    })
    db.surgical_days[rec["id"]] = rec
    return success(ser_default(rec), status=201)


@bp.route("/asc/surgical-days", methods=["GET"])
def list_days():
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    items = list(db.surgical_days.values())
    fid = _arg("facility_id")
    if fid is not None:
        items = [r for r in items if r["facility_id"] == fid]
    items = sorted_by_created(items)
    page, limit, offset, total = paginate(items)
    return list_response([ser_default(r) for r in page], limit, offset, total)


@bp.route("/asc/surgical-days/<day_id>", methods=["GET"])
def get_day(day_id):
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    return success(ser_default(lookup("surgical_days", day_id)))


@bp.route("/asc/surgical-days/<day_id>/lock", methods=["POST"])
def lock_day(day_id):
    _, role = get_user_context()
    require_role(role, {"Scheduler"})
    day = lookup("surgical_days", day_id)
    if day["posture"] != "OPEN":
        raise err("ERR_DAY_NOT_OPEN", "Day must be OPEN to lock.")
    if not _noncancelled(_day_cases(day_id)):
        raise err("ERR_DAY_EMPTY", "Cannot lock a day with no non-cancelled cases.")
    day["posture"] = "LOCKED"
    touch(day)
    return success(ser_default(day))


@bp.route("/asc/surgical-days/<day_id>/reopen", methods=["POST"])
def reopen_day(day_id):
    _, role = get_user_context()
    require_role(role, {"Scheduler"})
    day = lookup("surgical_days", day_id)
    if day["posture"] != "LOCKED":
        raise err("ERR_DAY_NOT_LOCKED", "Day must be LOCKED to reopen.")
    if any(c["case_status"] in ACTIVE_CASE_STATES for c in _day_cases(day_id)):
        raise err("ERR_DAY_HAS_ACTIVE_CASES",
                  "Cannot reopen a day with a case IN_OR/IN_RECOVERY/COMPLETED.")
    day["posture"] = "OPEN"
    touch(day)
    return success(ser_default(day))


@bp.route("/asc/surgical-days/<day_id>/close", methods=["POST"])
def close_day(day_id):
    _, role = get_user_context()
    require_role(role, {"ORManager"})
    day = lookup("surgical_days", day_id)
    if day["posture"] != "LOCKED":
        raise err("ERR_DAY_NOT_LOCKED", "Day must be LOCKED to close.")
    for c in _noncancelled(_day_cases(day_id)):
        if c["case_status"] != "COMPLETED":
            raise err("ERR_DAY_HAS_UNFINISHED_CASES",
                      "Every non-cancelled case must be COMPLETED to close.")
    # Recompute one final time before freezing, then set CLOSED (freezes util).
    recompute_day(day)
    day["posture"] = "CLOSED"
    touch(day)
    return success(ser_default(day))


def _arg(name):
    from flask import request
    return request.args.get(name)
