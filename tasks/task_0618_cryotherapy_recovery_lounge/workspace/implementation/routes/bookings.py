"""Booking endpoints (PRD §3.5)."""

from flask import Blueprint, request, g

import errors
from clock import (
    clock, parse_iso8601, format_iso8601_ms, floor_minutes_between,
)
from datetime import timedelta
from db import db
from helpers import (
    get_body, require_str, require_int, parse_pagination, sort_by_created,
    paginate, stamp_new, touch,
)
from middleware import require_roles
from response import success, list_success
from serializers import serialize_booking
from services.booking_credits import debit_credits, refund_credits
from services.calculations import cancellation_fee_cents, FREE_CANCEL_MINUTES
from services.compute import (
    increment_open_booking_count, decrement_open_booking_count,
    recompute_credit_balance_by_member_id,
)
from services.lookups import (
    get_member_or_404, get_room_or_404, get_booking_or_404,
    ref_location_or_404, ref_room_or_404, require_member_ownership,
)

bp = Blueprint("bookings", __name__)


def _intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) interiors intersect? Touching endpoints do not."""
    return a_start < b_end and b_start < a_end


def _member_active_subscription(member_id):
    for sub in db.subscriptions.values():
        if sub["member_id"] == member_id and sub["status"] != "CANCELLED":
            return sub
    return None


def _plan_waives_fee(member_id):
    sub = _member_active_subscription(member_id)
    if sub is None or sub["status"] != "ACTIVE":
        return False
    plan = db.membership_plans.get(sub["plan_id"])
    return bool(plan and plan["late_cancel_fee_waived"])


@bp.post("/bookings")
@require_roles("Member", "LocationManager")
def create_booking():
    body = get_body()
    member_id = require_str(body, "member_id")
    location_id = require_str(body, "location_id")
    room_id = require_str(body, "room_id")
    starts_at_raw = require_str(body, "starts_at")
    expected_room_version = require_int(body, "expected_room_version")
    try:
        starts_at = parse_iso8601(starts_at_raw)
    except ValueError:
        raise errors.invalid_request("starts_at must be an ISO 8601 instant")

    # Priority 2: ownership — a Member may only book for themselves.
    require_member_ownership(member_id)
    # Priority 4: body FK existence (member, location, room).
    member = db.members.get(member_id)
    if member is None:
        raise errors.reference_not_found("Referenced member does not exist")
    location = ref_location_or_404(location_id)
    room = ref_room_or_404(room_id)
    service = db.service_types.get(room["service_type_id"])

    # Priority 8: optimistic concurrency on the room version.
    if expected_room_version != room["version"]:
        raise errors.stale_version("Stale room version")

    # Priority 10: location must be OPEN.
    if location["status"] != "OPEN":
        raise errors.ApiError(
            errors.ERR_LOCATION_CLOSED, 409, "Location is CLOSED")

    # Priority 12: the room's service must be active.
    if not service["active"]:
        raise errors.ApiError(
            errors.ERR_SERVICE_INACTIVE, 409, "Service type is inactive")

    # Priority 13/14 order (PRD §3.5): waiver first, then contraindication.
    active_waiver = None
    for w in db.waivers.values():
        if w["member_id"] == member_id and w["status"] == "ACTIVE":
            active_waiver = w
            break
    if active_waiver is None:
        raise errors.ApiError(
            errors.ERR_WAIVER_REQUIRED, 422, "Member has no ACTIVE waiver")
    if service["requires_medical_clearance"] and member["contraindication_flag"]:
        raise errors.ApiError(
            errors.ERR_CONTRAINDICATION_BLOCK, 422,
            "Service requires medical clearance and member is flagged")

    # Compute the occupied interval [starts_at, starts_at+duration+buffer).
    occupies_until = starts_at + timedelta(
        minutes=service["duration_minutes"] + service["buffer_minutes"])

    # Priority 15: room temporal overlap with existing BOOKED bookings.
    for b in db.bookings.values():
        if b["room_id"] != room_id or b["status"] != "BOOKED":
            continue
        if _intervals_overlap(
            starts_at, occupies_until,
            parse_iso8601(b["starts_at"]), parse_iso8601(b["occupies_until_at"]),
        ):
            raise errors.ApiError(
                errors.ERR_ROOM_UNAVAILABLE, 409, "Room interval is unavailable")

    # Priority 17: staffing — interval fully covered by a SCHEDULED shift at the
    # booking's location.
    covered = False
    for s in db.technician_shifts.values():
        if s["location_id"] != location_id or s["status"] != "SCHEDULED":
            continue
        s_start = parse_iso8601(s["starts_at"])
        s_end = parse_iso8601(s["ends_at"])
        if s_start <= starts_at and occupies_until <= s_end:
            covered = True
            break
    if not covered:
        raise errors.ApiError(
            errors.ERR_NO_TECHNICIAN_ON_DUTY, 409,
            "No technician shift fully covers the booking interval")

    # Priority 20: credit waterfall (atomic — raises if it cannot cover).
    cost = service["credit_cost"]
    credits_charged, credit_source, debit_plan = debit_credits(member_id, cost)

    booking = stamp_new({
        "member_id": member_id,
        "location_id": location_id,
        "room_id": room_id,
        "service_type_id": room["service_type_id"],
        "starts_at": starts_at_raw,
        "occupies_until_at": format_iso8601_ms(occupies_until),
        "credits_charged": credits_charged,
        "credit_source": credit_source,
        "fee_charged_cents": 0,
        "status": "BOOKED",
        "_debit_plan": debit_plan,
    })
    db.bookings[booking["id"]] = booking

    # Side effects: bump room version, increment open_booking_count, recompute
    # member credit_balance (already recomputed in debit_credits, but the
    # location and room mutations follow).
    touch(room)
    increment_open_booking_count(location)
    recompute_credit_balance_by_member_id(member_id)
    return success(serialize_booking(booking), 201)


@bp.get("/bookings")
@require_roles("PlatformAdmin", "LocationManager", "Technician", "Member")
def list_bookings():
    limit, offset = parse_pagination()
    member_id = request.args.get("member_id")
    location_id = request.args.get("location_id")
    room_id = request.args.get("room_id")
    service_type_id = request.args.get("service_type_id")
    status = request.args.get("status")
    items = list(db.bookings.values())
    if g.user_role == "Member":
        items = [b for b in items if b["member_id"] == g.user_id]
    if member_id is not None:
        items = [b for b in items if b["member_id"] == member_id]
    if location_id is not None:
        items = [b for b in items if b["location_id"] == location_id]
    if room_id is not None:
        items = [b for b in items if b["room_id"] == room_id]
    if service_type_id is not None:
        items = [b for b in items if b["service_type_id"] == service_type_id]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return list_success([serialize_booking(b) for b in page], limit, offset, total)


@bp.get("/bookings/<booking_id>")
@require_roles("PlatformAdmin", "LocationManager", "Technician", "Member")
def get_booking(booking_id):
    booking = get_booking_or_404(booking_id)
    if g.user_role == "Member" and g.user_id != booking["member_id"]:
        raise errors.forbidden("A member may read only their own bookings")
    return success(serialize_booking(booking), 200)


@bp.post("/bookings/<booking_id>/cancel")
@require_roles("Member", "LocationManager")
def cancel_booking(booking_id):
    booking = get_booking_or_404(booking_id)
    if g.user_role == "Member" and g.user_id != booking["member_id"]:
        raise errors.forbidden("A member may cancel only their own bookings")
    # Permitted only while BOOKED and strictly before starts_at.
    if booking["status"] != "BOOKED":
        raise errors.invalid_state("Booking is not BOOKED")
    starts_at = parse_iso8601(booking["starts_at"])
    if not (clock.now() < starts_at):
        raise errors.invalid_state("Booking has already started")
    notice_minutes = floor_minutes_between(clock.now(), starts_at)
    fee = cancellation_fee_cents(
        "CANCEL", notice_minutes, _plan_waives_fee(booking["member_id"]))
    booking["status"] = "CANCELLED"
    booking["fee_charged_cents"] = fee
    touch(booking)
    # Refund credits to source.
    refund_credits(booking["member_id"], booking.get("_debit_plan", {}))
    recompute_credit_balance_by_member_id(booking["member_id"])
    location = db.locations.get(booking["location_id"])
    if location is not None:
        decrement_open_booking_count(location)
    return success(serialize_booking(booking), 200)


@bp.post("/bookings/<booking_id>/complete")
@require_roles("Technician", "LocationManager")
def complete_booking(booking_id):
    booking = get_booking_or_404(booking_id)
    # Permitted only while BOOKED.
    if booking["status"] != "BOOKED":
        raise errors.invalid_state("Booking is not BOOKED")
    # Technician must have a SCHEDULED shift at the booking's location covering
    # starts_at, and (ownership) the acting technician must be on their own shift.
    if g.user_role == "Technician":
        starts_at = parse_iso8601(booking["starts_at"])
        has_shift = False
        for s in db.technician_shifts.values():
            if s["technician_id"] != g.user_id:
                continue
            if s["location_id"] != booking["location_id"]:
                continue
            if s["status"] != "SCHEDULED":
                continue
            if parse_iso8601(s["starts_at"]) <= starts_at < parse_iso8601(s["ends_at"]):
                has_shift = True
                break
        if not has_shift:
            raise errors.forbidden(
                "Technician is not on a covering shift for this booking")
    # Only once the clock has reached or passed starts_at.
    if not (clock.now() >= parse_iso8601(booking["starts_at"])):
        raise errors.invalid_state("Booking has not started yet")
    booking["status"] = "COMPLETED"
    touch(booking)
    location = db.locations.get(booking["location_id"])
    if location is not None:
        decrement_open_booking_count(location)
    return success(serialize_booking(booking), 200)


@bp.post("/bookings/<booking_id>/no-show")
@require_roles("Technician", "LocationManager")
def no_show_booking(booking_id):
    booking = get_booking_or_404(booking_id)
    if booking["status"] != "BOOKED":
        raise errors.invalid_state("Booking is not BOOKED")
    if not (clock.now() >= parse_iso8601(booking["starts_at"])):
        raise errors.invalid_state("Booking has not started yet")
    fee = cancellation_fee_cents(
        "NO_SHOW", 0, _plan_waives_fee(booking["member_id"]))
    booking["status"] = "NO_SHOW"
    booking["fee_charged_cents"] = fee
    touch(booking)
    # Consumed credits are NOT refunded on no-show.
    location = db.locations.get(booking["location_id"])
    if location is not None:
        decrement_open_booking_count(location)
    return success(serialize_booking(booking), 200)
