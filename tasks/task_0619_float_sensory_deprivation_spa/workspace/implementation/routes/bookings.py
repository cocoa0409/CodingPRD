"""Booking lifecycle — the cyclic core.

Create (deposit + provisional charge + conflict checks), confirm, reschedule,
check-in, complete (turnover cascade), no-show, cancel.
"""
from datetime import timedelta

from flask import Blueprint, request

import errors
import serializers
from clock import clock
from constants import (
    CHECKIN_LEAD_MINUTES,
    RESCHEDULE_CUTOFF_HOURS,
    CANCEL_CUTOFF_HOURS,
    NO_SHOW_GRACE_MINUTES,
    CURRENT_WAIVER_VERSION,
    NO_SHOW_SUSPEND_THRESHOLD,
)
from db import db, stamp_create, touch
from helpers import (
    get_json_body,
    require_fields,
    parse_datetime,
    parse_pagination,
    paginate,
)
from middleware import authenticate, require_role
from response import success
from services.ledger import add_credit_entry, add_payment, reconcile_gift_card_balance
from services.pricing import (
    deposit_for,
    provisional_charge,
    final_charge,
    credits_required,
)
from routes.tanks import start_sanitation_cycle, ACTIVE_BOOKING_STATES

bp = Blueprint("bookings", __name__)


def _window(start, session_minutes, turnover_buffer):
    """Return (occupancy_start, occupancy_end) = [start, end + buffer)."""
    end = start + timedelta(minutes=session_minutes)
    occ_end = end + timedelta(minutes=turnover_buffer)
    return start, occ_end, end


def _overlaps(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def _conflicts(tank, occ_start, occ_end, exclude_booking_id=None):
    """True if [occ_start, occ_end) collides with an active booking's span on the tank."""
    buffer = tank["turnover_buffer_minutes"]
    for b in db.bookings.values():
        if b["tank_id"] != tank["id"]:
            continue
        if exclude_booking_id is not None and b["id"] == exclude_booking_id:
            continue
        if b["status"] not in ACTIVE_BOOKING_STATES:
            continue
        b_start = b["start_utc"]
        b_occ_end = b["end_utc"] + timedelta(minutes=buffer)
        if _overlaps(occ_start, occ_end, b_start, b_occ_end):
            return True
    return False


@bp.route("/bookings", methods=["POST"])
def create_booking():
    principal = authenticate()
    require_role(principal, {"Admin", "FrontDesk", "Member"})
    body = get_json_body()
    require_fields(body, ["member_id", "tank_id", "session_minutes", "start_utc", "pay_source"])

    member_id = body["member_id"]
    # Member ownership: a Member may only book for their own member_id (§2.1).
    if principal.is_member() and member_id != principal.user_id:
        raise errors.forbidden()

    # Existence resolution left-to-right: member, tank, then optional FKs.
    member = db.members.get(member_id)
    if member is None:
        raise errors.not_found("Member not found.")
    tank = db.tanks.get(body["tank_id"])
    if tank is None:
        raise errors.not_found("Tank not found.")

    membership_id = body.get("membership_id")
    membership = None
    if membership_id is not None:
        membership = db.memberships.get(membership_id)
        if membership is None:
            raise errors.not_found("Membership not found.")

    gift_card_id = body.get("gift_card_id")
    gift_card = None
    if gift_card_id is not None:
        gift_card = db.gift_cards.get(gift_card_id)
        if gift_card is None:
            raise errors.not_found("Gift card not found.")

    # Well-formedness.
    session_minutes = body["session_minutes"]
    if session_minutes not in (60, 90):
        raise errors.invalid_request("session_minutes must be 60 or 90.")
    pay_source = body["pay_source"]
    if pay_source not in ("CREDIT", "GIFT_CARD", "CASH"):
        raise errors.invalid_request("pay_source must be CREDIT, GIFT_CARD, or CASH.")
    is_couples = body.get("is_couples", False)
    if not isinstance(is_couples, bool):
        raise errors.invalid_request("is_couples must be a boolean.")
    start = parse_datetime(body["start_utc"], "start_utc")

    # Referential combination rules -> ERR_TANK_KIND_MISMATCH.
    if is_couples and tank["capacity_kind"] != "DUAL":
        raise errors.tank_kind_mismatch("Couples booking requires a DUAL tank.")
    if pay_source == "GIFT_CARD" and gift_card_id is None:
        raise errors.tank_kind_mismatch("GIFT_CARD pay_source requires gift_card_id.")
    if pay_source == "CREDIT" and membership_id is None:
        raise errors.tank_kind_mismatch("CREDIT pay_source requires membership_id.")

    # Gift card must be ACTIVE.
    if pay_source == "GIFT_CARD" and gift_card["status"] != "ACTIVE":
        raise errors.gift_card_inactive()

    # Tank time conflict (occupancy span incl. turnover buffer).
    occ_start, occ_end, end = _window(start, session_minutes, tank["turnover_buffer_minutes"])
    if _conflicts(tank, occ_start, occ_end):
        raise errors.tank_time_conflict()

    # Pricing.
    plan = db.plans.get(membership["plan_id"]) if membership is not None else None
    deposit_cents = deposit_for(is_couples)
    if plan is not None:
        prov = provisional_charge(plan, session_minutes, is_couples, membership)
    else:
        # No membership/plan -> provisional charge cannot use a plan rate card.
        prov = 0

    instrument = "GIFT_CARD" if pay_source == "GIFT_CARD" else "CASH"

    record = {
        "member_id": member_id,
        "tank_id": body["tank_id"],
        "membership_id": membership_id,
        "session_minutes": session_minutes,
        "is_couples": is_couples,
        "start_utc": start,
        "end_utc": end,
        "status": "RESERVED",
        "pay_source": pay_source,
        "gift_card_id": gift_card_id,
        "deposit_cents": deposit_cents,
        "provisional_charge_cents": prov,
        "final_charge_cents": 0,
        "credits_consumed": 0,
    }
    stamp_create(record)
    db.bookings[record["id"]] = record

    # Deposit hold — instrument mirrors the booking; GIFT_CARD debits the card.
    add_payment("DEPOSIT_HOLD", instrument, deposit_cents,
                booking_id=record["id"],
                gift_card_id=gift_card_id if instrument == "GIFT_CARD" else None)

    return success(serializers.booking_out(record), status=201)


@bp.route("/bookings/<bid>", methods=["GET"])
def get_booking(bid):
    principal = authenticate()
    require_role(principal, {"Admin", "FrontDesk", "Member"})
    b = db.bookings.get(bid)
    if b is None:
        raise errors.not_found("Booking not found.")
    if principal.is_member() and b["member_id"] != principal.user_id:
        raise errors.forbidden()
    return success(serializers.booking_out(b), status=200)


@bp.route("/bookings", methods=["GET"])
def list_bookings():
    principal = authenticate()
    require_role(principal, {"Admin", "FrontDesk", "Member"})
    limit, offset = parse_pagination()
    records = list(db.bookings.values())
    for key in ("member_id", "tank_id", "membership_id", "gift_card_id", "status"):
        val = request.args.get(key)
        if val is not None:
            records = [r for r in records if r[key] == val]
    if principal.is_member():
        records = [r for r in records if r["member_id"] == principal.user_id]
    page, meta = paginate(records, limit, offset)
    return success([serializers.booking_out(r) for r in page], status=200, pagination=meta)


def _load_owned_booking(principal, bid):
    b = db.bookings.get(bid)
    if b is None:
        raise errors.not_found("Booking not found.")
    if principal.is_member() and b["member_id"] != principal.user_id:
        raise errors.forbidden()
    return b


@bp.route("/bookings/<bid>/confirm", methods=["POST"])
def confirm_booking(bid):
    principal = authenticate()
    require_role(principal, {"Admin", "FrontDesk", "Member"})
    b = _load_owned_booking(principal, bid)
    if b["status"] not in ("RESERVED", "RESCHEDULED"):
        raise errors.invalid_state("Booking is not RESERVED or RESCHEDULED.")
    # Eligibility gate applies to the RESERVED->CONFIRMED first entry only; the
    # RESCHEDULED->CONFIRMED re-confirm carries no eligibility preconditions
    # (SCAFFOLD §1.2 Booking transitions).
    if b["status"] == "RESERVED":
        member = db.members.get(b["member_id"])
        if (not member["orientation_completed"]
                or member["waiver_signed_version"] < CURRENT_WAIVER_VERSION
                or member["status"] != "ACTIVE"):
            raise errors.member_not_eligible()
    b["status"] = "CONFIRMED"
    touch(b)
    return success(serializers.booking_out(b), status=200)


@bp.route("/bookings/<bid>/reschedule", methods=["POST"])
def reschedule_booking(bid):
    principal = authenticate()
    require_role(principal, {"Admin", "FrontDesk", "Member"})
    b = _load_owned_booking(principal, bid)
    body = get_json_body()
    require_fields(body, ["new_start_utc"])
    if b["status"] != "CONFIRMED":
        raise errors.invalid_state("Booking is not CONFIRMED.")
    new_start = parse_datetime(body["new_start_utc"], "new_start_utc")
    now = clock.now()
    # Reschedule allowed only at or before start_utc - RESCHEDULE_CUTOFF_HOURS.
    cutoff = b["start_utc"] - timedelta(hours=RESCHEDULE_CUTOFF_HOURS)
    if now > cutoff:
        raise errors.timing_not_allowed("Past the reschedule cutoff.")
    tank = db.tanks.get(b["tank_id"])
    occ_start, occ_end, new_end = _window(new_start, b["session_minutes"],
                                          tank["turnover_buffer_minutes"])
    if _conflicts(tank, occ_start, occ_end, exclude_booking_id=b["id"]):
        raise errors.tank_time_conflict()
    b["start_utc"] = new_start
    b["end_utc"] = new_end
    b["status"] = "RESCHEDULED"
    touch(b)
    return success(serializers.booking_out(b), status=200)


@bp.route("/bookings/<bid>/check-in", methods=["POST"])
def check_in_booking(bid):
    principal = authenticate()
    require_role(principal, {"Admin", "FrontDesk"})
    b = db.bookings.get(bid)
    if b is None:
        raise errors.not_found("Booking not found.")
    if b["status"] != "CONFIRMED":
        raise errors.invalid_state("Booking is not CONFIRMED.")
    now = clock.now()
    # Not too early: now >= start - CHECKIN_LEAD_MINUTES.
    earliest = b["start_utc"] - timedelta(minutes=CHECKIN_LEAD_MINUTES)
    if now < earliest:
        raise errors.timing_not_allowed("Check-in is too early.")
    tank = db.tanks.get(b["tank_id"])
    # Tank must be CLEAN + IN_SERVICE.
    if tank["operational_status"] != "IN_SERVICE" or tank["sanitation_status"] != "CLEAN":
        raise errors.tank_unavailable()

    if b["pay_source"] == "CREDIT":
        membership = db.memberships.get(b["membership_id"])
        need = credits_required(b["is_couples"])
        # Per PRD §3.6 a credit check-in requires an ACTIVE membership holding
        # enough credits; a non-ACTIVE membership has no usable credits.
        if (membership is None or membership["status"] != "ACTIVE"
                or membership["credit_balance"] < need):
            raise errors.insufficient_funds()
        add_credit_entry(membership, "CONSUME", -need, booking_id=b["id"])
        b["credits_consumed"] = need
    elif b["pay_source"] == "GIFT_CARD":
        card = db.gift_cards.get(b["gift_card_id"])
        if card["remaining_balance_cents"] < b["provisional_charge_cents"]:
            raise errors.insufficient_funds()
        add_payment("SESSION_CHARGE", "GIFT_CARD", b["provisional_charge_cents"],
                    booking_id=b["id"], gift_card_id=card["id"])
    # CASH: nothing charged at check-in.

    b["status"] = "CHECKED_IN"
    touch(b)
    return success(serializers.booking_out(b), status=200)


@bp.route("/bookings/<bid>/complete", methods=["POST"])
def complete_booking(bid):
    principal = authenticate()
    require_role(principal, {"Admin", "FrontDesk"})
    b = db.bookings.get(bid)
    if b is None:
        raise errors.not_found("Booking not found.")
    if b["status"] != "CHECKED_IN":
        raise errors.invalid_state("Booking is not CHECKED_IN.")
    tank = db.tanks.get(b["tank_id"])

    # Final charge from realized minutes (default = booked minutes).
    membership = db.memberships.get(b["membership_id"]) if b["membership_id"] else None
    plan = db.plans.get(membership["plan_id"]) if membership is not None else None
    if plan is not None:
        b["final_charge_cents"] = final_charge(plan, b["session_minutes"], b["is_couples"], membership)
    else:
        b["final_charge_cents"] = 0

    b["status"] = "COMPLETED"
    touch(b)

    # CASCADE L1+L2: create TURNOVER cycle -> tank CLEAN->IN_CYCLE.
    cycle = start_sanitation_cycle(
        tank, kind="TURNOVER", booking_id=b["id"],
        duration_minutes=tank["turnover_buffer_minutes"],
    )

    # CASCADE L3: auto-cancel every RESERVED booking on this tank whose
    # start_utc < new cycle ends_utc; refund their deposits.
    for other in list(db.bookings.values()):
        if other["id"] == b["id"]:
            continue
        if other["tank_id"] != tank["id"]:
            continue
        if other["status"] != "RESERVED":
            continue
        if other["start_utc"] < cycle["ends_utc"]:
            other["status"] = "CANCELLED"
            touch(other)
            _refund_deposit(other)

    # Release this booking's own deposit.
    _refund_deposit(b)

    return success(serializers.booking_out(b), status=200)


@bp.route("/bookings/<bid>/no-show", methods=["POST"])
def no_show_booking(bid):
    principal = authenticate()
    require_role(principal, {"Admin", "FrontDesk"})
    b = db.bookings.get(bid)
    if b is None:
        raise errors.not_found("Booking not found.")
    if b["status"] != "CONFIRMED":
        raise errors.invalid_state("Booking is not CONFIRMED.")
    now = clock.now()
    # Allowed only at or after start + NO_SHOW_GRACE_MINUTES.
    threshold = b["start_utc"] + timedelta(minutes=NO_SHOW_GRACE_MINUTES)
    if now < threshold:
        raise errors.timing_not_allowed("No-show grace period has not elapsed.")
    b["status"] = "NO_SHOW"
    touch(b)
    # Forfeit deposit.
    instrument = "GIFT_CARD" if b["pay_source"] == "GIFT_CARD" else "CASH"
    add_payment("NO_SHOW_FEE", instrument, b["deposit_cents"],
                booking_id=b["id"],
                gift_card_id=b["gift_card_id"] if instrument == "GIFT_CARD" else None)
    # Strike the member.
    member = db.members.get(b["member_id"])
    if member is not None:
        member["no_show_strikes"] = member["no_show_strikes"] + 1
        if member["no_show_strikes"] >= NO_SHOW_SUSPEND_THRESHOLD:
            member["status"] = "SUSPENDED"
        touch(member)
    return success(serializers.booking_out(b), status=200)


@bp.route("/bookings/<bid>/cancel", methods=["POST"])
def cancel_booking(bid):
    principal = authenticate()
    require_role(principal, {"Admin", "FrontDesk", "Member"})
    b = _load_owned_booking(principal, bid)
    if b["status"] not in ("RESERVED", "CONFIRMED", "RESCHEDULED"):
        raise errors.invalid_state("Booking cannot be cancelled from its current state.")
    now = clock.now()
    b["status"] = "CANCELLED"
    touch(b)
    # Timely (<= start - CANCEL_CUTOFF_HOURS): refund deposit. Late: forfeit.
    cutoff = b["start_utc"] - timedelta(hours=CANCEL_CUTOFF_HOURS)
    instrument = "GIFT_CARD" if b["pay_source"] == "GIFT_CARD" else "CASH"
    gc = b["gift_card_id"] if instrument == "GIFT_CARD" else None
    if now <= cutoff:
        add_payment("DEPOSIT_REFUND", instrument, -b["deposit_cents"],
                    booking_id=b["id"], gift_card_id=gc)
    else:
        add_payment("LATE_FEE", instrument, b["deposit_cents"],
                    booking_id=b["id"], gift_card_id=gc)
    return success(serializers.booking_out(b), status=200)


def _refund_deposit(b):
    """Record a DEPOSIT_REFUND for a booking on its funding instrument."""
    instrument = "GIFT_CARD" if b["pay_source"] == "GIFT_CARD" else "CASH"
    gc = b["gift_card_id"] if instrument == "GIFT_CARD" else None
    add_payment("DEPOSIT_REFUND", instrument, -b["deposit_cents"],
                booking_id=b["id"], gift_card_id=gc)
