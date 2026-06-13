"""Press booking routes (PRD §3.5)."""

from datetime import datetime, timezone, timedelta

from flask import Blueprint, request

import db
import errors
from errors import err
from middleware import require_roles
from response import object_response, array_response
from services import serialize
from services.common import (
    get_body, require_fields, require_str, lookup, list_collection,
)

bp = Blueprint("press_bookings", __name__)


def _parse_dt(value, field):
    if not isinstance(value, str):
        raise err(errors.ERR_VALIDATION, "Field %s must be an ISO 8601 datetime" % field)
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err(errors.ERR_VALIDATION, "Field %s is not a valid ISO 8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@bp.post("/press-bookings")
@require_roles("ProductionOperator")
def create_press_booking():
    body = get_body()
    require_fields(body, "press_id", "order_line_id", "start_utc", "end_utc")
    press_id = require_str(body, "press_id")
    press = lookup(db.presses, press_id)
    order_line_id = require_str(body, "order_line_id")
    lookup(db.order_lines, order_line_id)

    start_dt = _parse_dt(body["start_utc"], "start_utc")
    end_dt = _parse_dt(body["end_utc"], "end_utc")
    buffer = timedelta(minutes=press["cleanup_buffer_minutes"])

    # Precedence per PRD §3.9 / scaffold: press overlap (12) before interval (13).
    # Overlap: an existing CONFIRMED booking B occupies [B.start, B.end + buffer);
    # new N = [N.start, N.end). Conflict iff N.start < B.end+buffer AND B.start < N.end.
    for b in db.press_bookings.values():
        if b["press_id"] != press_id or b["status"] != "CONFIRMED":
            continue
        b_start = _parse_dt(b["start_utc"], "start_utc")
        b_end = _parse_dt(b["end_utc"], "end_utc")
        occupied_end = b_end + buffer
        if start_dt < occupied_end and b_start < end_dt:
            raise err(errors.ERR_PRESS_DOUBLE_BOOKED,
                      "Press booking overlaps a confirmed booking")

    # Interval validity: end_utc strictly after start_utc.
    if not (end_dt > start_dt):
        raise err(errors.ERR_BOOKING_INTERVAL_INVALID,
                  "end_utc must be strictly after start_utc")

    rec = {
        "press_id": press_id,
        "order_line_id": order_line_id,
        "start_utc": body["start_utc"],
        "end_utc": body["end_utc"],
        "status": "CONFIRMED",
    }
    db.stamp_new(rec)
    db.press_bookings[rec["id"]] = rec
    return object_response(serialize.press_booking(rec), 201)


@bp.get("/press-bookings")
@require_roles("ShopStaff", "ProductionOperator", "Customer")
def list_press_bookings():
    press_id = request.args.get("press_id")
    order_line_id = request.args.get("order_line_id")

    def pred(r):
        if press_id is not None and r["press_id"] != press_id:
            return False
        if order_line_id is not None and r["order_line_id"] != order_line_id:
            return False
        return True

    items, limit, offset, total = list_collection(db.press_bookings, pred)
    return array_response([serialize.press_booking(r) for r in items], limit, offset, total)


@bp.get("/press-bookings/<press_booking_id>")
@require_roles("ShopStaff", "ProductionOperator", "Customer")
def read_press_booking(press_booking_id):
    rec = lookup(db.press_bookings, press_booking_id)
    return object_response(serialize.press_booking(rec), 200)


@bp.post("/press-bookings/<press_booking_id>/release")
@require_roles("ProductionOperator")
def release_press_booking(press_booking_id):
    rec = lookup(db.press_bookings, press_booking_id)
    if rec["status"] != "CONFIRMED":
        raise err(errors.ERR_INVALID_STATE, "Only a CONFIRMED booking may be released")
    rec["status"] = "RELEASED"
    db.touch(rec)
    return object_response(serialize.press_booking(rec), 200)
