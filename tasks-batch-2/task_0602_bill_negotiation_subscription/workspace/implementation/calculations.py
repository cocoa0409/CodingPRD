"""Calculation rules. Money is integer cents. Decimal + ROUND_HALF_UP for rates."""
from decimal import Decimal, ROUND_HALF_UP

# Annualization constants
WEEKS_PER_YEAR = 52
MONTHS_PER_YEAR = 12

# Success-fee tier table
LOW_TIER_CENTS = 10000
HIGH_TIER_CENTS = 50000
LOW_RATE = Decimal("0.40")
MID_RATE = Decimal("0.35")
HIGH_RATE = Decimal("0.30")
FEE_CAP_CENTS = 20000

# Refund pursuit constants
LOOKBACK_CYCLES = 6
OUTAGE_DAYS = 10
CYCLE_DAYS = 30

# Caps
MAX_ROUNDS = 8
MAX_DISPUTE_ROUNDS = 3


def round_half_up(value):
    """Round a Decimal to nearest whole integer, half rounds up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def annualize_charge_cost(amount_cents, cadence):
    if cadence == "MONTHLY":
        return amount_cents * MONTHS_PER_YEAR
    if cadence == "ANNUAL":
        return amount_cents * 1
    if cadence == "WEEKLY":
        return amount_cents * WEEKS_PER_YEAR
    return amount_cents


def success_fee_split(gross_cents):
    """Tiered fee on gross. Returns success_fee_cents."""
    gross_cents = max(0, gross_cents)
    if gross_cents < LOW_TIER_CENTS:
        rate = LOW_RATE
    elif gross_cents < HIGH_TIER_CENTS:
        rate = MID_RATE
    else:
        rate = HIGH_RATE
    raw_fee = round_half_up(Decimal(gross_cents) * rate)
    capped = min(raw_fee, FEE_CAP_CENTS)
    return max(capped, 0)


def refund_pursuit_amount(claim_type, observed_old, observed_new):
    delta = max(0, observed_old - observed_new)
    if claim_type == "PRICE_DROP":
        claimed = delta * LOOKBACK_CYCLES
    elif claim_type == "DOUBLE_BILL":
        claimed = observed_old
    elif claim_type == "SERVICE_OUTAGE":
        claimed = round_half_up(Decimal(observed_old) * OUTAGE_DAYS / CYCLE_DAYS)
    else:
        claimed = 0
    return max(0, claimed)
