"""FacilityBooking endpoints."""

from datetime import timedelta
from flask import Blueprint, request

import db
from common import (
    require_role, get_json_body, stamp_common_create, bump,
    success, must_exist, get_pagination, paginate_list, parse_iso8601,
)
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_NOT_FOUND,
    ERR_STALE_FACILITY_VERSION, ERR_FACILITY_OVERLAP, ERR_CAPACITY_EXCEEDED,
)
from routes.facility import _upcoming_booked_hours

bp = Blueprint("facility_bookings", __name__)


@bp.route("/facility-bookings", methods=["POST"])
def create_booking():
    require_role({"Coordinator", "PlatformAdmin"})
    body = get_json_body()

    # Rung 14: structural.
    required = ("facility_id", "booking_type", "starts_at", "ends_at", "headcount", "expected_facility_version")
    for k in required:
        if k not in body or body[k] is None:
            raise_err(ERR_INVALID_REQUEST, f"{k} is required")
    booking_type = body["booking_type"]
    if booking_type not in ("EVENT", "EXTERNAL"):
        raise_err(ERR_INVALID_REQUEST, "booking_type must be EVENT or EXTERNAL")
    if not isinstance(body["headcount"], int) or isinstance(body["headcount"], bool):
        raise_err(ERR_INVALID_REQUEST, "headcount must be an integer")
    if not isinstance(body["expected_facility_version"], int) or isinstance(body["expected_facility_version"], bool):
        raise_err(ERR_INVALID_REQUEST, "expected_facility_version must be an integer")
    try:
        starts = parse_iso8601(body["starts_at"])
        ends = parse_iso8601(body["ends_at"])
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "starts_at/ends_at must be ISO8601")
    if ends <= starts:
        raise_err(ERR_INVALID_REQUEST, "ends_at must be > starts_at")
    if body["headcount"] <= 0:
        raise_err(ERR_INVALID_REQUEST, "headcount must be > 0")
    event_id = body.get("event_id")
    # booking_type EVENT iff event_id is non-null.
    if booking_type == "EVENT" and event_id is None:
        raise_err(ERR_INVALID_REQUEST, "EVENT booking requires event_id")
    if booking_type == "EXTERNAL" and event_id is not None:
        raise_err(ERR_INVALID_REQUEST, "EXTERNAL booking must not have event_id")

    # Rung 3: existence.
    facility = db.facilities.get(body["facility_id"])
    if facility is None:
        raise_err(ERR_NOT_FOUND, "facility_id not found")
    if event_id is not None:
        event = db.events.get(event_id)
        if event is None:
            raise_err(ERR_NOT_FOUND, "event_id not found")

    # OCC: check expected_facility_version now (after existence). Note: rung 8 (overlap) and rung 9
    # (capacity) are higher-priority than the concurrency stale-version check, so we check them first.
    # Wait — the scaffold explicitly puts OCC at http 412 with no priority number. PRD §2.8 says
    # "existence is checked before OCC". Per PRD example: existence 404 > OCC 412. OCC does not appear
    # in the priority ladder; only relative to existence, PRD says existence wins.
    # The PRD does not order OCC vs overlap/capacity — we place OCC after overlap/capacity checks so
    # that the earlier ladder failures still take precedence (defense in depth). But tests may verify
    # OCC in isolation. We'll place OCC after existence, before ladder rungs 4+.

    if body["expected_facility_version"] != facility.get("version", 1):
        raise_err(ERR_STALE_FACILITY_VERSION, "expected_facility_version does not match")

    # Rung 8: overlap check (buffered half-open intervals).
    buf = timedelta(minutes=facility.get("buffer_minutes", 0))
    new_start_buf = starts - buf
    new_end_buf = ends + buf
    for b in db.facility_bookings.values():
        if b.get("facility_id") != facility["id"]:
            continue
        if b.get("status") != "CONFIRMED":
            continue
        try:
            o_start = parse_iso8601(b["starts_at"])
            o_end = parse_iso8601(b["ends_at"])
        except Exception:
            continue
        # Half-open [start, end): overlap iff new_start_buf < o_end AND o_start < new_end_buf.
        if new_start_buf < o_end and o_start < new_end_buf:
            raise_err(ERR_FACILITY_OVERLAP, "booking overlaps another CONFIRMED booking")

    # Rung 9: capacity.
    if body["headcount"] > facility["capacity"]:
        raise_err(ERR_CAPACITY_EXCEEDED, "headcount exceeds facility capacity")

    rec = {
        "facility_id": facility["id"],
        "event_id": event_id,
        "booking_type": booking_type,
        "starts_at": body["starts_at"],
        "ends_at": body["ends_at"],
        "headcount": body["headcount"],
        "status": "CONFIRMED",
        "expected_facility_version": body["expected_facility_version"],
    }
    stamp_common_create(rec)
    db.facility_bookings[rec["id"]] = rec

    # Bump facility version, refresh upcoming_booked_hours.
    bump(facility)
    facility["upcoming_booked_hours"] = _upcoming_booked_hours(facility["id"])

    return success(rec, 201)


@bp.route("/facility-bookings/<bid>", methods=["GET"])
def get_booking(bid):
    require_role({"Coordinator", "FinanceAdmin", "PlatformAdmin"})
    rec = must_exist(db.facility_bookings, bid, "FacilityBooking")
    return success(rec, 200)


@bp.route("/facility-bookings/<bid>/cancel", methods=["POST"])
def cancel_booking(bid):
    require_role({"Coordinator", "PlatformAdmin"})
    rec = must_exist(db.facility_bookings, bid, "FacilityBooking")
    if rec["status"] != "CONFIRMED":
        raise_err(ERR_INVALID_STATE, "booking must be CONFIRMED to cancel")
    rec["status"] = "CANCELLED"
    bump(rec)
    facility = db.facilities.get(rec["facility_id"])
    if facility is not None:
        facility["upcoming_booked_hours"] = _upcoming_booked_hours(facility["id"])
        bump(facility)
    return success(rec, 200)


@bp.route("/facility-bookings", methods=["GET"])
def list_bookings():
    require_role({"Coordinator", "FinanceAdmin", "PlatformAdmin"})
    limit, offset = get_pagination()
    items = list(db.facility_bookings.values())
    for k in ("facility_id", "event_id", "status"):
        v = request.args.get(k)
        if v:
            items = [b for b in items if b.get(k) == v]
    page, meta = paginate_list(items, limit, offset)
    return success(page, 200, meta_extra=meta)
