"""CompRoomBooking endpoints."""
import math

from flask import Blueprint, request

import clock
import db
from auth import require_role
from common import (
    get_json_or_400, require_str, require_int, require_iso_datetime,
    parse_pagination, paginate, stamp_create, stamp_update,
    get_or_404, fk_or_404,
)
from errors import (
    ApiError, ERR_INVALID_STATE, ERR_STALE_MEMBER_VERSION,
    ERR_MEMBER_EXCLUDED, ERR_MEMBER_VELOCITY_SUSPENDED,
    ERR_TIER_INELIGIBLE_FOR_COMP, ERR_BOOKING_INVALID_DATES,
    ERR_BOOKING_OVERLAP, ERR_UNAUTHORIZED,
)
from response import success_object, success_array
from services.serializers import comp_room_booking_view
from services.calculations import comp_room_rate


bp = Blueprint("comp_room_bookings", __name__)

OCCUPANCY_CAP = 20
COMP_ELIGIBLE_TIERS = {"PLATINUM", "DIAMOND", "SEVEN_STARS"}


def _compute_nights(check_in_dt, check_out_dt) -> int:
    delta = check_out_dt - check_in_dt
    seconds = delta.total_seconds()
    return int(math.ceil(seconds / 86400.0))


def _interval_overlap_count(property_id, check_in_dt, check_out_dt, *, exclude_booking_id=None) -> int:
    """Maximum aggregate occupancy at any point in [check_in, check_out).

    The window is half-open: [check_in, check_out). Two intervals overlap iff
    A.start < B.end AND B.start < A.end (treating both as half-open).
    The aggregate occupancy at any sub-interval = count of intervals containing it.
    Using sweep on event points restricted to the new interval's range.
    """
    events = []  # (time, +1 or -1)
    events.append((check_in_dt, +1))
    events.append((check_out_dt, -1))
    for b in db.comp_room_bookings.values():
        if exclude_booking_id and b["id"] == exclude_booking_id:
            continue
        if b["property_id"] != property_id:
            continue
        if b["status"] not in ("PENDING", "CONFIRMED", "CHECKED_IN"):
            continue
        b_in = clock.parse_iso(b["check_in"])
        b_out = clock.parse_iso(b["check_out"])
        # Standard half-open overlap test.
        if b_in < check_out_dt and check_in_dt < b_out:
            events.append((b_in, +1))
            events.append((b_out, -1))
    # Sort: at same instant, end (-1) comes before start (+1) so touching is OK.
    events.sort(key=lambda e: (e[0], 0 if e[1] == -1 else 1))
    current = 0
    peak = 0
    for _t, delta in events:
        current += delta
        if current > peak:
            peak = current
    return peak


@bp.route("/comp-room-bookings", methods=["POST"])
def create_booking():
    require_role({"LoyaltyManager"})
    body = get_json_or_400()
    member_id = require_str(body, "member_id")
    property_id = require_str(body, "property_id")
    check_in_dt = require_iso_datetime(body, "check_in")
    check_out_dt = require_iso_datetime(body, "check_out")
    expected_member_version = require_int(body, "expected_member_version", minimum=0)

    with db.lock:
        member = fk_or_404(db.members, member_id, "member")
        prop = fk_or_404(db.properties, property_id, "property")

        # priority 5: OCC check
        if expected_member_version != member["version"]:
            raise ApiError(ERR_STALE_MEMBER_VERSION, 412,
                           "expected_member_version does not match Member.version")

        # priority 6: exclusion
        if member["exclusion_status"] == "EXCLUDED":
            raise ApiError(ERR_MEMBER_EXCLUDED, 422,
                           "member is excluded; booking blocked")

        # priority 7: velocity suspended
        if member["velocity_status"] == "SUSPENDED":
            raise ApiError(ERR_MEMBER_VELOCITY_SUSPENDED, 422,
                           "member is velocity-suspended; booking blocked")

        # priority 15: check_out > check_in
        if not (check_out_dt > check_in_dt):
            raise ApiError(ERR_BOOKING_INVALID_DATES, 422,
                           "check_out must be strictly greater than check_in")

        # priority 19: aggregate overlap > cap
        new_count = _interval_overlap_count(property_id, check_in_dt, check_out_dt)
        if new_count > OCCUPANCY_CAP:
            raise ApiError(ERR_BOOKING_OVERLAP, 409,
                           "booking exceeds property occupancy cap on overlap")

        nights = _compute_nights(check_in_dt, check_out_dt)
        provisional_rate = comp_room_rate(
            prop["base_room_rate_cents"], member["tier_status"], prop["market_segment"]
        )
        total = nights * provisional_rate

        row = {
            "member_id": member_id,
            "property_id": property_id,
            "check_in": clock.iso(check_in_dt),
            "check_out": clock.iso(check_out_dt),
            "nights": nights,
            "provisional_rate_cents": provisional_rate,
            "final_rate_cents": None,
            "total_charge_cents": total,
            "status": "PENDING",
        }
        stamp_create(row)
        db.comp_room_bookings[row["id"]] = row

        stamp_update(member)
        return success_object(comp_room_booking_view(row), 201)


@bp.route("/comp-room-bookings/<bid>/confirm", methods=["POST"])
def confirm_booking(bid):
    require_role({"LoyaltyManager"})
    with db.lock:
        b = get_or_404(db.comp_room_bookings, bid, "comp room booking")
        if b["status"] != "PENDING":
            raise ApiError(ERR_INVALID_STATE, 409, "booking is not PENDING")
        member = db.members.get(b["member_id"])
        if member is None:
            raise ApiError(ERR_INVALID_STATE, 409, "owning member missing")
        # priority 6
        if member["exclusion_status"] == "EXCLUDED":
            raise ApiError(ERR_MEMBER_EXCLUDED, 422, "member is excluded")
        # priority 7
        if member["velocity_status"] == "SUSPENDED":
            raise ApiError(ERR_MEMBER_VELOCITY_SUSPENDED, 422,
                           "member is velocity-suspended")
        # priority 11: tier eligibility
        if member["tier_status"] not in COMP_ELIGIBLE_TIERS:
            raise ApiError(ERR_TIER_INELIGIBLE_FOR_COMP, 422,
                           "member tier ineligible for comp")

        b["status"] = "CONFIRMED"
        stamp_update(b)
        return success_object(comp_room_booking_view(b), 200)


@bp.route("/comp-room-bookings/<bid>/check-in", methods=["POST"])
def checkin_booking(bid):
    require_role({"LoyaltyManager"})
    with db.lock:
        b = get_or_404(db.comp_room_bookings, bid, "comp room booking")
        if b["status"] != "CONFIRMED":
            raise ApiError(ERR_INVALID_STATE, 409, "booking is not CONFIRMED")
        member = db.members.get(b["member_id"])
        prop = db.properties.get(b["property_id"])
        if member is None or prop is None:
            raise ApiError(ERR_INVALID_STATE, 409, "owning member/property missing")
        # priority 6
        if member["exclusion_status"] == "EXCLUDED":
            raise ApiError(ERR_MEMBER_EXCLUDED, 422, "member is excluded")
        # priority 7
        if member["velocity_status"] == "SUSPENDED":
            raise ApiError(ERR_MEMBER_VELOCITY_SUSPENDED, 422,
                           "member is velocity-suspended")

        check_in_dt = clock.parse_iso(b["check_in"])
        now = clock.now()
        if not (now >= check_in_dt):
            raise ApiError(ERR_INVALID_STATE, 409,
                           "current_utc is before booking check_in")

        # Recompute FINAL rate using current tier.
        final_rate = comp_room_rate(
            prop["base_room_rate_cents"], member["tier_status"], prop["market_segment"]
        )
        b["final_rate_cents"] = final_rate
        b["total_charge_cents"] = b["nights"] * final_rate
        b["status"] = "CHECKED_IN"
        stamp_update(b)
        return success_object(comp_room_booking_view(b), 200)


@bp.route("/comp-room-bookings/<bid>/check-out", methods=["POST"])
def checkout_booking(bid):
    require_role({"LoyaltyManager"})
    with db.lock:
        b = get_or_404(db.comp_room_bookings, bid, "comp room booking")
        if b["status"] != "CHECKED_IN":
            raise ApiError(ERR_INVALID_STATE, 409, "booking is not CHECKED_IN")

        check_out_dt = clock.parse_iso(b["check_out"])
        now = clock.now()
        if not (now >= check_out_dt):
            raise ApiError(ERR_INVALID_STATE, 409,
                           "current_utc is before booking check_out")

        b["status"] = "COMPLETED"
        stamp_update(b)
        return success_object(comp_room_booking_view(b), 200)


@bp.route("/comp-room-bookings/<bid>/cancel", methods=["POST"])
def cancel_booking(bid):
    uid, role = require_role({"LoyaltyManager", "Member"})
    with db.lock:
        b = get_or_404(db.comp_room_bookings, bid, "comp room booking")
        # Member can only cancel own bookings.
        if role == "Member" and b["member_id"] != uid:
            raise ApiError(ERR_UNAUTHORIZED, 403,
                           "members may only cancel their own bookings")
        if b["status"] not in ("PENDING", "CONFIRMED"):
            raise ApiError(ERR_INVALID_STATE, 409,
                           "booking is not cancellable (must be PENDING or CONFIRMED)")
        b["status"] = "CANCELLED"
        stamp_update(b)
        return success_object(comp_room_booking_view(b), 200)


@bp.route("/comp-room-bookings/<bid>/revert-to-pending", methods=["POST"])
def revert_to_pending(bid):
    require_role({"LoyaltyManager"})
    with db.lock:
        b = get_or_404(db.comp_room_bookings, bid, "comp room booking")
        if b["status"] != "CONFIRMED":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "booking is not CONFIRMED")
        check_in_dt = clock.parse_iso(b["check_in"])
        now = clock.now()
        if not (now < check_in_dt):
            raise ApiError(ERR_INVALID_STATE, 409,
                           "revert-to-pending requires current_utc strictly before check_in")
        b["status"] = "PENDING"
        stamp_update(b)
        return success_object(comp_room_booking_view(b), 200)


@bp.route("/comp-room-bookings/<bid>", methods=["GET"])
def get_booking(bid):
    uid, role = require_role({"LoyaltyManager", "MemberServices", "Member"})
    with db.lock:
        b = get_or_404(db.comp_room_bookings, bid, "comp room booking")
        if role == "Member" and b["member_id"] != uid:
            raise ApiError(ERR_UNAUTHORIZED, 403,
                           "members may only read their own bookings")
        return success_object(comp_room_booking_view(b), 200)


@bp.route("/comp-room-bookings", methods=["GET"])
def list_bookings():
    uid, role = require_role({"LoyaltyManager", "MemberServices", "ComplianceOfficer", "Member"})
    member_id = request.args.get("member_id")
    property_id = request.args.get("property_id")
    status = request.args.get("status")
    limit, offset = parse_pagination()
    with db.lock:
        rows = list(db.comp_room_bookings.values())
        if role == "Member":
            # Members can only see their own bookings.
            rows = [r for r in rows if r["member_id"] == uid]
        if member_id is not None:
            rows = [r for r in rows if r["member_id"] == member_id]
        if property_id is not None:
            rows = [r for r in rows if r["property_id"] == property_id]
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        rows.sort(key=lambda r: r["created_at"])
        page, total = paginate(rows, limit, offset)
        return success_array([comp_room_booking_view(r) for r in page], limit, offset, total, 200)
