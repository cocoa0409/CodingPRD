"""Pure calculation functions (PRD §3.7). All money is integer cents."""
import math
from decimal import Decimal, ROUND_HALF_UP

# ---- Constants ----
WAIVER_VALID_DAYS = 365
CERT_VALID_DAYS = 365
CYCLE_DAYS = 30
GRACE_DAYS = 7
RENTAL_DUE_HOURS = 24
LATE_FEE_PER_DAY_CENTS = 800
DAY_PASS_BASE_CENTS = 2500
GEAR_BUNDLE_CENTS = 1200
YOUTH_DISCOUNT_RATE = Decimal("0.20")
CERT_PASS_THRESHOLD = 80
CERT_STATION_FLOOR = 60

PLAN_FEES = {"BASIC": 9000, "YOUTH_TEAM": 6000}
STYLE_MULT = {"SLAB": Decimal("1.0"), "OVERHANG": Decimal("1.25"), "ROOF": Decimal("1.50")}
STATION_WEIGHTS = {
    "knot": Decimal("0.30"),
    "commands": Decimal("0.20"),
    "catch": Decimal("0.30"),
    "lower": Decimal("0.20"),
}

SECONDS_PER_DAY = 86400


def round_half_up(value):
    """Round a Decimal half-up to a whole integer."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def is_youth_at(dob, ref_date):
    """True when age in completed years as of ref_date (a datetime) is under 18.

    Age is measured in completed years against the created_at date.
    """
    years = ref_date.year - dob.year
    # Subtract one if the birthday has not yet occurred this year (by month/day).
    if (ref_date.month, ref_date.day) < (dob.month, dob.day):
        years -= 1
    return years < 18


def day_pass_price(is_youth, gear_bundle):
    subtotal = DAY_PASS_BASE_CENTS + (GEAR_BUNDLE_CENTS if gear_bundle else 0)
    if is_youth:
        # floor (truncate toward zero) of 20% of the subtotal
        discount = int((Decimal(subtotal) * YOUTH_DISCOUNT_RATE).to_integral_value(rounding="ROUND_FLOOR"))
    else:
        discount = 0
    return subtotal - discount


def ceil_days_between(start, end):
    """Whole days remaining from start to end, never less than zero.

    Counts complete days from the freeze instant to cycle_end (the count of whole
    days remaining). Uses floor of the elapsed seconds over a day.
    """
    if end <= start:
        return 0
    delta_seconds = (end - start).total_seconds()
    return int(delta_seconds // SECONDS_PER_DAY)


def freeze_credit(monthly_fee_cents, clock_now, cycle_end):
    unused_days = ceil_days_between(clock_now, cycle_end)
    credit = round_half_up(Decimal(monthly_fee_cents) * Decimal(unused_days) / Decimal(CYCLE_DAYS))
    return credit, unused_days


def renewal_charge(monthly_fee_cents, wallet_credit_cents):
    """Returns (wallet_applied, card_charge, new_wallet_credit). Wallet-first."""
    gross = monthly_fee_cents
    wallet_applied = min(wallet_credit_cents, gross)
    card_charge = gross - wallet_applied
    new_wallet = wallet_credit_cents - wallet_applied
    return wallet_applied, card_charge, new_wallet


def rental_late_fee(due_at, return_clock, deposit_cents):
    """Returns (late_fee_cents, refund_cents) for a RETURN."""
    hours_late = max(0, (return_clock - due_at).total_seconds() / 3600.0)
    days_late = math.ceil(hours_late / 24.0)
    raw_fee = LATE_FEE_PER_DAY_CENTS * days_late
    late_fee = min(raw_fee, deposit_cents)
    refund = deposit_cents - late_fee
    return late_fee, refund


def belay_weighted_score(knot, commands, catch, lower):
    raw = (
        STATION_WEIGHTS["knot"] * Decimal(knot)
        + STATION_WEIGHTS["commands"] * Decimal(commands)
        + STATION_WEIGHTS["catch"] * Decimal(catch)
        + STATION_WEIGHTS["lower"] * Decimal(lower)
    )
    weighted = round_half_up(raw)
    min_station = min(knot, commands, catch, lower)
    return weighted, min_station


def difficulty_points(grade, style):
    base_points = 100 + grade * 50
    mult = STYLE_MULT[style]
    return round_half_up(Decimal(base_points) * mult)


def grace_days_overdue(past_due_since, clock_now):
    delta = (clock_now - past_due_since).total_seconds()
    return int(delta // SECONDS_PER_DAY)
