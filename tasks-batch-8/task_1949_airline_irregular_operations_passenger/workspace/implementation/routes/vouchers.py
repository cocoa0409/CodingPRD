"""Voucher issuance, reads, redeem, void."""

from datetime import datetime, timedelta

from flask import Blueprint, request

import errors
from db import db, now
from middleware import authenticate, check_booking_ownership, require_role
from response import success_list, success_object
from serializers import serialize_voucher
from services.core import post_cost_entry, stamp_new, touch
from services.selector import (
    BOOKING_VOUCHER_CAP_CENTS,
    HOTEL_NIGHT_CAP_CENTS,
    HOTEL_WINDOW_THRESHOLD_HOURS,
    MAX_HOTEL_NIGHTS,
    MEAL_RATE_CENTS,
    MEAL_WINDOW_HOURS,
    TRANSPORT_FLAT_CENTS,
    disruption_window_hours,
)
from validators import (
    get_json_body,
    get_json_body_optional,
    opt_query_enum,
    pagination_params,
    req_date,
    req_int,
)

bp = Blueprint("vouchers", __name__)

VOUCHER_TYPES = {"HOTEL", "MEAL", "TRANSPORT"}
VOUCHER_STATUSES = {"ISSUED", "REDEEMED", "VOIDED", "EXPIRED"}
VOUCHER_READ_ROLES = ["ReaccommodationAgent", "FinanceProcessor", "DutyManager", "Passenger"]


def _booking_event_id(booking):
    """The disruption_event_id copied from the booking's reaccommodation case."""
    for case in db.reaccommodation_cases.values():
        if case["booking_id"] == booking["id"] and case["disruption_event_id"]:
            return case["disruption_event_id"]
    return None


def _committed_case(booking):
    for case in db.reaccommodation_cases.values():
        if case["booking_id"] == booking["id"] and case["case_status"] == "COMMITTED":
            return case
    return None


def _nights_covered(check_in_date_str, nights):
    d = datetime.strptime(check_in_date_str, "%Y-%m-%d").date()
    return {d + timedelta(days=i) for i in range(nights)}


@bp.post("/irops/bookings/<bid>/vouchers")
def issue_voucher(bid):
    caller = authenticate()
    require_role(caller, ["ReaccommodationAgent"])
    body = get_json_body()
    voucher_type = body.get("voucher_type")
    if not isinstance(voucher_type, str):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "voucher_type must be a string")
    if voucher_type not in VOUCHER_TYPES:
        errors.raise_error(errors.ERR_INVALID_ENUM,
                           "voucher_type value %r outside declared enum domain" % voucher_type)
    check_in_date = None
    if voucher_type == "HOTEL":
        check_in_date = req_date(body, "check_in_date")
    elif "check_in_date" in body and body["check_in_date"] is not None:
        if not isinstance(body["check_in_date"], str):
            errors.raise_error(errors.ERR_INVALID_REQUEST, "check_in_date must be a string")
        check_in_date = body["check_in_date"]
    b = db.bookings.get(bid)
    if b is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "Booking not found")
    event_id = _booking_event_id(b)
    event = db.disruption_events.get(event_id) if event_id else None
    # gate 1: event must be RECOVERY
    if event is None or event["event_status"] != "RECOVERY":
        errors.raise_error(errors.ERR_EVENT_INVALID_STATE,
                           "Voucher issuance requires the event in RECOVERY")
    # gate 2: booking must be DISRUPTED or REBOOKED
    if b["booking_status"] not in ("DISRUPTED", "REBOOKED"):
        errors.raise_error(errors.ERR_BOOKING_NOT_DISRUPTED,
                           "Voucher issuance requires booking DISRUPTED or REBOOKED")
    # gate 3 (HOTEL): controllable event + committed case + entitlement window
    window_hours = None
    if voucher_type in ("HOTEL", "MEAL"):
        committed = _committed_case(b)
        if not event["is_controllable"] or committed is None:
            errors.raise_error(errors.ERR_VOUCHER_RULE_NOT_MET,
                               "%s requires a committed case on a controllable event" % voucher_type)
        window_hours = disruption_window_hours(b)
        if window_hours is None:
            errors.raise_error(errors.ERR_VOUCHER_RULE_NOT_MET,
                               "Disruption window cannot be determined")
    # compute entitlement
    nights = 0
    meals_count = 0
    if voucher_type == "HOTEL":
        if window_hours < HOTEL_WINDOW_THRESHOLD_HOURS:
            errors.raise_error(errors.ERR_VOUCHER_RULE_NOT_MET,
                               "HOTEL requires disruption_window_hours >= 8")
        import math
        nights = min(MAX_HOTEL_NIGHTS, max(1, math.ceil(window_hours / 24)))
        face = nights * HOTEL_NIGHT_CAP_CENTS
    elif voucher_type == "MEAL":
        meals_count = min(3, window_hours // MEAL_WINDOW_HOURS)
        if meals_count < 1:
            errors.raise_error(errors.ERR_VOUCHER_RULE_NOT_MET,
                               "MEAL requires meals_count >= 1")
        face = meals_count * MEAL_RATE_CENTS
    else:  # TRANSPORT
        face = TRANSPORT_FLAT_CENTS
    # gate (HOTEL night overlap) — priority 25: before entitlement? PRD pins order:
    # event state, booking state, hotel night overlap, entitlement thresholds,
    # booking cap, event cap. Entitlement was needed to compute nights, so the
    # overlap check runs here with nights known, before caps.
    if voucher_type == "HOTEL":
        new_nights = _nights_covered(check_in_date, nights)
        for v in db.vouchers.values():
            if v["voucher_type"] != "HOTEL" or v["voucher_status"] not in ("ISSUED", "REDEEMED"):
                continue
            other_booking = db.bookings.get(v["booking_id"])
            if other_booking is None or other_booking["passenger_id"] != b["passenger_id"]:
                continue
            if v["check_in_date"] is None:
                continue
            existing = _nights_covered(v["check_in_date"], v["nights"])
            if new_nights & existing:
                errors.raise_error(errors.ERR_HOTEL_NIGHT_OVERLAP,
                                   "Passenger already holds a hotel voucher covering these nights")
    # booking fiscal cap
    booking_face = sum(v["face_value_cents"] for v in db.vouchers.values()
                       if v["booking_id"] == b["id"] and v["voucher_status"] in ("ISSUED", "REDEEMED"))
    if booking_face + face > BOOKING_VOUCHER_CAP_CENTS:
        errors.raise_error(errors.ERR_VOUCHER_CAP_EXCEEDED,
                           "Per-booking voucher face total would exceed the cap")
    # event fiscal cap
    if event["accrual_total_cents"] + face > event["cost_cap_cents"]:
        errors.raise_error(errors.ERR_EVENT_COST_CAP_EXCEEDED,
                           "Event accrual total plus new face would exceed cost_cap_cents")
    # valid_through
    issue_date = now().date()
    if voucher_type == "HOTEL":
        vt = (datetime.strptime(check_in_date, "%Y-%m-%d").date() + timedelta(days=nights)).isoformat()
    elif voucher_type == "MEAL":
        vt = (issue_date + timedelta(days=1)).isoformat()
    else:
        vt = (issue_date + timedelta(days=2)).isoformat()
    v = stamp_new({
        "booking_id": b["id"],
        "disruption_event_id": event_id,
        "voucher_type": voucher_type,
        "check_in_date": check_in_date,
        "nights": nights,
        "meals_count": meals_count,
        "face_value_cents": face,
        "valid_through": vt,
        "voucher_status": "ISSUED",
        "redeemed_amount_cents": None,
    })
    db.vouchers[v["id"]] = v
    post_cost_entry(event_id, "VOUCHER", v["id"], "ACCRUAL", face, note="voucher issued")
    return success_object(serialize_voucher(v), 201)


@bp.get("/irops/vouchers/<vid>")
def get_voucher(vid):
    caller = authenticate()
    require_role(caller, VOUCHER_READ_ROLES)
    v = db.vouchers.get(vid)
    if v is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "Voucher not found")
    if caller.is_passenger:
        b = db.bookings.get(v["booking_id"])
        if b is not None:
            check_booking_ownership(caller, b)
    return success_object(serialize_voucher(v), 200)


@bp.get("/irops/vouchers")
def list_vouchers():
    caller = authenticate()
    require_role(caller, VOUCHER_READ_ROLES)
    booking_id = request.args.get("booking_id")
    event_id = request.args.get("disruption_event_id")
    status = opt_query_enum("voucher_status", VOUCHER_STATUSES)
    limit, offset = pagination_params()
    items = sorted(db.vouchers.values(), key=lambda v: v["created_at"])
    if caller.is_passenger:
        items = [v for v in items
                 if db.bookings.get(v["booking_id"]) is not None
                 and db.bookings[v["booking_id"]]["passenger_id"] == caller.user_id]
    if booking_id is not None:
        items = [v for v in items if v["booking_id"] == booking_id]
    if event_id is not None:
        items = [v for v in items if v["disruption_event_id"] == event_id]
    if status is not None:
        items = [v for v in items if v["voucher_status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_voucher(v) for v in page], limit, offset, total)


@bp.post("/irops/vouchers/<vid>/redeem")
def redeem_voucher(vid):
    caller = authenticate()
    require_role(caller, ["FinanceProcessor"])
    body = get_json_body()
    amount = req_int(body, "actual_amount_cents")
    if amount < 0:
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "actual_amount_cents must be >= 0")
    v = db.vouchers.get(vid)
    if v is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "Voucher not found")
    if v["voucher_status"] != "ISSUED":
        errors.raise_error(errors.ERR_VOUCHER_NOT_OPEN,
                           "Voucher is not ISSUED")
    v["redeemed_amount_cents"] = amount
    v["voucher_status"] = "REDEEMED"
    touch(v)
    post_cost_entry(v["disruption_event_id"], "VOUCHER", v["id"], "SETTLEMENT",
                    amount, note="voucher redeemed")
    return success_object(serialize_voucher(v), 200)


@bp.post("/irops/vouchers/<vid>/void")
def void_voucher(vid):
    caller = authenticate()
    require_role(caller, ["FinanceProcessor"])
    get_json_body_optional()
    v = db.vouchers.get(vid)
    if v is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "Voucher not found")
    if v["voucher_status"] != "ISSUED":
        errors.raise_error(errors.ERR_VOUCHER_NOT_OPEN,
                           "Voucher is not ISSUED")
    v["voucher_status"] = "VOIDED"
    touch(v)
    post_cost_entry(v["disruption_event_id"], "VOUCHER", v["id"], "REVERSAL",
                    -v["face_value_cents"], note="voucher voided")
    return success_object(serialize_voucher(v), 200)
