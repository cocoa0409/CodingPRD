"""Pure calculation rules (PRD sections 2.9, 3.2, 3.5, 3.6, 3.8)."""

from decimal import Decimal

from core import (
    BASE_ROUND_SECONDS,
    COURSE_WALK_MIN_MINUTES,
    HEIGHT_FACTOR_BASE_CM,
    HEIGHT_FACTOR_DIVISOR,
    JUMPOFF_CAP,
    JUMPOFF_RATE,
    MIN_ENTRIES_FOR_POINTS,
    NATIONAL_POINTS,
    OFFICE_FEE_FULL_AMOUNT_CENTS,
    OFFICE_FEE_REDUCED_AMOUNT_CENTS,
    OFFICE_FEE_REDUCED_CENTS,
    OFFICE_FEE_WAIVER_CENTS,
    PLACE_SHARE_BP,
    REGIONAL_PLACING_CAP,
    REGIONAL_POINTS,
    bp_share,
    ceil_int,
    round_half_up_1dp,
)

PROJECTED_STATUSES = ("ENTERED", "CONFIRMED")
CONFIRMED_ONLY_STATUSES = ("CONFIRMED",)


# --------------------------------------------------------------------------
# class_duration_estimate
# --------------------------------------------------------------------------
def duration_estimate(cls, division, ring, entry_count):
    base_seconds = BASE_ROUND_SECONDS[division["discipline"]]
    excess = max(0, int(cls["jump_height_cm"]) - HEIGHT_FACTOR_BASE_CM)
    height_factor = Decimal(1) + (Decimal(excess) / Decimal(HEIGHT_FACTOR_DIVISOR))

    rounds = int(entry_count)
    if division["jumpoff_enabled"] and division["discipline"] == "JUMPER":
        jumpoff_rounds = min(ceil_int(Decimal(rounds) * JUMPOFF_RATE), JUMPOFF_CAP)
    else:
        jumpoff_rounds = 0

    course_walk_minutes = max(COURSE_WALK_MIN_MINUTES, ceil_int(Decimal(rounds) / Decimal(10)) * 5)
    ride_minutes = ceil_int(
        Decimal(rounds + jumpoff_rounds) * Decimal(base_seconds) * height_factor / Decimal(60)
    )
    return ride_minutes + course_walk_minutes + int(ring["turnover_buffer_minutes"])


def count_class_entries(class_entries, statuses):
    return sum(1 for ce in class_entries if ce["status"] in statuses)


# --------------------------------------------------------------------------
# class_prize_allocation
# --------------------------------------------------------------------------
def division_allotment(show, division):
    return bp_share(show["prize_money_pool_cents"], division["division_share_bp"])


def class_purse(division, cls):
    return bp_share(division["division_allotment_cents"], cls["class_share_bp"])


def ribbon_allocation(class_purse_cents, placed_count):
    """Return (mapping placing -> cents, awarded total) per the pinned order."""
    k = min(5, int(placed_count))
    place_cents = {}
    for place in range(1, k + 1):
        place_cents[place] = bp_share(class_purse_cents, PLACE_SHARE_BP[place])
    awarded = sum(place_cents.values())
    if k == 5:
        place_cents[1] = place_cents[1] + (int(class_purse_cents) - awarded)
        awarded = int(class_purse_cents)
    return place_cents, awarded


# --------------------------------------------------------------------------
# entry_settlement
# --------------------------------------------------------------------------
BILLABLE_CLASS_ENTRY_STATUSES = ("ENTERED", "CONFIRMED", "COMPLETED", "DISQUALIFIED")


def office_fee_for(preliminary_subtotal_cents):
    if preliminary_subtotal_cents >= OFFICE_FEE_WAIVER_CENTS:
        return 0
    if preliminary_subtotal_cents >= OFFICE_FEE_REDUCED_CENTS:
        return OFFICE_FEE_REDUCED_AMOUNT_CENTS
    return OFFICE_FEE_FULL_AMOUNT_CENTS


# --------------------------------------------------------------------------
# rider_standing_points
# --------------------------------------------------------------------------
def national_multiplier(confirmed_entry_count):
    count = int(confirmed_entry_count)
    if count >= 25:
        return Decimal("2.0")
    if count >= 10:
        return Decimal("1.5")
    if count >= MIN_ENTRIES_FOR_POINTS:
        return Decimal("1.0")
    return Decimal("0.0")


def national_points_for(placing, confirmed_entry_count):
    if placing is None:
        return Decimal("0.0")
    table = NATIONAL_POINTS.get(int(placing), 0)
    return round_half_up_1dp(Decimal(table) * national_multiplier(confirmed_entry_count))


def raw_regional_points_for(placing):
    if placing is None:
        return 0
    place = int(placing)
    if place > REGIONAL_PLACING_CAP:
        return 0
    return REGIONAL_POINTS.get(place, 0)
