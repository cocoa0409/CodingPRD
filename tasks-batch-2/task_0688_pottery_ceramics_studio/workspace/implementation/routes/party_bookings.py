"""PartyBooking routes (PRD §3.6; SCAFFOLD §1.5).

RBAC:
  POST /party-bookings                    StudioStaff, StudioManager
  GET  /party-bookings/{id}               StudioStaff, StudioManager, LoyaltyMember(own)
  GET  /party-bookings                    StudioStaff, StudioManager
  POST /party-bookings/{id}/pay-deposit   StudioStaff, StudioManager
  POST /party-bookings/{id}/expire        StudioManager
  POST /party-bookings/{id}/cancel        StudioManager
"""

from flask import Blueprint, request

from clock import clock, parse_iso
from db import db, new_id, stamp_common, touch
from errors import (ApiError, invalid_state, invalid_request,
                    ERR_BOOKING_DATE_PAST, ERR_DEPOSIT_AMOUNT_MISMATCH)
from middleware import get_caller, require_roles
from response import success, list_success, parse_pagination, paginate
from services import serializers, calculations
from services.lookup import get_booking, get_member, assert_member_owns
from services.validation import require_body, require_str, require_int, require_enum

bp = Blueprint("party_bookings", __name__)

STAFF_MANAGER = {"StudioStaff", "StudioManager"}
STAFF_MANAGER_MEMBER = {"StudioStaff", "StudioManager", "LoyaltyMember"}
PACKAGE_TIERS = {"BASIC", "DELUXE"}


@bp.route("/party-bookings", methods=["POST"])
def create_booking():
    caller = get_caller()
    require_roles(caller, STAFF_MANAGER)
    payload = require_body(request.get_json(silent=True))
    member_id = require_str(payload, "member_id")
    package_tier = require_enum(payload, "package_tier", PACKAGE_TIERS)
    guest_count = require_int(payload, "guest_count", minimum=1)
    scheduled_for = require_str(payload, "scheduled_for")

    # Existence: host member must exist (PRD §3.6).
    member = get_member(member_id)

    # Field-shape: guest_count must meet the package minimum (ERR_INVALID_REQUEST).
    min_guests = calculations.PACKAGE_MIN_GUESTS[package_tier]
    if guest_count < min_guests:
        raise invalid_request(
            "guest_count below package minimum (%s requires >= %s)"
            % (package_tier, min_guests))

    # Temporal: scheduled_for must be strictly after current logical clock.
    try:
        sched_dt = parse_iso(scheduled_for)
    except ValueError:
        raise invalid_request("scheduled_for must be an ISO 8601 instant")
    if not (sched_dt > clock.now()):
        raise ApiError(ERR_BOOKING_DATE_PAST, 422,
                       "scheduled_for must be strictly in the future")

    package_total, deposit_due = calculations.party_deposit(package_tier, guest_count)

    record = {
        "id": new_id(),
        "member_id": member_id,
        "package_tier": package_tier,
        "guest_count": guest_count,
        "scheduled_for": scheduled_for,
        "package_total_cents": package_total,
        "deposit_due_cents": deposit_due,
        "deposit_paid_cents": 0,
        "status": "DEPOSIT_PENDING",
    }
    stamp_common(record)
    db.party_bookings[record["id"]] = record
    return success(serializers.party_booking(record), status=201)


@bp.route("/party-bookings/<booking_id>", methods=["GET"])
def fetch_booking(booking_id):
    caller = get_caller()
    require_roles(caller, STAFF_MANAGER_MEMBER)
    booking = get_booking(booking_id)
    assert_member_owns(caller, booking["member_id"])
    return success(serializers.party_booking(booking))


@bp.route("/party-bookings", methods=["GET"])
def list_bookings():
    caller = get_caller()
    require_roles(caller, STAFF_MANAGER)
    limit, offset = parse_pagination(request.args)
    records = list(db.party_bookings.values())
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    member_id = request.args.get("member_id")
    if member_id is not None:
        records = [r for r in records if r["member_id"] == member_id]
    window, total = paginate(records, limit, offset)
    return list_success([serializers.party_booking(r) for r in window], limit, offset, total)


@bp.route("/party-bookings/<booking_id>/pay-deposit", methods=["POST"])
def pay_deposit(booking_id):
    caller = get_caller()
    require_roles(caller, STAFF_MANAGER)
    booking = get_booking(booking_id)
    payload = require_body(request.get_json(silent=True))
    amount_cents = require_int(payload, "amount_cents", minimum=0)

    # State: must be DEPOSIT_PENDING (PRD §3.6).
    if booking["status"] != "DEPOSIT_PENDING":
        raise invalid_state("Booking is not DEPOSIT_PENDING")

    # Clock must still be before scheduled_for (PRD §3.6).
    if not (clock.now() < parse_iso(booking["scheduled_for"])):
        raise invalid_state("Booking event time has passed")

    # Deposit must equal deposit_due_cents exactly (PRD §3.6).
    if amount_cents != booking["deposit_due_cents"]:
        raise ApiError(ERR_DEPOSIT_AMOUNT_MISMATCH, 422,
                       "amount_cents must equal deposit_due_cents")

    booking["deposit_paid_cents"] = amount_cents
    booking["status"] = "CONFIRMED"
    touch(booking)
    return success(serializers.party_booking(booking))


@bp.route("/party-bookings/<booking_id>/expire", methods=["POST"])
def expire_booking_endpoint(booking_id):
    caller = get_caller()
    require_roles(caller, {"StudioManager"})
    booking = get_booking(booking_id)

    # State: DEPOSIT_PENDING (PRD §3.6).
    if booking["status"] != "DEPOSIT_PENDING":
        raise invalid_state("Booking is not DEPOSIT_PENDING")
    # Requires clock at or past scheduled_for (PRD §3.6).
    if not (clock.now() >= parse_iso(booking["scheduled_for"])):
        raise invalid_state("Booking has not yet reached scheduled_for")

    booking["status"] = "EXPIRED"
    touch(booking)
    return success(serializers.party_booking(booking))


@bp.route("/party-bookings/<booking_id>/cancel", methods=["POST"])
def cancel_booking(booking_id):
    caller = get_caller()
    require_roles(caller, {"StudioManager"})
    booking = get_booking(booking_id)
    if booking["status"] != "DEPOSIT_PENDING":
        raise invalid_state("Booking is not DEPOSIT_PENDING")
    booking["status"] = "CANCELLED"
    touch(booking)
    return success(serializers.party_booking(booking))
