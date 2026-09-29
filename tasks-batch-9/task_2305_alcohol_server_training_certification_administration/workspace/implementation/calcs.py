"""Calculation rules (SCAFFOLD 1.3 / PRD 2.7, 3.6-3.9)."""

import calendar
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

HUNDRED = Decimal("100")


def round_half_up(value, places=2):
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    exp = Decimal(1).scaleb(-places) if places > 0 else Decimal(1)
    return value.quantize(exp, rounding=ROUND_HALF_UP)


def round_cents(value):
    """Whole cents, round half up."""
    return int(round_half_up(value, 0))


def pct(numerator, denominator):
    """round_half_up(numerator / denominator * 100, 2)."""
    return round_half_up(Decimal(numerator) / Decimal(denominator) * HUNDRED, 2)


def add_months(anchor, months):
    """Month arithmetic that clamps the day and preserves the time-of-day."""
    total = anchor.month - 1 + int(months)
    year = anchor.year + total // 12
    month = total % 12 + 1
    day = min(anchor.day, calendar.monthrange(year, month)[1])
    return anchor.replace(year=year, month=month, day=day)


def whole_months(start, end):
    """Number of whole months between two instants (0 when start is None)."""
    if start is None or end is None:
        return 0
    if end < start:
        return 0
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if (end.day, end.hour, end.minute, end.second, end.microsecond) < (
        start.day, start.hour, start.minute, start.second, start.microsecond
    ):
        months -= 1
    return max(0, months)


def add_days(anchor, days):
    return anchor + timedelta(days=int(days))


def add_hours(anchor, hours):
    return anchor + timedelta(hours=int(hours))


# --- exam_attempt_scoring --------------------------------------------------

def score_pct(raw_correct_count, question_count):
    return pct(raw_correct_count, question_count)


# --- registry_submission_penalty ------------------------------------------

ESCALATION_PER_ATTEMPT = Decimal("0.05")
DAY_SECONDS = 86400


def registry_penalty(transmitted_at, due_at, attempt_number, fee_per_day):
    if due_at is None or transmitted_at <= due_at:
        late_days = 0
    else:
        delta = (transmitted_at - due_at).total_seconds()
        late_days = int(math.ceil(delta / DAY_SECONDS))
    escalation = Decimal(1) + ESCALATION_PER_ATTEMPT * Decimal(attempt_number - 1)
    penalty = round_cents(Decimal(late_days) * Decimal(fee_per_day) * escalation)
    return late_days, penalty


# --- seat_credit_purchase_settlement --------------------------------------

PROCESSING_FEE_RATE = Decimal("0.029")
PROCESSING_FEE_CAP_CENTS = 2500
BONUS_CREDIT_NET_CENTS = 100000


def seat_credit_settlement(seat_quantity, unit_price_cents):
    subtotal = seat_quantity * unit_price_cents                       # 1
    if subtotal < 50000:                                              # 2
        volume_discount_pct = Decimal("0.00")
    elif subtotal < 150000:
        volume_discount_pct = Decimal("3.00")
    elif subtotal < 500000:
        volume_discount_pct = Decimal("6.00")
    else:
        volume_discount_pct = Decimal("10.00")
    discount_cents = round_cents(Decimal(subtotal) * volume_discount_pct / HUNDRED)  # 3
    net_cents = subtotal - discount_cents                             # 4
    processing_fee_cents = min(                                       # 5
        PROCESSING_FEE_CAP_CENTS,
        round_cents(Decimal(net_cents) * PROCESSING_FEE_RATE),
    )
    total_charged_cents = net_cents + processing_fee_cents            # 6
    bonus_credits = net_cents // BONUS_CREDIT_NET_CENTS               # 7
    seat_credits_granted = seat_quantity + bonus_credits              # 8
    return {
        "subtotal_cents": subtotal,
        "volume_discount_pct": round_half_up(volume_discount_pct, 2),
        "discount_cents": discount_cents,
        "net_cents": net_cents,
        "processing_fee_cents": processing_fee_cents,
        "total_charged_cents": total_charged_cents,
        "bonus_credits": bonus_credits,
        "seat_credits_granted": seat_credits_granted,
    }


# --- dram_shop_discount_pct / credit --------------------------------------

MAX_DISCOUNT_PCT = Decimal("12.00")
TENURE_BONUS_CAP_PCT = Decimal("3.00")
MULTI_LOCATION_BONUS_PCT = Decimal("2.00")
MULTI_LOCATION_MIN_COUNT = 3
MULTI_LOCATION_MIN_RATE_PCT = Decimal("90.00")


def dram_shop_discount(account_rate, account_status, months_documented,
                       location_count, min_location_strict_rate):
    rate = Decimal(account_rate)
    if rate >= Decimal("98.00"):
        tier, base = "TIER_3", Decimal("10.00")
    elif rate >= Decimal("90.00"):
        tier, base = "TIER_2", Decimal("7.00")
    elif rate >= Decimal("80.00"):
        tier, base = "TIER_1", Decimal("4.00")
    else:
        tier, base = "NONE", Decimal("0.00")

    tenure_bonus_pct = min(
        TENURE_BONUS_CAP_PCT,
        Decimal(months_documented // 12) * Decimal("1.00"),
    )
    if (location_count >= MULTI_LOCATION_MIN_COUNT
            and Decimal(min_location_strict_rate) >= MULTI_LOCATION_MIN_RATE_PCT):
        multi_bonus_pct = MULTI_LOCATION_BONUS_PCT
    else:
        multi_bonus_pct = Decimal("0.00")

    if account_status != "ACTIVE":
        return "NONE", Decimal("0.00")

    total = base + tenure_bonus_pct + multi_bonus_pct
    clamped = min(MAX_DISCOUNT_PCT, max(Decimal("0.00"), total))
    return tier, round_half_up(clamped, 2)


def dram_shop_credit(locations, discount_pct):
    """Round each location's credit to whole cents FIRST, then sum."""
    credit = 0
    for loc in locations:
        credit += round_cents(
            Decimal(loc["annual_premium_cents"]) * Decimal(discount_pct) / HUNDRED
        )
    return credit
