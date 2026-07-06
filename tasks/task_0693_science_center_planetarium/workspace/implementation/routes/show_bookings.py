"""ShowBooking endpoints (PRD §3.4)."""
from flask import Blueprint, request

from db import db, new_record, touch
from clock import iso
from errors import (
    err,
    ERR_INVALID_STATE,
    ERR_STALE_SHOW_VERSION,
    ERR_ACCESSIBLE_SEATS_UNAVAILABLE,
    ERR_SHOW_CAPACITY_EXCEEDED,
    ERR_HOLD_EXPIRED,
    ERR_VALIDATION,
)
from middleware import authenticate, require_role
from response import success
from services.common import (
    get_body,
    require_string,
    require_int,
    optional_int,
    parse_pagination,
    paginate,
)
from services.lookups import get_show, get_membership, get_show_booking
from services.serialize import show_booking_view
from services.calculations import show_admission_pricing
from services.show_logic import (
    recompute_seats_sold,
    bubble_after_recompute,
    capacity_of,
    accessible_seats_of,
    accessible_seats_used,
)

bp = Blueprint("show_bookings", __name__)


@bp.route("/show-bookings", methods=["POST"])
def create_booking():
    _, role = authenticate()
    require_role(role, {"BoxOfficeOperator"})
    body = get_body()
    # Body structure (priority 4) — required fields present and typed.
    require_string(body, "show_event_id")
    show_id = body["show_event_id"]
    party_size = require_int(body, "party_size")
    expected_show_version = require_int(body, "expected_show_version")
    accessible_req = optional_int(body, "accessible_seats_requested", 0)
    membership_id = body.get("membership_id")

    with db.lock:
        # Existence (priority 3): path/body FKs left-to-right.
        show = get_show(show_id)
        membership = None
        if membership_id is not None:
            membership = get_membership(membership_id)

        # State (priority 5): a hold is created on an OPEN show.
        if show["status"] != "OPEN":
            raise err(ERR_INVALID_STATE, "Show is not OPEN for booking")

        # OCC stale-version (priority 6).
        if expected_show_version != show["version"]:
            raise err(ERR_STALE_SHOW_VERSION, "Show version is stale")

        # Accessibility (priority 7): requested accessible seats must not exceed
        # the show venue's remaining accessible seats. Checked before the
        # generic field-range (priority 20) per PRD §3.10.
        remaining_accessible = accessible_seats_of(show) - accessible_seats_used(show)
        if accessible_req > remaining_accessible:
            raise err(ERR_ACCESSIBLE_SEATS_UNAVAILABLE, "Not enough accessible seats remain")

        # Show seat capacity (priority 15).
        if show["seats_sold"] + party_size > capacity_of(show):
            raise err(ERR_SHOW_CAPACITY_EXCEEDED, "Show capacity exceeded")

        # Generic field-range (priority 20, lowest): reported only if no
        # higher-priority check fired.
        if party_size < 1:
            raise err(ERR_VALIDATION, "party_size must be >= 1")
        if accessible_req < 0 or accessible_req > party_size:
            raise err(ERR_VALIDATION, "accessible_seats_requested must be 0..party_size")

        # Snapshot pricing at hold time.
        gross, discount, net = show_admission_pricing(show, party_size, membership)

        now = db.clock.now
        rec = new_record(with_version=True)
        rec.update({
            "show_event_id": show_id,
            "membership_id": membership_id,
            "party_size": party_size,
            "accessible_seats_requested": accessible_req,
            "gross_price_cents": gross,
            "member_discount_cents": discount,
            "net_price_cents": net,
            "expected_show_version": expected_show_version,
            "status": "HELD",
            "held_at": iso(now),
            "_held_at_dt": now,
        })
        db.show_bookings[rec["id"]] = rec

        # Reserve seats: recompute seats_sold, bubble-up SOLD_OUT, bump version.
        recompute_seats_sold(show)
        bubble_after_recompute(show)
        touch(show)
    return success(show_booking_view(rec), status=201)


@bp.route("/show-bookings", methods=["GET"])
def list_bookings():
    _, role = authenticate()
    require_role(role, {"BoxOfficeOperator", "AccessibilityCoordinator"})
    limit, offset = parse_pagination()
    show_event_id = request.args.get("show_event_id")
    membership_id = request.args.get("membership_id")
    status = request.args.get("status")
    with db.lock:
        records = list(db.show_bookings.values())
        if show_event_id is not None:
            records = [b for b in records if b["show_event_id"] == show_event_id]
        if membership_id is not None:
            records = [b for b in records if b["membership_id"] == membership_id]
        if status is not None:
            records = [b for b in records if b["status"] == status]
        page, meta = paginate(records, limit, offset)
        data = [show_booking_view(b) for b in page]
    return success(data, status=200, pagination=meta)


@bp.route("/show-bookings/<bid>", methods=["GET"])
def get_one_booking(bid):
    _, role = authenticate()
    require_role(role, {"BoxOfficeOperator", "AccessibilityCoordinator"})
    with db.lock:
        b = get_show_booking(bid)
        return success(show_booking_view(b), status=200)


@bp.route("/show-bookings/<bid>/confirm", methods=["POST"])
def confirm_booking(bid):
    _, role = authenticate()
    require_role(role, {"BoxOfficeOperator"})
    with db.lock:
        b = get_show_booking(bid)
        # State (priority 5): must be HELD.
        if b["status"] != "HELD":
            raise err(ERR_INVALID_STATE, "Booking is not HELD")
        # Hold-expiry (priority 13): clock < held_at + 30 minutes.
        expiry = db.clock.plus_minutes(b["_held_at_dt"], 30)
        if not (db.clock.now < expiry):
            raise err(ERR_HOLD_EXPIRED, "Hold window has elapsed")
        show = get_show(b["show_event_id"])
        # Linked show must be OPEN or SOLD_OUT.
        if show["status"] not in ("OPEN", "SOLD_OUT"):
            raise err(ERR_INVALID_STATE, "Linked show is not bookable")
        # Freeze net_price_cents (no recompute). Seat count unchanged.
        b["status"] = "CONFIRMED"
        touch(b)
        recompute_seats_sold(show)
        bubble_after_recompute(show)
        touch(show)
        return success(show_booking_view(b), status=200)


@bp.route("/show-bookings/<bid>/cancel", methods=["POST"])
def cancel_booking(bid):
    _, role = authenticate()
    require_role(role, {"BoxOfficeOperator"})
    with db.lock:
        b = get_show_booking(bid)
        # Permitted while HELD.
        if b["status"] != "HELD":
            raise err(ERR_INVALID_STATE, "Booking is not HELD")
        show = get_show(b["show_event_id"])
        b["status"] = "CANCELLED"
        touch(b)
        recompute_seats_sold(show)
        bubble_after_recompute(show)
        touch(show)
        return success(show_booking_view(b), status=200)


@bp.route("/show-bookings/<bid>/refund", methods=["POST"])
def refund_booking(bid):
    _, role = authenticate()
    require_role(role, {"BoxOfficeOperator"})
    with db.lock:
        b = get_show_booking(bid)
        # Permitted only while CONFIRMED.
        if b["status"] != "CONFIRMED":
            raise err(ERR_INVALID_STATE, "Booking is not CONFIRMED")
        show = get_show(b["show_event_id"])
        # Clock must be before the linked show's starts_at.
        if not (db.clock.now < show["_starts_at_dt"]):
            raise err(ERR_INVALID_STATE, "Show has already started")
        b["status"] = "REFUNDED"
        touch(b)
        recompute_seats_sold(show)
        bubble_after_recompute(show)
        touch(show)
        return success(show_booking_view(b), status=200)
