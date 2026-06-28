"""Violation record logging and review (confirm/dismiss with cascades)."""
from flask import Blueprint, request

from clock import clock
from db import db, make_versioned, touch
from errors import (
    err,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
)
from middleware import require_auth, require_role
from response import success, success_list
from serialize import violation_view
from util import require_body, require_str, require_int, require_enum, parse_pagination, paginate
from services import calculations as calc
from services import domain

bp = Blueprint("violations", __name__)

VIOLATION_KINDS = {"OVERSTAY", "UNAUTHORIZED_GATE", "NO_SHOW"}


@bp.post("/violations")
def create_violation():
    caller = require_auth()
    require_role(caller, "Host", "PlatformAdmin")
    data = require_body(request.get_json(silent=True))
    booking_id = require_str(data, "booking_id")

    booking = db.bookings.get(booking_id)
    if booking is None:
        raise err(ERR_NOT_FOUND, "Booking not found.")

    violation_kind = require_enum(data, "violation_kind", VIOLATION_KINDS)
    base_points = require_int(data, "base_points")
    if base_points < 1 or base_points > 10:
        raise err(ERR_INVALID_REQUEST, "base_points must be within 1..10.")

    rec = domain.create_violation(booking, violation_kind, base_points)
    return success(violation_view(rec), status=201)


@bp.get("/violations/<violation_id>")
def get_violation(violation_id):
    caller = require_auth()
    require_role(caller, "Host", "Driver", "PlatformAdmin")
    rec = db.violations.get(violation_id)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Violation not found.")
    return success(violation_view(rec))


@bp.get("/violations")
def list_violations():
    caller = require_auth()
    require_role(caller, "Host", "Driver", "PlatformAdmin")
    limit, offset = parse_pagination(request.args)
    driver_id = request.args.get("driver_id")
    booking_id = request.args.get("booking_id")
    status = request.args.get("status")
    items = list(db.violations.values())
    if driver_id is not None:
        items = [v for v in items if v["driver_id"] == driver_id]
    if booking_id is not None:
        items = [v for v in items if v["booking_id"] == booking_id]
    if status is not None:
        items = [v for v in items if v["status"] == status]
    items.sort(key=lambda v: v["_seq"])
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([violation_view(v) for v in page], limit, offset, total)


@bp.post("/violations/<violation_id>/confirm")
def confirm_violation(violation_id):
    caller = require_auth()
    require_role(caller, "PlatformAdmin")
    rec = db.violations.get(violation_id)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Violation not found.")
    if rec["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Violation is not OPEN.")

    driver = db.drivers[rec["driver_id"]]
    # prior_confirmed: driver's already-CONFIRMED records created before this one.
    prior_confirmed = 0
    for v in db.violations.values():
        if (v["driver_id"] == driver["id"] and v["status"] == "CONFIRMED"
                and v["_seq"] < rec["_seq"]):
            prior_confirmed += 1

    assessed = calc.confirmed_violation_points(
        rec["violation_kind"], rec["base_points"], prior_confirmed
    )
    rec["status"] = "CONFIRMED"
    rec["assessed_points"] = assessed

    # Cascade: add assessed to driver.violation_points; recompute standing_tier.
    driver["violation_points"] += assessed
    new_tier = calc.driver_standing_tier(driver["violation_points"])
    driver["standing_tier"] = new_tier
    # Re-derive provisional points (this OPEN record dropped out of the open set).
    domain.recompute_provisional_points(driver)

    # Suspension cascade: auto-cancel RESERVED bookings with tiered refund.
    if new_tier == "SUSPENDED":
        domain.apply_suspension_cascade(driver, clock.now())

    touch(driver)
    touch(rec)
    return success(violation_view(rec))


@bp.post("/violations/<violation_id>/dismiss")
def dismiss_violation(violation_id):
    caller = require_auth()
    require_role(caller, "PlatformAdmin")
    rec = db.violations.get(violation_id)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Violation not found.")
    if rec["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Violation is not OPEN.")

    rec["status"] = "DISMISSED"
    rec["assessed_points"] = 0
    driver = db.drivers[rec["driver_id"]]
    # violation_points unchanged; re-derive provisional (this OPEN record drops out).
    domain.recompute_provisional_points(driver)
    touch(driver)
    touch(rec)
    return success(violation_view(rec))
