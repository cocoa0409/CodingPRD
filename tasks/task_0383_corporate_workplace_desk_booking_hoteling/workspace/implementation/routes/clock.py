"""Logical-clock routes (PRD §2.7 / §3.8). FacilityManager-only."""
from __future__ import annotations

from flask import Blueprint

import db
from errors import APIError, ERR_INVALID_REQUEST
from middleware import require_role
from response import ok_object
from routes._helpers import get_body, order_by_created
from services import state_machines as sm

bp = Blueprint("clock", __name__)


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_iso_date(v):
    if not isinstance(v, str) or len(v) != 10 or v[4] != "-" or v[7] != "-":
        return False
    y, m, d = v[:4], v[5:7], v[8:10]
    if not (y.isdigit() and m.isdigit() and d.isdigit()):
        return False
    return 1 <= int(m) <= 12 and 1 <= int(d) <= 31


@bp.post("/workplace/_clock/set")
def set_clock():
    require_role("FacilityManager")
    body = get_body()
    current_date = body.get("current_date")
    current_minute = body.get("current_minute")
    if not _is_iso_date(current_date):
        raise APIError(ERR_INVALID_REQUEST, 422, "current_date must be YYYY-MM-DD")
    if not _is_int(current_minute):
        raise APIError(ERR_INVALID_REQUEST, 422, "current_minute must be an integer")
    db.clock["current_date"] = current_date
    db.clock["current_minute"] = current_minute
    return ok_object({"current_date": current_date, "current_minute": current_minute})


@bp.post("/workplace/_clock/advance-no-show-sweep")
def no_show_sweep():
    require_role("FacilityManager")
    body = get_body()
    target_date = body.get("booking_date")
    if target_date is not None and not _is_iso_date(target_date):
        raise APIError(ERR_INVALID_REQUEST, 422, "booking_date must be YYYY-MM-DD")

    cm = db.clock.get("current_minute")
    if cm is None:
        raise APIError(ERR_INVALID_REQUEST, 422, "Logical clock not set")

    # Collect grace-expired BOOKED reservations first (stable order), then release.
    candidates = [
        r for r in db.reservations.values()
        if r["occupancy_status"] == "BOOKED"
        and cm > r["checkin_deadline_minute"]
        and (target_date is None or r["booking_date"] == target_date)
    ]
    candidates = order_by_created(candidates)

    released_ids = []
    for r in candidates:
        employee = db.employees.get(r["employee_id"])
        if employee is None:
            continue
        sm.reservation_release(r, employee)
        released_ids.append(r["id"])

    return ok_object({
        "released_count": len(released_ids),
        "released_reservation_ids": released_ids,
    })
