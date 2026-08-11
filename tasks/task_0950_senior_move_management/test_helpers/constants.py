"""Domain thresholds and pure re-derivations of the pricing/roll-up formulas.

Every number here is quoted directly from the requirements narrative, and every
helper re-derives an expected value from those numbers rather than hard-coding a
result, so a test asserting money is asserting the stated formula.
"""

import math
from decimal import ROUND_HALF_UP, Decimal

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
CLOCK_EPOCH = "2026-05-01T00:00:00.000Z"  # reading before any clock is set

# ---------------------------------------------------------------------------
# Pipelines and tiers
# ---------------------------------------------------------------------------
PACKAGE_BASE_CENTS = {
    "STUDIO": 185000,
    "ONE_BED": 265000,
    "TWO_BED": 395000,
    "HOUSE": 620000,
}

PACKAGE_INCLUDED_HOURS = {
    "STUDIO": 18,
    "ONE_BED": 26,
    "TWO_BED": 40,
    "HOUSE": 64,
}
PACKAGE_OVERAGE_RATE_CENTS_PER_HOUR = 8900

CREW_MIN_REQUIRED = {"STUDIO": 2, "ONE_BED": 3, "TWO_BED": 4, "HOUSE": 6}

HEURISTIC_ROOM_COUNT = {"STUDIO": 2, "ONE_BED": 3, "TWO_BED": 5, "HOUSE": 8}
VOLUME_PER_ROOM_CFT = 180

# ---------------------------------------------------------------------------
# Crew, hours and labour
# ---------------------------------------------------------------------------
ROLE_RATE_CENTS = {"LEAD": 9500, "ORGANIZER": 8200, "PACKER": 6800, "DRIVER": 7400}
TIME_ROUNDING_INCREMENT_HOURS = 0.25
HOURLY_MIN_CALLOUT_HOURS = 3.00
OVERTIME_THRESHOLD_HOURS = 8.00
OVERTIME_MULTIPLIER = 1.5

# ---------------------------------------------------------------------------
# Surcharges and the coordination fee
# ---------------------------------------------------------------------------
TRAVEL_FREE_MILES = 15
TRAVEL_BAND1_MAX_MILES = 40
TRAVEL_BAND1_RATE_CENTS = 317
TRAVEL_BAND2_RATE_CENTS = 486

STAIRS_INCLUDED_FLIGHTS = 1
STAIRS_RATE_CENTS_PER_FLIGHT_PER_CREW = 2500

LONG_CARRY_FREE_FEET = 75
LONG_CARRY_BLOCK_FEET = 25
LONG_CARRY_BLOCK_CENTS = 1800

COORD_FEE_RATE = 0.06
COORD_FEE_TIER1_MAX_CENTS = 300000
COORD_FEE_TIER1_CAP_CENTS = 18000
COORD_FEE_TIER2_MAX_CENTS = 800000
COORD_FEE_TIER2_CAP_CENTS = 42000
COORD_FEE_TIER3_CAP_CENTS = 75000

DEPOSIT_SIGNING_PCT = 0.30
DEPOSIT_PACK_START_PCT = 0.40

# ---------------------------------------------------------------------------
# Rooms and space fit
# ---------------------------------------------------------------------------
ROOM_PROVISIONAL_DERATE = 0.80
ROOM_APPROVED_FACTOR = 1.00
ROOM_VOLUME_SAFETY_FACTOR = 0.90

# ---------------------------------------------------------------------------
# Dispositions, appraisal, authority
# ---------------------------------------------------------------------------
CONSIGN_MIN_VALUE_CENTS = 15000
HIGH_VALUE_DISPOSITION_THRESHOLD_CENTS = 250000
AUTHORITY_DEFAULT_CEILING_CENTS = 100000
DONATION_RATE_SELF_REPORTED = 0.30
DONATION_RATE_APPRAISED = 0.85
DONATION_RECEIPT_CAP_CENTS = 500000

# ---------------------------------------------------------------------------
# Consignment
# ---------------------------------------------------------------------------
MARKDOWN_ROUND1_DISCOUNT = 0.20
MARKDOWN_ROUND2_DISCOUNT = 0.35
COMMISSION_BAND1_MAX_CENTS = 50000
COMMISSION_BAND1_RATE = 0.50
COMMISSION_BAND2_MAX_CENTS = 250000
COMMISSION_BAND2_RATE = 0.40
COMMISSION_BAND3_RATE = 0.30
CONSIGN_PICKUP_FEE_CENTS = 7500
CONSIGN_PHOTO_FEE_CENTS_PER_ITEM = 1200
CONSIGN_PHOTO_FEE_CAP_CENTS = 12000
CONSIGN_UNSOLD_WINDOW_DAYS = 30
DISPOSAL_RATE_CENTS_PER_CFT = 145
DISPOSAL_MIN_FEE_CENTS = 9500

# ---------------------------------------------------------------------------
# Vendors
# ---------------------------------------------------------------------------
VENDOR_DAILY_CAPACITY_DEFAULT = 3
VENDOR_HOLDBACK_PCT_DEFAULT = 0.10

# ---------------------------------------------------------------------------
# Trucks, junk haul
# ---------------------------------------------------------------------------
PARTIAL_TRIP_THRESHOLD_FRACTION = 0.15
HAUL_MIN_LOAD_CFT = 250
HAUL_AUTO_ORDER_QUOTE_CENTS = 45000

# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------
MOVE_FREEZE_LEAD_HOURS = 72
MILESTONE_DAY_OFFSETS = {
    "ASSESSMENT": -35,
    "SORT_PLAN": -21,
    "PACK": -3,
    "MOVE_DAY": 0,
    "SETTLE_IN": 7,
    "CLOSE_OUT": 21,
}
MILESTONE_SEQUENCE = [
    "ASSESSMENT",
    "SORT_PLAN",
    "PACK",
    "MOVE_DAY",
    "SETTLE_IN",
    "CLOSE_OUT",
]
PROGRESS_WEIGHTS = {
    "ASSESSMENT": 10,
    "SORT_PLAN": 25,
    "PACK": 15,
    "MOVE_DAY": 30,
    "SETTLE_IN": 15,
    "CLOSE_OUT": 5,
}

PUNCH_SLA_HOURS = {"CRITICAL": 24, "MAJOR": 72, "MINOR": 168}

# ---------------------------------------------------------------------------
# Retry / cycle caps
# ---------------------------------------------------------------------------
MAX_SORT_PLAN_REOPENS = 2
MAX_MOVE_DAY_RESCHEDULES = 1
MAX_MARKDOWN_ROUNDS = 2
MAX_MILESTONE_REOPENS = 2
MAX_UNPACK_REOPENS = 2
MAX_PUNCH_REOPENS = 3
MAX_INVOICE_RECALLS = 2
MAX_INVOICE_DISPUTES = 2
MAX_HOLD_ESCALATIONS = 2
MAX_HOLD_REMANDS = 2
MAX_AUTHORITY_SUSPENSIONS = 2


# ---------------------------------------------------------------------------
# Pure re-derivations
# ---------------------------------------------------------------------------
def round_half_up(value, places: int = 0):
    """All rounding in this system is round-half-up."""
    quant = Decimal(1).scaleb(-places)
    result = Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP)
    return int(result) if places == 0 else float(result)


def travel_surcharge_cents(mileage_miles) -> int:
    """First 15 miles free; miles up to 40 at 317; every mile beyond 40 at 486.

    Each band is rounded to whole cents separately and then the two are added.
    """
    band1_miles = max(min(mileage_miles, TRAVEL_BAND1_MAX_MILES) - TRAVEL_FREE_MILES, 0)
    band2_miles = max(mileage_miles - TRAVEL_BAND1_MAX_MILES, 0)
    return round_half_up(band1_miles * TRAVEL_BAND1_RATE_CENTS) + round_half_up(
        band2_miles * TRAVEL_BAND2_RATE_CENTS
    )


def stairs_surcharge_cents(origin_stairs_flights: int, crew_confirmed_count: int) -> int:
    billable = max(origin_stairs_flights - STAIRS_INCLUDED_FLIGHTS, 0)
    return round_half_up(
        billable * STAIRS_RATE_CENTS_PER_FLIGHT_PER_CREW * crew_confirmed_count
    )


def long_carry_surcharge_cents(origin_long_carry_feet) -> int:
    excess = max(origin_long_carry_feet - LONG_CARRY_FREE_FEET, 0)
    blocks = math.ceil(excess / LONG_CARRY_BLOCK_FEET)
    return round_half_up(blocks * LONG_CARRY_BLOCK_CENTS)


def coordination_fee_cents(pre_fee_subtotal_cents: int) -> int:
    if pre_fee_subtotal_cents <= COORD_FEE_TIER1_MAX_CENTS:
        cap = COORD_FEE_TIER1_CAP_CENTS
    elif pre_fee_subtotal_cents <= COORD_FEE_TIER2_MAX_CENTS:
        cap = COORD_FEE_TIER2_CAP_CENTS
    else:
        cap = COORD_FEE_TIER3_CAP_CENTS
    return min(round_half_up(pre_fee_subtotal_cents * COORD_FEE_RATE), cap)


def quarter_hour_round(raw_hours: float) -> float:
    """Divide by the quarter-hour increment, round half-up, multiply back."""
    increments = round_half_up(
        Decimal(str(raw_hours)) / Decimal(str(TIME_ROUNDING_INCREMENT_HOURS))
    )
    return round_half_up(increments * TIME_ROUNDING_INCREMENT_HOURS, 2)


def applied_hours(billing_hours: float, billing_mode: str) -> float:
    if billing_mode == "HOURLY":
        return round_half_up(max(billing_hours, HOURLY_MIN_CALLOUT_HOURS), 2)
    return round_half_up(billing_hours, 2)


def overtime_hours(applied: float) -> float:
    return round_half_up(max(applied - OVERTIME_THRESHOLD_HOURS, 0), 2)


def labor_cents(applied: float, rate_cents: int) -> int:
    """Regular and overtime components are rounded separately and then added."""
    ot = overtime_hours(applied)
    regular = round_half_up(applied - ot, 2)
    return round_half_up(regular * rate_cents) + round_half_up(
        ot * rate_cents * OVERTIME_MULTIPLIER
    )


def package_overage_cents(billing_hours_total: float, package_tier: str) -> int:
    allowance = PACKAGE_INCLUDED_HOURS[package_tier]
    overage = max(billing_hours_total - allowance, 0)
    return round_half_up(overage * PACKAGE_OVERAGE_RATE_CENTS_PER_HOUR)


def commission_cents(gross_sale_price_cents: int) -> int:
    if gross_sale_price_cents <= COMMISSION_BAND1_MAX_CENTS:
        rate = COMMISSION_BAND1_RATE
    elif gross_sale_price_cents <= COMMISSION_BAND2_MAX_CENTS:
        rate = COMMISSION_BAND2_RATE
    else:
        rate = COMMISSION_BAND3_RATE
    return round_half_up(gross_sale_price_cents * rate)


def consignment_fees_cents(item_count: int) -> int:
    photo = min(
        item_count * CONSIGN_PHOTO_FEE_CENTS_PER_ITEM, CONSIGN_PHOTO_FEE_CAP_CENTS
    )
    return CONSIGN_PICKUP_FEE_CENTS + photo


def net_proceeds_cents(gross_sale_price_cents: int, item_count: int) -> int:
    return max(
        gross_sale_price_cents
        - commission_cents(gross_sale_price_cents)
        - consignment_fees_cents(item_count),
        0,
    )


def markdown_price_cents(list_price_cents: int, markdown_round: int) -> int:
    """Markdowns are always taken off the original list price, never compounded."""
    if markdown_round == 0:
        return list_price_cents
    discount = (
        MARKDOWN_ROUND1_DISCOUNT if markdown_round == 1 else MARKDOWN_ROUND2_DISCOUNT
    )
    return round_half_up(list_price_cents * (1 - discount))


def disposal_fee_cents(total_volume_cft) -> int:
    """Rounded to whole cents first, then floored at the minimum."""
    return max(
        round_half_up(total_volume_cft * DISPOSAL_RATE_CENTS_PER_CFT),
        DISPOSAL_MIN_FEE_CENTS,
    )


def donation_receipt_cents(appraised_value_cents: int, appraisal_source: str) -> int:
    if appraisal_source == "SELF_REPORTED":
        raw = appraised_value_cents * DONATION_RATE_SELF_REPORTED
    elif appraisal_source == "APPRAISED":
        raw = appraised_value_cents * DONATION_RATE_APPRAISED
    else:
        raw = 0
    return min(round_half_up(raw), DONATION_RECEIPT_CAP_CENTS)


def room_effective_capacity(
    nominal_linear_inches, approved_addendum_linear_inches, approved: bool
) -> float:
    if approved:
        return round_half_up(
            nominal_linear_inches * ROOM_APPROVED_FACTOR
            + approved_addendum_linear_inches,
            2,
        )
    return round_half_up(nominal_linear_inches * ROOM_PROVISIONAL_DERATE, 2)


def room_volume_allowance(nominal_volume_cft) -> float:
    return round_half_up(nominal_volume_cft * ROOM_VOLUME_SAFETY_FACTOR, 2)


def trip_count(volume_cft, truck_capacity_cft, truck_count: int) -> int:
    combined = truck_capacity_cft * truck_count
    full = math.floor(volume_cft / combined)
    remainder = volume_cft - full * combined
    count = full + (1 if remainder > PARTIAL_TRIP_THRESHOLD_FRACTION * combined else 0)
    if volume_cft > 0 and count == 0:
        count = 1
    return count


def package_deposit_schedule(contracted_cents: int):
    """Thirty percent at signing, forty at pack start, the rest at close-out."""
    signing = round_half_up(contracted_cents * DEPOSIT_SIGNING_PCT)
    pack_start = round_half_up(contracted_cents * DEPOSIT_PACK_START_PCT)
    return signing, pack_start, contracted_cents - signing - pack_start


def heuristic_volume_cft(home_tier: str) -> float:
    return round_half_up(HEURISTIC_ROOM_COUNT[home_tier] * VOLUME_PER_ROOM_CFT, 2)


def punch_due_at_hours(severity: str) -> int:
    return PUNCH_SLA_HOURS[severity]
