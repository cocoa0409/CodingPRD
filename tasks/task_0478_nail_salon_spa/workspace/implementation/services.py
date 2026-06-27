"""Business-logic services: appointment scheduling, the checkout settlement
cascade, no-show cascade, refund reversal, and commission statement payout.
All amounts are integer cents (PRD §2.7).
"""
from datetime import timedelta

from db import db
from clock import clock
from common import touch
from datetime_util import parse_iso8601, format_iso8601
from derive import (client_effective_strikes, station_sanitation_status,
                    station_in_service_appointment_id,
                    DEPOSIT_FLAT_CENTS, NO_SHOW_STRIKE_DEPOSIT_THRESHOLD,
                    LOYALTY_POINT_VALUE_CENTS, STATION_TURNOVER_MINUTES,
                    NO_SHOW_GRACE_MINUTES, CANCEL_FREE_WINDOW_MINUTES)
from calc import (commission_earning_cents, ceil_points,
                  commission_aggregate_payout_cents)


# ---- appointment window helpers -------------------------------------------

def appointment_add_on_rows(appointment_id):
    return [r for r in db.appointment_add_ons.values()
            if r["appointment_id"] == appointment_id]


def compute_end_at(appointment):
    """end_at = start_at + (service.duration_minutes + sum add-on extra_minutes)
    minutes (PRD §3.5). Half-open interval [start_at, end_at)."""
    service = db.menu_items[appointment["service_item_id"]]
    extra = sum(r["extra_minutes_snapshot"] for r in appointment_add_on_rows(appointment["id"]))
    total_minutes = service["duration_minutes"] + extra
    start = parse_iso8601(appointment["start_at"])
    end = start + timedelta(minutes=total_minutes)
    return format_iso8601(end)


def compute_subtotal(appointment):
    """subtotal = service.base_price_cents + sum(add-on price_cents_snapshot)
    (PRD §3.7)."""
    service = db.menu_items[appointment["service_item_id"]]
    add = sum(r["price_cents_snapshot"] for r in appointment_add_on_rows(appointment["id"]))
    return service["base_price_cents"] + add


# ---- deposit assessment (PRD §3.5, §1.3 deposit_assessment) ----------------

def assess_deposit(client):
    """Returns deposit_due_cents for a new booking, based on the client's
    decayed strike count. Sets the (raw) strike posture so deposit_required
    derives true when threshold met. Returns deposit_due_cents."""
    effective, _ = client_effective_strikes(client)
    if effective >= NO_SHOW_STRIKE_DEPOSIT_THRESHOLD:
        return DEPOSIT_FLAT_CENTS
    return 0


# ---- scheduling guards (PRD §3.7) -----------------------------------------

ACTIVE_BOOKING_STATES = {"CONFIRMED", "CHECKED_IN", "IN_SERVICE"}


def windows_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap: a_start < b_end and b_start < a_end."""
    return a_start < b_end and b_start < a_end


def technician_double_booked(appt):
    """True if appt's window overlaps any other CONFIRMED/CHECKED_IN/IN_SERVICE
    appointment on the same technician (zero buffer) (PRD §3.7)."""
    a_start = parse_iso8601(appt["start_at"])
    a_end = parse_iso8601(appt["end_at"])
    for other in db.appointments.values():
        if other["id"] == appt["id"]:
            continue
        if other["technician_id"] != appt["technician_id"]:
            continue
        if other["booking_status"] not in ACTIVE_BOOKING_STATES:
            continue
        o_start = parse_iso8601(other["start_at"])
        o_end = parse_iso8601(other["end_at"])
        if windows_overlap(a_start, a_end, o_start, o_end):
            return True
    return False


def station_turnover_conflict(appt):
    """True if appt's window is NOT separated by >= 10min from some other
    CONFIRMED/CHECKED_IN/IN_SERVICE appointment on the same station (PRD §3.7).
    Allowed iff new.start_at >= other.end_at + 10min OR new.end_at + 10min <= other.start_at.
    Boundary inclusive: a gap of exactly 10min is allowed."""
    buffer = timedelta(minutes=STATION_TURNOVER_MINUTES)
    a_start = parse_iso8601(appt["start_at"])
    a_end = parse_iso8601(appt["end_at"])
    for other in db.appointments.values():
        if other["id"] == appt["id"]:
            continue
        if other["station_id"] != appt["station_id"]:
            continue
        if other["booking_status"] not in ACTIVE_BOOKING_STATES:
            continue
        o_start = parse_iso8601(other["start_at"])
        o_end = parse_iso8601(other["end_at"])
        separated = (a_start >= o_end + buffer) or (a_end + buffer <= o_start)
        if not separated:
            return True
    return False


# ---- checkout settlement cascade (PRD §3.10, §3.11, §1.3) ------------------

def technician_earning_for(appt, technician):
    """Per-appointment technician earning (PRD §3.11)."""
    subtotal = appt["subtotal_cents"]
    if technician["pay_model"] == "COMMISSION":
        return commission_earning_cents(subtotal, technician["commission_pct"])
    # BOOTH_RENT: keeps full subtotal at the line
    return subtotal


def run_checkout_settlement(appt, gift_card, loyalty_points_redeemed):
    """Run the pinned settlement waterfall (PRD §3.10) and all side ledgers.

    Order PINNED: subtotal -> deposit credit -> loyalty redemption -> gift draw
    -> client charge. Mutates appt, client, technician, station, gift card and
    refreshes their updated_at/version. Caller has already validated all
    preconditions (state, OCC, gift active, loyalty sufficiency)."""
    client = db.clients[appt["client_id"]]
    technician = db.technicians[appt["technician_id"]]
    station = db.stations[appt["station_id"]]

    gross = appt["subtotal_cents"]
    # 1. deposit credit
    deposit_credit = appt["deposit_paid_cents"]
    after_deposit = max(0, gross - deposit_credit)
    # 2. loyalty redemption (each point = LOYALTY_POINT_VALUE_CENTS), capped
    requested_loyalty_cents = loyalty_points_redeemed * LOYALTY_POINT_VALUE_CENTS
    loyalty_applied_cents = min(requested_loyalty_cents, after_deposit)
    points_consumed = ceil_points(loyalty_applied_cents, LOYALTY_POINT_VALUE_CENTS)
    after_loyalty = after_deposit - loyalty_applied_cents
    # 3. gift-card draw, capped at min(balance, after_loyalty)
    if gift_card is not None:
        gift_draw_cents = min(gift_card["balance_cents"], after_loyalty)
    else:
        gift_draw_cents = 0
    after_gift = after_loyalty - gift_draw_cents
    # 4. client charge
    total_charged_cents = after_gift

    # record on appointment
    appt["total_charged_cents"] = total_charged_cents
    appt["loyalty_points_redeemed"] = loyalty_points_redeemed
    appt["gift_card_id"] = gift_card["id"] if gift_card is not None else appt["gift_card_id"]

    # side ledgers: loyalty consumed, gift drawn
    client["loyalty_points_balance"] -= points_consumed
    if gift_card is not None and gift_draw_cents:
        gift_card["balance_cents"] -= gift_draw_cents

    # technician earning + accrual
    earning = technician_earning_for(appt, technician)
    appt["technician_earning_cents"] = earning
    technician["accrued_earnings_cents"] += earning
    touch(technician)

    # award loyalty points for the completed service
    service = db.menu_items[appt["service_item_id"]]
    client["loyalty_points_balance"] += service["loyalty_points_award"]
    touch(client)

    # payment + booking dimensions
    appt["payment_status"] = "SETTLED"
    appt["booking_status"] = "COMPLETED"

    # free the station (clears derived occupancy by leaving IN_SERVICE) and
    # refresh its updated_at/version per PRD §2.10 cross-entity consistency.
    touch(station)

    # gift-card cascade hop: drawn to exactly 0 -> DEPLETED
    if gift_card is not None:
        if gift_draw_cents:
            if gift_card["balance_cents"] == 0:
                gift_card["status"] = "DEPLETED"
            touch(gift_card)
        # record bookkeeping for refund reversal
    # bookkeeping for refund reversal
    appt["_gift_draw_cents"] = gift_draw_cents
    appt["_points_consumed"] = points_consumed
    appt["_points_awarded"] = service["loyalty_points_award"]

    touch(appt)


# ---- refund reversal (PRD §3.14) ------------------------------------------

def run_refund_settled(appt):
    """Reverse the checkout cascade (PRD §3.14). payment_status -> REFUNDED.
    Restores gift draw, returns redeemed points, removes awarded points, debits
    technician accrual. Refreshes every reversed entity's updated_at/version."""
    client = db.clients[appt["client_id"]]
    technician = db.technicians[appt["technician_id"]]

    gift_draw = appt.get("_gift_draw_cents", 0)
    points_consumed = appt.get("_points_consumed", 0)
    points_awarded = appt.get("_points_awarded", 0)

    # restore gift-card draw; revert DEPLETED -> ACTIVE if restored positive
    if appt["gift_card_id"] is not None and gift_draw:
        gift_card = db.gift_cards.get(appt["gift_card_id"])
        if gift_card is not None:
            gift_card["balance_cents"] += gift_draw
            if gift_card["status"] == "DEPLETED" and gift_card["balance_cents"] > 0:
                gift_card["status"] = "ACTIVE"
            touch(gift_card)

    # return redeemed loyalty points and remove awarded points (net pre-checkout)
    client["loyalty_points_balance"] += points_consumed
    client["loyalty_points_balance"] -= points_awarded
    touch(client)

    # debit technician accrual by this appointment's earning
    technician["accrued_earnings_cents"] -= appt["technician_earning_cents"]
    touch(technician)

    appt["payment_status"] = "REFUNDED"
    touch(appt)


# ---- no-show cascade (PRD §3.13) ------------------------------------------

def run_mark_no_show(appt):
    """Drive the no-show cascade (PRD §3.13). booking_status -> NO_SHOW.
    Caller has validated grace elapsed and no_show_strike_charged == false."""
    client = db.clients[appt["client_id"]]
    technician = db.technicians[appt["technician_id"]]

    client["_raw_strikes"] += 1
    client["last_no_show_at"] = format_iso8601(clock.now())
    appt["no_show_strike_charged"] = True
    # deposit_required is derived on read; the raw bump above flips it once the
    # effective count reaches the threshold (PRD §3.13 cascade hop).
    touch(client)

    if appt["payment_status"] == "DEPOSIT_HELD":
        appt["payment_status"] = "FORFEITED"

    technician["lifetime_no_show_strikes_attributed"] += 1
    touch(technician)

    appt["booking_status"] = "NO_SHOW"
    touch(appt)


# ---- cancellation (PRD §3.12) ---------------------------------------------

def run_cancel(appt):
    """Cancel a REQUESTED/CONFIRMED appointment (PRD §3.12). Refund deposit if
    at/before start_at - 120min, else forfeit; untouched if no deposit held."""
    if appt["payment_status"] == "DEPOSIT_HELD":
        start = parse_iso8601(appt["start_at"])
        free_boundary = start - timedelta(minutes=CANCEL_FREE_WINDOW_MINUTES)
        if clock.now() <= free_boundary:
            appt["payment_status"] = "REFUNDED"
        else:
            appt["payment_status"] = "FORFEITED"
    appt["booking_status"] = "CANCELLED"
    touch(appt)


# ---- commission statement payout (PRD §3.16, §1.3 statement_payout) --------

def settle_statement(stmt, technician):
    """Sweep COMPLETED appointments in [period_start, period_end) and compute
    payout (PRD §3.16). SUM-THEN-ROUND for COMMISSION. Resets technician accrual."""
    period_start = parse_iso8601(stmt["period_start"])
    period_end = parse_iso8601(stmt["period_end"])

    swept = []
    for ap in db.appointments.values():
        if ap["technician_id"] != stmt["technician_id"]:
            continue
        if ap["booking_status"] != "COMPLETED":
            continue
        completed_at = parse_iso8601(ap["updated_at"])
        if period_start <= completed_at < period_end:
            swept.append(ap)

    # deterministic order: updated_at ASC, then created_at ASC (never id)
    swept.sort(key=lambda a: (a["updated_at"], a["created_at"], a["_seq"]))

    swept_count = len(swept)
    gross = sum(a["subtotal_cents"] for a in swept)

    if technician["pay_model"] == "COMMISSION":
        # SUM-THEN-ROUND: aggregate gross, apply (1 - commission_pct) once
        payout = commission_aggregate_payout_cents(gross, technician["commission_pct"])
    else:  # BOOTH_RENT
        payout = max(0, gross - technician["booth_rent_cents"])

    retained = gross - payout

    stmt["gross_service_cents"] = gross
    stmt["technician_payout_cents"] = payout
    stmt["salon_retained_cents"] = retained
    stmt["swept_appointment_count"] = swept_count
    stmt["status"] = "SETTLED"

    technician["accrued_earnings_cents"] = 0
    touch(technician)
    touch(stmt)
