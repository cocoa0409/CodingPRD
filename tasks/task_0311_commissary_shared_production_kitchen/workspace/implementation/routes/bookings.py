"""Station booking lifecycle: create (priced), cancel (refund), complete."""
from datetime import timedelta

from flask import Blueprint, request

from db import db, LOCK
from errors import ApiError
from middleware import (
    get_identity, require_roles, require_owner, get_json_body, parse_pagination,
)
from response import success, paginated
from services.common import (
    stamp_new, touch, public, find_member, get_or_404, sorted_by_creation,
    paginate, require_fields, parse_dt,
)
from services.calculations import booking_fee

bp = Blueprint("bookings", __name__)


def _public(b):
    return public(b)


def _is_peak(start_dt):
    """PRD 3.2: a booking is peak when its start_utc local hour falls in the peak
    window that runs from 06:00 inclusive up to 10:00 exclusive."""
    hour = start_dt.hour
    return 6 <= hour < 10


def _separation_minutes(a_start, a_end, b_start, b_end):
    """Clear minutes of space between the two half-open intervals.

    0 when they abut exactly (one starts the instant the other ends),
    positive when there is clear time between them, and negative when their
    occupied times overlap.
    """
    if a_start >= b_end:
        return (a_start - b_end).total_seconds() / 60.0
    if b_start >= a_end:
        return (b_start - a_end).total_seconds() / 60.0
    # Occupied-time overlap.
    return -1.0


@bp.post("/members/<member_id>/bookings")
def create_booking(member_id):
    user_id, role = get_identity()
    require_roles(role, {"MemberOperator"})
    require_owner(role, user_id, member_id)
    body = get_json_body()
    with LOCK:
        member = find_member(member_id)
        # FK existence (station) before body well-formedness checks on values.
        require_fields(body, ["station_id", "start_utc", "end_utc", "expected_member_version"])
        station = get_or_404(db.stations, body["station_id"])

        start_dt = parse_dt(body["start_utc"])
        end_dt = parse_dt(body["end_utc"])
        if start_dt is None or end_dt is None:
            raise ApiError("ERR_INVALID_REQUEST")

        # OCC (priority 7).
        if body["expected_member_version"] != member["version"]:
            raise ApiError("ERR_STALE_VERSION")

        # Member active (priority 9).
        if member["status"] != "ACTIVE":
            raise ApiError("ERR_MEMBER_NOT_ACTIVE")

        # Interval validity (priority 12).
        if not (end_dt > start_dt):
            raise ApiError("ERR_INVALID_INTERVAL")

        # Peak-tier gating (priority 13).
        is_peak = _is_peak(start_dt)
        if is_peak and member["plan_tier"] != "PREMIUM":
            raise ApiError("ERR_PEAK_REQUIRES_PREMIUM")

        buffer_minutes = station["turnover_buffer_minutes"]
        turnover_applied = False
        for other in db.bookings.values():
            if other["station_id"] != station["id"]:
                continue
            if other["status"] not in ("CONFIRMED", "COMPLETED"):
                continue
            o_start = parse_dt(other["start_utc"])
            o_end = parse_dt(other["end_utc"])
            sep = _separation_minutes(start_dt, end_dt, o_start, o_end)
            # Occupied-time overlap, or sitting strictly inside the cleaning
            # buffer (clear space less than the buffer but not an exact abutment)
            # is an overlap (priority 14). An exact abutment (sep == 0) is
            # allowed but forces the cleaning buffer into play.
            if sep < 0 or (0 < sep < buffer_minutes):
                raise ApiError("ERR_BOOKING_OVERLAP")
            if sep == 0:
                turnover_applied = True

        # Station availability (priority 15).
        if station["status"] != "OPEN":
            raise ApiError("ERR_STATION_OUT_OF_SERVICE")

        duration_minutes = (end_dt - start_dt).total_seconds() / 60.0
        fee = booking_fee(station["station_class"], duration_minutes, is_peak, turnover_applied)

        # Wallet sufficiency (priority 22).
        if member["wallet_balance_cents"] < fee:
            raise ApiError("ERR_INSUFFICIENT_WALLET")

        booking = {
            "member_id": member_id,
            "station_id": station["id"],
            "start_utc": body["start_utc"],
            "end_utc": body["end_utc"],
            "is_peak": is_peak,
            "turnover_applied": turnover_applied,
            "fee_cents": fee,
            "status": "CONFIRMED",
        }
        stamp_new(booking)
        db.bookings[booking["id"]] = booking

        member["wallet_balance_cents"] -= fee
        member["lifetime_charged_cents"] += fee
        touch(member)

        return success(_public(booking), 201)


def _load_member_booking(member_id, booking_id):
    find_member(member_id)
    booking = get_or_404(db.bookings, booking_id)
    if booking["member_id"] != member_id:
        raise ApiError("ERR_NOT_FOUND")
    return booking


@bp.get("/members/<member_id>/bookings")
def list_member_bookings(member_id):
    _, role = get_identity()
    require_roles(role, {"MemberOperator", "FacilityManager"})
    limit, offset = parse_pagination()
    status = request.args.get("status")
    station_id = request.args.get("station_id")
    with LOCK:
        find_member(member_id)
        records = [b for b in db.bookings.values() if b["member_id"] == member_id]
        records = sorted_by_creation(records)
        if status:
            records = [b for b in records if b["status"] == status]
        if station_id:
            records = [b for b in records if b["station_id"] == station_id]
        items, total = paginate(records, limit, offset)
    return paginated(items, total, limit, offset)


@bp.get("/members/<member_id>/bookings/<booking_id>")
def get_member_booking(member_id, booking_id):
    _, role = get_identity()
    require_roles(role, {"MemberOperator", "FacilityManager"})
    with LOCK:
        booking = _load_member_booking(member_id, booking_id)
        return success(_public(booking))


@bp.post("/members/<member_id>/bookings/<booking_id>/cancel")
def cancel_booking(member_id, booking_id):
    user_id, role = get_identity()
    require_roles(role, {"MemberOperator"})
    require_owner(role, user_id, member_id)
    with LOCK:
        booking = _load_member_booking(member_id, booking_id)
        if booking["status"] != "CONFIRMED":
            raise ApiError("ERR_INVALID_STATE")
        member = db.members[member_id]
        fee = booking["fee_cents"]
        member["wallet_balance_cents"] += fee
        member["lifetime_charged_cents"] -= fee
        touch(member)
        booking["status"] = "CANCELLED"
        touch(booking)
        return success(_public(booking))


@bp.post("/members/<member_id>/bookings/<booking_id>/complete")
def complete_booking(member_id, booking_id):
    user_id, role = get_identity()
    require_roles(role, {"MemberOperator", "FacilityManager"})
    require_owner(role, user_id, member_id)
    with LOCK:
        booking = _load_member_booking(member_id, booking_id)
        if booking["status"] != "CONFIRMED":
            raise ApiError("ERR_INVALID_STATE")
        booking["status"] = "COMPLETED"
        touch(booking)
        return success(_public(booking))
