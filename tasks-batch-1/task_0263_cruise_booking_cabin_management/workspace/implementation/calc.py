"""Pure calculation helpers (PRD §2.8, §3.4, §3.8, §3.7)."""
from decimal import ROUND_HALF_UP, Decimal

# ---- Constants (PRD §3.4 / §3.8 / §3.7) ----
THIRD_FOURTH_PCT = Decimal("0.55")
PORT_FEE_PCT = Decimal("0.115")
FLAT_PORT_PER_GUEST_CENTS = 8900
DEPOSIT_PCT = Decimal("0.20")
DEPOSIT_MIN_PER_GUEST_CENTS = 25000
CANCEL_ADMIN_FEE_CENTS = 5000
FCC_PENALTY_FACTOR = Decimal("0.50")
GRATUITY_PER_GUEST_PER_NIGHT_CENTS = 1800
# Dining turnover buffer (minutes), applied symmetrically around each seating
# (PRD §3.6: fixed forty-five-minute spacing; test_helpers/constants.py == 45).
DINING_TURNOVER_MINUTES = 45


def half_up(value):
    """Round a Decimal to the nearest whole cent, half rounds up. Returns int."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def base_fare_for_index(base_fare, occupancy_index):
    """Per-guest base fare before group discount (PRD §3.4)."""
    if occupancy_index <= 2:
        return int(base_fare)
    return half_up(Decimal(base_fare) * THIRD_FOURTH_PCT)


def final_fare_for(base_fare_cents, apply_group, group_discount_pct):
    """final_fare_cents from base_fare_cents (PRD §3.4)."""
    if apply_group:
        factor = Decimal("1") - Decimal(str(group_discount_pct))
        return half_up(Decimal(base_fare_cents) * factor)
    return int(base_fare_cents)


def tax_port_for(final_fare_cents):
    """Per-guest taxes + port fees (PRD §3.4)."""
    return half_up(Decimal(final_fare_cents) * PORT_FEE_PCT) + FLAT_PORT_PER_GUEST_CENTS


def deposit_schedule(booking_total_cents, guest_count):
    """Returns (deposit_due_cents, final_due_cents) (PRD §3.4)."""
    pct_component = half_up(Decimal(booking_total_cents) * DEPOSIT_PCT)
    floor_component = DEPOSIT_MIN_PER_GUEST_CENTS * guest_count
    deposit_due = max(pct_component, floor_component)
    final_due = booking_total_cents - deposit_due
    return deposit_due, final_due


def penalty_pct_for_days(days_before):
    """Cancellation penalty fraction keyed on whole days before sailing (PRD §3.8)."""
    if days_before >= 90:
        return Decimal("0.00")
    if days_before >= 60:
        return Decimal("0.25")
    if days_before >= 30:
        return Decimal("0.50")
    if days_before >= 15:
        return Decimal("0.75")
    return Decimal("1.00")


def cancellation_settlement(mode, booking_total_cents, amount_paid_cents, days_before):
    """Returns (cancel_refund_cents, fcc_credit_cents) (PRD §3.8)."""
    penalty_pct = penalty_pct_for_days(days_before)
    penalty_cents = half_up(Decimal(booking_total_cents) * penalty_pct)
    if mode == "CASH":
        admin_fee = CANCEL_ADMIN_FEE_CENTS if penalty_pct == Decimal("0.00") else 0
        refund = amount_paid_cents - penalty_cents - admin_fee
        return max(refund, 0), 0
    # FCC
    fcc_penalty_cents = half_up(Decimal(penalty_cents) * FCC_PENALTY_FACTOR)
    credit = amount_paid_cents - fcc_penalty_cents
    return 0, max(credit, 0)


def gratuity_total(guest_count, nights):
    return GRATUITY_PER_GUEST_PER_NIGHT_CENTS * guest_count * nights
