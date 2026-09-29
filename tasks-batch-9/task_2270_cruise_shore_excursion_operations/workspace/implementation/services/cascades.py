"""Cross-entity cascades: closure, cancellation, suspension, closure of a call."""

from db import db
from errors import fail
from services.allocation import bookings_of, recompute_seats, return_seats
from services.alternatives import select_alternative
from services.commission import (final_line_cents, operator_of_departure,
                                 recompute_draft_statements)
from services.ledger import (guest_cancellation_settlement, line_cancellation_settlement,
                             no_show_retention, return_guarantee_settlement,
                             void_authorization)
from services.safety import compute_safety_score
from services.timing import recompute_projections
from util import apply_bps, minutes_between

SALES_CUTOFF_MINUTES = 60
CHECKIN_OPEN_MINUTES = 45
CHECKIN_GRACE_MINUTES = 10
SAFETY_SCORE_FLOOR = 60
RELIABILITY_STRIKE_SUSPEND_THRESHOLD = 3
CANCELLABLE_DEPARTURE_STATUSES = ("SCHEDULED", "SELLING", "CLOSED")
LIVE_FULFILLMENT = ("BOOKED", "TICKETED", "CHECKED_IN")


# --------------------------------------------------------------------------
# ordered collections
# --------------------------------------------------------------------------

def _ordered(rows):
    rows = list(rows)
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


def departures_of_call(port_call_id):
    return _ordered(d for d in db.departures.values() if d["port_call_id"] == port_call_id)


def departures_of_excursion(excursion_id):
    return _ordered(d for d in db.departures.values() if d["excursion_id"] == excursion_id)


def excursions_of_operator(operator_id):
    return _ordered(e for e in db.excursions.values() if e["operator_id"] == operator_id)


def operator_for_departure(departure):
    operator_id = operator_of_departure(departure)
    return db.operators.get(operator_id) if operator_id else None


def commission_rate_for_departure(departure):
    operator = operator_for_departure(departure)
    return operator["commission_rate_bps"] if operator else 0


# --------------------------------------------------------------------------
# departure sales closure
# --------------------------------------------------------------------------

def close_departure_sales(departure):
    """SELLING -> CLOSED; only never-charged bookings are cancelled."""
    departure["status"] = "CLOSED"
    for booking in bookings_of(departure["id"]):
        if booking["fulfillment_status"] != "BOOKED":
            continue
        booking["fulfillment_status"] = "CANCELLED_BY_LINE"
        if booking["financial_status"] == "AUTHORIZED":
            void_authorization(booking, "LINE_CANCELLED_OPERATIONAL")
        db.touch(booking)
        return_seats(departure, booking)
    recompute_seats(departure)
    db.touch(departure)
    return departure


def materialize_departure(departure):
    """Recompute projections and land the clock-driven sales closure."""
    recompute_projections(departure)
    if departure["status"] == "SELLING":
        if minutes_between(db.now(), departure["meeting_time_utc"]) <= SALES_CUTOFF_MINUTES:
            close_departure_sales(departure)
    recompute_seats(departure)
    return departure


def start_selling(departure):
    """SCHEDULED -> SELLING, freezing the return guarantee once and for all."""
    recompute_projections(departure)
    excursion = db.excursions.get(departure["excursion_id"])
    guaranteed = bool(excursion and excursion.get("return_guarantee"))
    departure["status"] = "SELLING"
    departure["return_guarantee_eligible"] = bool(
        guaranteed and departure["timing_risk_band_scheduled"] != "RED")
    recompute_seats(departure)
    db.touch(departure)
    return departure


# --------------------------------------------------------------------------
# departure cancellation (fork-join on cause)
# --------------------------------------------------------------------------

def cancel_departure(departure, cause, offer_alternative=False, charge_strike=True):
    basis = "LINE_CANCELLED_WEATHER" if cause == "WEATHER" else "LINE_CANCELLED_OPERATIONAL"
    bookings = bookings_of(departure["id"])
    live = [b for b in bookings if b["fulfillment_status"] in LIVE_FULFILLMENT]

    # Resolve every alternative before mutating anything: the cancellation is atomic.
    offers = {}
    if offer_alternative:
        for booking in live:
            alternative = select_alternative(booking, departure)
            if alternative is None:
                fail("ERR_NO_ALTERNATIVE_AVAILABLE",
                     "no sellable alternative departure exists for this booking")
            offers[booking["id"]] = alternative["id"]

    departure["status"] = "CANCELLED_WEATHER" if cause == "WEATHER" else "CANCELLED_OPERATIONAL"
    departure["cancellation_cause"] = cause

    # the wave keeps the assignment on the row but gives its counters back
    wave_id = departure.get("tender_wave_id")
    if wave_id:
        wave = db.tender_waves.get(wave_id)
        if wave is not None:
            wave["assigned_guest_count"] = max(0, wave["assigned_guest_count"] - departure["total_capacity"])
            wave["assigned_departure_count"] = max(0, wave["assigned_departure_count"] - 1)
            db.touch(wave)

    forgone_gross = 0
    for booking in bookings:
        fulfillment = booking["fulfillment_status"]
        financial = booking["financial_status"]
        if fulfillment in LIVE_FULFILLMENT:
            booking["fulfillment_status"] = "CANCELLED_BY_LINE"
            if financial in ("CHARGED", "PARTIALLY_REFUNDED"):
                line_cancellation_settlement(booking, basis, cause == "OPERATIONAL")
            elif financial == "AUTHORIZED":
                void_authorization(booking, basis)
            booking["commission_accrued_cents"] = 0
            forgone_gross += booking["quoted_total_cents"]
            if booking["id"] in offers:
                booking["alternative_departure_id"] = offers[booking["id"]]
                booking["alternative_offer_status"] = "OFFERED"
            db.touch(booking)
            return_seats(departure, booking)
        elif fulfillment == "CANCELLED_BY_GUEST" and financial == "PARTIALLY_REFUNDED":
            # the guest had already walked away: top the refund up, but no goodwill
            line_cancellation_settlement(booking, basis, False)
            booking["commission_accrued_cents"] = 0
            db.touch(booking)

    departure["forgone_gross_ticket_cents"] = forgone_gross
    recompute_seats(departure)
    db.touch(departure)

    operator = operator_for_departure(departure)
    if cause == "OPERATIONAL" and operator is not None and charge_strike:
        operator["reliability_strikes"] = operator["reliability_strikes"] + 1
        db.touch(operator)
        if (operator["reliability_strikes"] >= RELIABILITY_STRIKE_SUSPEND_THRESHOLD
                and operator["vetting_status"] == "APPROVED"):
            suspend_operator(operator)

    if operator is not None:
        recompute_draft_statements(operator["id"], departure["port_call_id"])
    return departure


# --------------------------------------------------------------------------
# catalog withdrawal and the four-hop operator suspension
# --------------------------------------------------------------------------

def withdraw_excursion(excursion, charge_strike=True):
    excursion["catalog_status"] = "WITHDRAWN"
    db.touch(excursion)
    for departure in departures_of_excursion(excursion["id"]):
        if departure["status"] in CANCELLABLE_DEPARTURE_STATUSES:
            cancel_departure(departure, "OPERATIONAL", False, charge_strike=charge_strike)
    return excursion


def suspend_operator(operator):
    """Hop 1 operator, hop 2 catalog, hop 3 schedule, hop 4 guests."""
    if operator.get("_suspending"):
        return operator
    operator["_suspending"] = True
    try:
        operator["vetting_status"] = "SUSPENDED"
        db.touch(operator)
        for excursion in excursions_of_operator(operator["id"]):
            if excursion["catalog_status"] == "PUBLISHED":
                withdraw_excursion(excursion, charge_strike=False)
    finally:
        operator.pop("_suspending", None)
    return operator


def recompute_operator_score(operator, allow_auto_suspend=False):
    operator["safety_score"] = compute_safety_score(operator)
    if (allow_auto_suspend and operator["safety_score"] < SAFETY_SCORE_FLOOR
            and operator["vetting_status"] == "APPROVED"):
        suspend_operator(operator)
    return operator


# --------------------------------------------------------------------------
# booking level helpers
# --------------------------------------------------------------------------

def mark_no_show(booking, departure):
    """TICKETED -> NO_SHOW with retention and the no-show commission floor."""
    booking["fulfillment_status"] = "NO_SHOW"
    if booking["financial_status"] == "CHARGED":
        no_show_retention(booking)
    booking["commission_accrued_cents"] = final_line_cents(
        booking, commission_rate_for_departure(departure))
    return booking


def cancel_booking_by_guest(booking, departure, reason_code=None):
    fulfillment = booking["fulfillment_status"]
    booking["fulfillment_status"] = "CANCELLED_BY_GUEST"
    if fulfillment == "BOOKED":
        void_authorization(booking, "GUEST_INITIATED", reason_code)
    else:
        guest_cancellation_settlement(booking, departure, reason_code)
        rate = commission_rate_for_departure(departure)
        basis = max(0, booking["quoted_total_cents"] - booking["refunded_cents"])
        booking["commission_accrued_cents"] = apply_bps(basis, rate)
    db.touch(booking)
    return_seats(departure, booking)
    db.touch(departure)
    return booking


# --------------------------------------------------------------------------
# departure operations
# --------------------------------------------------------------------------

def dispatch_departure(departure):
    departure["status"] = "OPERATING"
    for booking in bookings_of(departure["id"]):
        if booking["fulfillment_status"] == "TICKETED":
            mark_no_show(booking, departure)
            db.touch(booking)
    recompute_seats(departure)
    db.touch(departure)
    return departure


def complete_departure(departure, actual_return_utc):
    call = db.port_calls.get(departure["port_call_id"])
    departure["status"] = "COMPLETED"
    departure["actual_return_utc"] = actual_return_utc
    late = bool(call and actual_return_utc > call["all_aboard_utc"])
    rate = commission_rate_for_departure(departure)

    for booking in bookings_of(departure["id"]):
        touched = False
        if booking["fulfillment_status"] == "CHECKED_IN":
            booking["fulfillment_status"] = "COMPLETED"
            touched = True
            if late:
                booking["return_guarantee_honored"] = False
                if departure.get("return_guarantee_eligible") and booking["financial_status"] == "CHARGED":
                    return_guarantee_settlement(booking)
        if booking["fulfillment_status"] in ("COMPLETED", "NO_SHOW"):
            accrual = final_line_cents(booking, rate)
            if accrual != booking["commission_accrued_cents"]:
                booking["commission_accrued_cents"] = accrual
                touched = True
        if touched:
            db.touch(booking)

    recompute_seats(departure)
    db.touch(departure)
    return departure


# --------------------------------------------------------------------------
# port call transitions
# --------------------------------------------------------------------------

def open_call_sales(call):
    call["status"] = "OPEN_FOR_SALE"
    db.touch(call)
    for departure in departures_of_call(call["id"]):
        excursion = db.excursions.get(departure["excursion_id"])
        if departure["status"] == "SCHEDULED" and excursion and excursion["catalog_status"] == "PUBLISHED":
            start_selling(departure)
    return call


def close_call(call):
    call["status"] = "CLOSED"
    db.touch(call)
    for departure in departures_of_call(call["id"]):
        if departure["status"] == "SELLING":
            close_departure_sales(departure)
    for departure in departures_of_call(call["id"]):
        for booking in bookings_of(departure["id"]):
            touched = False
            if booking["fulfillment_status"] == "TICKETED":
                mark_no_show(booking, departure)
                touched = True
            if booking["alternative_offer_status"] == "OFFERED":
                booking["alternative_offer_status"] = "EXPIRED"
                touched = True
            if touched:
                db.touch(booking)
        recompute_seats(departure)
    return call


def cancel_call(call):
    call["status"] = "CANCELLED"
    db.touch(call)
    for departure in departures_of_call(call["id"]):
        if departure["status"] in CANCELLABLE_DEPARTURE_STATUSES:
            cancel_departure(departure, "WEATHER", False)
    return call


def record_delay(call, additional_minutes):
    from datetime import timedelta
    call["delay_minutes"] = call["delay_minutes"] + additional_minutes
    call["effective_arrival_utc"] = call["arrival_utc"] + timedelta(minutes=call["delay_minutes"])
    db.touch(call)
    for departure in departures_of_call(call["id"]):
        recompute_projections(departure)
        if departure["status"] == "SELLING" and departure["timing_risk_band_actual"] == "RED":
            close_departure_sales(departure)
        else:
            recompute_seats(departure)
    return call
