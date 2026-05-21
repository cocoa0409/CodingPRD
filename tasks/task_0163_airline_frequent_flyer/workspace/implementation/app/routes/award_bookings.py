"""AwardBooking endpoints."""

from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, g, request

from .. import errors as E
from ..auth import require_roles
from ..envelope import ok_object, ok_array
from ..store import store, new_uuid
from ..timeutil import clock
from ..services.common import (
    get_json_body, require_fields, parse_pagination, paginate,
    bump_version, get_member_or_404, get_flight_or_404, get_booking_owned,
    get_certificate_owned, enforce_member_ownership, enforce_member_status,
)
from ..services.serialize import (
    serialize_award_booking, compute_load_factor, compute_points_balance,
)
from ..services import calc, ledger
from ..services import tier as tier_svc


award_bookings_bp = Blueprint("award_bookings", __name__)


VALID_CABINS = {"ECONOMY", "BUSINESS", "FIRST"}
VALID_MODES = {"DYNAMIC", "FIXED"}


@award_bookings_bp.post("/members/<member_id>/award-bookings")
@require_roles("Member", "BookingAgent")
def create_award_booking(member_id):
    m = get_member_or_404(member_id)
    enforce_member_ownership(g.user_id, g.user_role, member_id)
    body = get_json_body()
    require_fields(body, "flight_id", "cabin", "pricing_mode")
    if body["cabin"] not in VALID_CABINS:
        raise E.ApiError(E.ERR_INVALID_REQUEST, 400, "Invalid cabin.")
    if body["pricing_mode"] not in VALID_MODES:
        raise E.ApiError(E.ERR_INVALID_REQUEST, 400, "Invalid pricing_mode.")
    cash_taxes = body.get("cash_taxes_cents")
    if cash_taxes is not None and (not isinstance(cash_taxes, int) or cash_taxes < 0):
        raise E.ApiError(E.ERR_INVALID_REQUEST, 400, "Invalid cash_taxes_cents.")
    cert_id = body.get("companion_certificate_id")
    f = get_flight_or_404(body["flight_id"])
    enforce_member_status(m)
    if f["status"] != "SCHEDULED":
        raise E.ApiError(E.ERR_FLIGHT_NOT_BOOKABLE, 409, "Flight not bookable.")
    now = clock.now()
    cert = None
    if cert_id is not None:
        cert = get_certificate_owned(member_id, cert_id)
        # State check: cert must be ACTIVE (priority 4 — before tier/temporal/etc.)
        if cert["status"] != "ACTIVE":
            raise E.ApiError(E.ERR_CERTIFICATE_NOT_USABLE, 409, "Certificate not ACTIVE.")
        # Priority 5: tier at issuance must have been PLATINUM (we keep it simple — current member tier
        # at booking time must be PLATINUM or cert issued_reason ADMIN_GRANT implies admin path).
        # Spec: tier at the moment of certificate's original issuance must be PLATINUM.
        # We approximate using current Member.tier per the PRD §3.5 phrasing.
        if not tier_svc.at_least(m["tier"], "PLATINUM"):
            raise E.ApiError(E.ERR_MEMBER_TIER_INELIGIBLE, 403,
                             "Member tier must be at least PLATINUM to redeem a companion certificate.")
        # Priority 6: temporal window [issued_at, expires_at)
        if now >= cert["expires_at"]:
            raise E.ApiError(E.ERR_CERTIFICATE_EXPIRED, 409, "Certificate expired.")
        # Reserve certificate
        cert["status"] = "RESERVED"
        cert["reserved_for_booking_id"] = None  # will be set below
        bump_version(cert, now)
    # Pin pricing
    if body["pricing_mode"] == "DYNAMIC":
        points_cost = calc.award_price_dynamic(f["distance_miles"], compute_load_factor(f), body["cabin"])
    else:
        points_cost = calc.award_price_fixed(f["route_region"], body["cabin"])
    bid = new_uuid()
    b = {
        "id": bid,
        "member_id": member_id,
        "flight_id": f["id"],
        "cabin": body["cabin"],
        "pricing_mode": body["pricing_mode"],
        "points_cost": points_cost,
        "cash_taxes_cents": cash_taxes if cash_taxes is not None else 0,
        "status": "HELD",
        "held_until": now + timedelta(hours=24),
        "companion_certificate_id": cert_id,
        "linked_segment_id": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.award_bookings[bid] = b
    if cert is not None:
        cert["reserved_for_booking_id"] = bid
        bump_version(cert, now)
    return ok_object(serialize_award_booking(b), 201)


@award_bookings_bp.get("/members/<member_id>/award-bookings")
@require_roles("Member", "ProgramAdmin", "BookingAgent")
def list_award_bookings(member_id):
    get_member_or_404(member_id)
    enforce_member_ownership(g.user_id, g.user_role, member_id)
    limit, offset = parse_pagination()
    status_f = request.args.get("status")
    flight_f = request.args.get("flight_id")
    items = [
        b for b in store.award_bookings.values()
        if b["member_id"] == member_id
        and (status_f is None or b["status"] == status_f)
        and (flight_f is None or b["flight_id"] == flight_f)
    ]
    items.sort(key=lambda b: b["created_at"])
    page, total, has_more = paginate(items, limit, offset)
    data = [serialize_award_booking(b) for b in page]
    return ok_array(data, limit, offset, total, has_more)


@award_bookings_bp.get("/members/<member_id>/award-bookings/<booking_id>")
@require_roles("Member", "ProgramAdmin", "BookingAgent")
def get_award_booking(member_id, booking_id):
    get_member_or_404(member_id)
    enforce_member_ownership(g.user_id, g.user_role, member_id)
    b = get_booking_owned(member_id, booking_id)
    return ok_object(serialize_award_booking(b))


@award_bookings_bp.post("/members/<member_id>/award-bookings/<booking_id>/confirm")
@require_roles("Member")
def confirm_award_booking(member_id, booking_id):
    m = get_member_or_404(member_id)
    enforce_member_ownership(g.user_id, g.user_role, member_id)
    b = get_booking_owned(member_id, booking_id)
    # Priority 4: state — must be HELD
    if b["status"] != "HELD":
        raise E.ApiError(E.ERR_BOOKING_NOT_HOLDABLE, 409, "Booking is not HELD.")
    f = store.flights.get(b["flight_id"])
    if not f or f["status"] != "SCHEDULED":
        raise E.ApiError(E.ERR_FLIGHT_NOT_BOOKABLE, 409, "Flight not bookable.")
    now = clock.now()
    # Priority 6: temporal — held_until and certificate validity
    if now >= b["held_until"]:
        raise E.ApiError(E.ERR_HELD_UNTIL_PASSED, 409, "Booking hold has elapsed.")
    cert = None
    if b.get("companion_certificate_id"):
        cert = store.companion_certificates.get(b["companion_certificate_id"])
        if not cert or cert["status"] != "RESERVED":
            raise E.ApiError(E.ERR_CERTIFICATE_NOT_USABLE, 409, "Companion certificate is not RESERVED.")
        if cert["member_id"] != member_id:
            raise E.ApiError(E.ERR_OWNERSHIP_MISMATCH, 403, "Certificate does not belong to member.")
        if now >= cert["expires_at"]:
            raise E.ApiError(E.ERR_CERTIFICATE_EXPIRED, 409, "Certificate expired.")
    # Priority 8: points sufficiency
    bal = compute_points_balance(member_id, now)
    if bal < b["points_cost"]:
        raise E.ApiError(E.ERR_INSUFFICIENT_POINTS, 402, "Insufficient points.")
    # Priority 9: member status
    enforce_member_status(m)
    # Side effects
    ledger.append(
        member_id=member_id,
        kind="REDEMPTION",
        points_delta=-b["points_cost"],
        posted_at=now,
        related_booking_id=b["id"],
        related_certificate_id=b.get("companion_certificate_id"),
        now=now,
    )
    # Create new FlightSegment in BOOKED
    sid = new_uuid()
    seg = {
        "id": sid,
        "member_id": member_id,
        "flight_id": f["id"],
        "booked_cabin": b["cabin"],
        "flown_cabin": None,
        "status": "BOOKED",
        "flown_year": None,
        "qualifying_points_earned": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.segments[sid] = seg
    b["linked_segment_id"] = sid
    b["status"] = "CONFIRMED"
    bump_version(b, now)
    if cert is not None:
        cert["status"] = "USED"
        cert["used_on_booking_id"] = b["id"]
        cert["reserved_for_booking_id"] = None
        bump_version(cert, now)
    m["last_activity_at"] = now
    bump_version(m, now)
    return ok_object(serialize_award_booking(b))


@award_bookings_bp.post("/members/<member_id>/award-bookings/<booking_id>/cancel")
@require_roles("Member")
def cancel_award_booking(member_id, booking_id):
    m = get_member_or_404(member_id)
    enforce_member_ownership(g.user_id, g.user_role, member_id)
    b = get_booking_owned(member_id, booking_id)
    if b["status"] != "CONFIRMED":
        raise E.ApiError(E.ERR_BOOKING_NOT_CANCELLABLE, 409, "Booking is not CONFIRMED.")
    f = store.flights.get(b["flight_id"])
    if not f or f["status"] != "SCHEDULED":
        raise E.ApiError(E.ERR_BOOKING_NOT_CANCELLABLE, 409, "Flight no longer SCHEDULED.")
    now = clock.now()
    # Compensating ledger row
    ledger.append(
        member_id=member_id,
        kind="REDEMPTION_REFUND",
        points_delta=b["points_cost"],
        posted_at=now,
        related_booking_id=b["id"],
        related_certificate_id=b.get("companion_certificate_id"),
        now=now,
    )
    # CONFIRMED -> CANCELLED -> REFUNDED in same transaction
    b["status"] = "REFUNDED"
    bump_version(b, now)
    # Cascade segment cancellation
    if b.get("linked_segment_id"):
        s = store.segments.get(b["linked_segment_id"])
        if s and s["status"] == "BOOKED":
            s["status"] = "CANCELLED"
            bump_version(s, now)
    # Restore companion certificate if still inside its validity window
    if b.get("companion_certificate_id"):
        cert = store.companion_certificates.get(b["companion_certificate_id"])
        if cert and cert["status"] == "USED":
            if now < cert["expires_at"]:
                cert["status"] = "ACTIVE"
                cert["used_on_booking_id"] = None
                bump_version(cert, now)
            # else: leave USED (naturally expired)
    m["last_activity_at"] = now
    bump_version(m, now)
    return ok_object(serialize_award_booking(b))
