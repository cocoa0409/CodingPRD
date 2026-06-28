"""Booking endpoints, confirm/complete/cancel lifecycle (PRD §3.6, §3.7)."""
from flask import Blueprint, request

from db import db, lock
from errors import ApiError
from middleware import get_identity, require_role
from response import object_response, array_response
from services.common import (
    mint_common,
    touch,
    public,
    get_json_body,
    require_str,
    require_int,
    lookup,
    paginate,
)
from services.calc import gross_fee_cents, commission_cents
from services.reconcile import reconcile_agency, reconcile_talent_booked
from timeutil import require_dt, to_date, inclusive_day_span, now_dt

bp = Blueprint("bookings", __name__)

ALL_ROLES = {"Agent", "CastingDirector", "Talent"}


@bp.route("/bookings", methods=["POST"])
def create_booking():
    _, role = get_identity()
    require_role(role, {"Agent"})
    body = get_json_body()
    deal_memo_id = require_str(body, "deal_memo_id")
    talent_id = require_str(body, "talent_id")
    casting_call_id = require_str(body, "casting_call_id")
    availability_hold_id = require_str(body, "availability_hold_id")
    require_str(body, "start_date")
    require_str(body, "end_date")
    expected_talent_version = require_int(body, "expected_talent_version")
    start_date = require_dt(body["start_date"])
    end_date = require_dt(body["end_date"])
    with lock:
        # Existence, declaration order (priority 3).
        lookup("DealMemo", deal_memo_id)
        talent = lookup("Talent", talent_id)
        lookup("CastingCall", casting_call_id)
        lookup("AvailabilityHold", availability_hold_id)

        # OCC on Talent.version (priority 5).
        if expected_talent_version != talent["version"]:
            raise ApiError("ERR_STALE_TALENT_VERSION")

        # Date ordering (priority 11).
        if to_date(end_date) < to_date(start_date):
            raise ApiError("ERR_INVALID_DATE_RANGE")

        record = mint_common({
            "deal_memo_id": deal_memo_id,
            "talent_id": talent_id,
            "casting_call_id": casting_call_id,
            "availability_hold_id": availability_hold_id,
            "start_date": body["start_date"],
            "end_date": body["end_date"],
            "agreed_day_rate_cents": 0,
            "usage_term_months": 0,
            "gross_fee_cents": 0,
            "provisional_commission_cents": 0,
            "final_commission_cents": None,
            "booking_status": "PENDING",
            "payment_status": "UNPAID",
            # internal helpers
            "_agency_id": talent["agency_id"],
            "_day_span": inclusive_day_span(start_date, end_date),
        })
        db.bookings[record["id"]] = record
        return object_response(public(record), status=201)


@bp.route("/bookings", methods=["GET"])
def list_bookings():
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    with lock:
        items = list(db.bookings.values())
        for field in ("talent_id", "casting_call_id", "deal_memo_id", "availability_hold_id", "booking_status"):
            val = request.args.get(field)
            if val is not None:
                items = [b for b in items if b[field] == val]
        page, limit, offset, total = paginate(items)
        return array_response(page, limit, offset, total)


@bp.route("/bookings/<booking_id>", methods=["GET"])
def get_booking(booking_id):
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    with lock:
        record = lookup("Booking", booking_id)
        return object_response(public(record), status=200)


@bp.route("/bookings/<booking_id>/confirm", methods=["POST"])
def confirm_booking(booking_id):
    _, role = get_identity()
    require_role(role, {"Agent"})
    with lock:
        booking = lookup("Booking", booking_id)
        if booking["booking_status"] != "PENDING":
            raise ApiError("ERR_INVALID_STATE")

        # Cross-entity gates (priority 7), scaffold order.
        deal = lookup("DealMemo", booking["deal_memo_id"])
        if deal["status"] != "ACCEPTED":
            raise ApiError("ERR_DEAL_NOT_ACCEPTED")
        hold = lookup("AvailabilityHold", booking["availability_hold_id"])
        if hold["hold_kind"] != "CONFIRMED_BOOKING" or hold["status"] != "ACTIVE":
            raise ApiError("ERR_HOLD_NOT_ACTIVE")
        talent = lookup("Talent", booking["talent_id"])
        if talent["status"] != "ROSTERED":
            raise ApiError("ERR_TALENT_NOT_ROSTERED")

        agency = lookup("Agency", talent["agency_id"])

        # Side effects.
        booking["booking_status"] = "CONFIRMED"
        booking["agreed_day_rate_cents"] = deal["current_day_rate_cents"]
        booking["usage_term_months"] = deal["usage_term_months"]
        day_span = booking["_day_span"]
        gross = gross_fee_cents(booking["agreed_day_rate_cents"], day_span)
        booking["gross_fee_cents"] = gross
        provisional = commission_cents(gross, agency["commission_rate_bps"])
        booking["provisional_commission_cents"] = provisional
        touch(booking)

        # Create HELD CommissionEntry.
        entry = mint_common({
            "agency_id": agency["id"],
            "booking_id": booking["id"],
            "held_cents": provisional,
            "earned_cents": 0,
            "status": "HELD",
        })
        db.commission_entries[entry["id"]] = entry

        # Reconcile escrow + booked days (recomputed from source of truth).
        reconcile_agency(agency)
        reconcile_talent_booked(talent)

        # Casting call OPEN -> FILLED.
        call = lookup("CastingCall", booking["casting_call_id"])
        if call["status"] == "OPEN":
            call["status"] = "FILLED"
            touch(call)

        return object_response(public(booking), status=200)


@bp.route("/bookings/<booking_id>/complete", methods=["POST"])
def complete_booking(booking_id):
    _, role = get_identity()
    require_role(role, {"Agent"})
    with lock:
        booking = lookup("Booking", booking_id)
        if booking["booking_status"] != "CONFIRMED":
            raise ApiError("ERR_INVALID_STATE")
        if now_dt(db) < require_dt(booking["end_date"]):
            raise ApiError("ERR_BOOKING_NOT_ENDED")
        booking["booking_status"] = "COMPLETED"
        touch(booking)
        return object_response(public(booking), status=200)


@bp.route("/bookings/<booking_id>/cancel", methods=["POST"])
def cancel_booking(booking_id):
    _, role = get_identity()
    require_role(role, {"Agent"})
    with lock:
        booking = lookup("Booking", booking_id)
        status = booking["booking_status"]
        if status not in ("PENDING", "CONFIRMED"):
            raise ApiError("ERR_INVALID_STATE")
        if status == "CONFIRMED" and booking["payment_status"] == "PAID":
            raise ApiError("ERR_BOOKING_ALREADY_PAID")

        was_confirmed = status == "CONFIRMED"
        booking["booking_status"] = "CANCELLED"
        touch(booking)

        if was_confirmed:
            # Link 2: availability hold ACTIVE -> RELEASED.
            hold = db.availability_holds.get(booking["availability_hold_id"])
            if hold is not None and hold["status"] == "ACTIVE":
                hold["status"] = "RELEASED"
                touch(hold)
            # Link 3: deal memo ACCEPTED -> VOIDED.
            deal = db.deal_memos.get(booking["deal_memo_id"])
            if deal is not None and deal["status"] == "ACCEPTED":
                deal["status"] = "VOIDED"
                touch(deal)
            # Link 4: commission entry HELD -> REVERSED, held_cents -> 0.
            for entry in db.commission_entries.values():
                if entry["booking_id"] == booking["id"] and entry["status"] == "HELD":
                    entry["status"] = "REVERSED"
                    entry["held_cents"] = 0
                    touch(entry)
            # Reconcile escrow + booked days downward.
            agency = db.agencies.get(booking["_agency_id"])
            if agency is not None:
                reconcile_agency(agency)
            talent = db.talents.get(booking["talent_id"])
            if talent is not None:
                reconcile_talent_booked(talent)

        return object_response(public(booking), status=200)
