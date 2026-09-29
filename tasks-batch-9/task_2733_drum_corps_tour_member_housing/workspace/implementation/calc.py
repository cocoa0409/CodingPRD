"""Calculations of PRD section 3.

All money is integer cents.  Every proportional step rounds half up exactly
once, at the point the PRD pins it (PRD 2.7).
"""
from decimal import Decimal, ROUND_HALF_UP

from store import add_days, days_between

ONE = Decimal(1)


def rhu(value):
    """Round a Decimal half up to a whole cent / whole unit."""
    return int(Decimal(value).quantize(ONE, rounding=ROUND_HALF_UP))


def ceil_div(numerator, denominator):
    """Integer ceiling division on non-negative integers."""
    if numerator <= 0:
        return 0
    return -((-numerator) // denominator)


# --------------------------------------------------------------------------
# 3.3 installment schedule
# --------------------------------------------------------------------------
INSTALLMENT_COUNTS = {"STANDARD_3": 3, "EXTENDED_6": 6}
SURCHARGE_RATES = {"STANDARD_3": Decimal("0"), "EXTENDED_6": Decimal("0.025")}
INSTALLMENT_GAP_DAYS = 30


def installment_schedule(principal_cents, plan_type):
    """Three ordered steps: surcharge once, split the financed total, spread
    the remainder onto the earliest installments."""
    count = INSTALLMENT_COUNTS[plan_type]
    surcharge = rhu(Decimal(principal_cents) * SURCHARGE_RATES[plan_type])
    financed_total = principal_cents + surcharge
    # Step two: installment_base rounds DOWN.
    base = financed_total // count
    remainder = financed_total - base * count
    amounts = [base + 1 if i < remainder else base for i in range(count)]
    return {
        "installment_count": count,
        "surcharge_cents": surcharge,
        "financed_total_cents": financed_total,
        "installment_base_cents": base,
        "installment_remainder_cents": remainder,
        "amounts": amounts,
    }


def installment_due_dates(first_due_date, count):
    return [add_days(first_due_date, INSTALLMENT_GAP_DAYS * i) for i in range(count)]


# --------------------------------------------------------------------------
# 3.3 payment waterfall
# --------------------------------------------------------------------------
def payment_waterfall_allocation(amount_cents, late_fee_outstanding, principal_outstanding):
    to_late_fee = min(amount_cents, max(late_fee_outstanding, 0))
    to_principal = min(amount_cents - to_late_fee, max(principal_outstanding, 0))
    return to_late_fee, to_principal


# --------------------------------------------------------------------------
# 3.4 late-fee assessment
# --------------------------------------------------------------------------
LATE_FEE_RATE = Decimal("0.015")
LATE_FEE_FLOOR_CENTS = 2500
LATE_FEE_CEILING_CENTS = 15000


def late_fee_assessment(arrears_cents):
    """1.5% of arrears, rounded half up, then clamped up to the floor and
    only afterwards down to the ceiling."""
    fee = rhu(Decimal(arrears_cents) * LATE_FEE_RATE)
    fee = max(fee, LATE_FEE_FLOOR_CENTS)
    fee = min(fee, LATE_FEE_CEILING_CENTS)
    return fee


# --------------------------------------------------------------------------
# 3.5 withdrawal obligation
# --------------------------------------------------------------------------
ADMIN_FEE_CENTS = 15000
LADDER_PERCENTS = {
    0: Decimal("0.75"),
    1: Decimal("0.85"),
    2: Decimal("0.92"),
    3: Decimal("0.97"),
    4: Decimal("1.00"),
}


def member_withdrawal_obligation(charged_cents, withdrawal_date, spring_start, departure):
    if charged_cents == 0:
        return 0, "NONE"
    if withdrawal_date < departure:
        window = days_between(spring_start, departure)
        completed = days_between(spring_start, withdrawal_date)
        if completed < 0:
            completed = 0
        if completed > window:
            completed = window
        component = rhu(Decimal(charged_cents) * Decimal(completed) / Decimal(window))
        return component + ADMIN_FEE_CENTS, "PRORATED_SPRING"
    weeks = days_between(departure, withdrawal_date) // 7
    if weeks > 4:
        weeks = 4
    if weeks < 0:
        weeks = 0
    component = rhu(Decimal(charged_cents) * LADDER_PERCENTS[weeks])
    return component + ADMIN_FEE_CENTS, "LIQUIDATED_LADDER"


# --------------------------------------------------------------------------
# 3.7 transport plan
# --------------------------------------------------------------------------
CUFT_PER_TRUNK = 22
CUFT_PER_CASE = 14
CUFT_PER_PROP = 46
LBS_PER_TRUNK = 180
LBS_PER_CASE = 95
LBS_PER_PROP = 260
TRAILER_CUFT = 1800
TRAILER_LBS = 26000
OVERSIZE_PROP_THRESHOLD = 24
RELIEF_TRACTOR_MILES = 350


def transport_plan(uniform_trunks, instrument_cases, prop_units, travel_miles):
    total_cuft = (
        CUFT_PER_TRUNK * uniform_trunks
        + CUFT_PER_CASE * instrument_cases
        + CUFT_PER_PROP * prop_units
    )
    total_lbs = (
        LBS_PER_TRUNK * uniform_trunks
        + LBS_PER_CASE * instrument_cases
        + LBS_PER_PROP * prop_units
    )
    by_volume = ceil_div(total_cuft, TRAILER_CUFT)
    by_weight = ceil_div(total_lbs, TRAILER_LBS)
    trucks = max(by_volume, by_weight, 1)
    # The two surcharges apply to that maximum, never folded into a ceiling.
    if prop_units > OVERSIZE_PROP_THRESHOLD:
        trucks += 1
    if travel_miles >= RELIEF_TRACTOR_MILES:
        trucks += 1
    return total_cuft, total_lbs, trucks


# --------------------------------------------------------------------------
# 3.7 travel feasibility
# --------------------------------------------------------------------------
CONVOY_MPH = 45
FUEL_STOP_MILES = 200
FUEL_STOP_MINUTES = 30


def travel_feasibility(travel_miles, has_previous):
    if not has_previous:
        return 0
    drive_minutes = ceil_div(travel_miles * 60, CONVOY_MPH)
    fuel_stops = travel_miles // FUEL_STOP_MILES
    return drive_minutes + fuel_stops * FUEL_STOP_MINUTES


# --------------------------------------------------------------------------
# 3.8 food service
# --------------------------------------------------------------------------
BASE_MEAL_CENTS = 1175
MEALS_PER_STOP = 3
DIETARY_MULTIPLIERS = {
    "NONE": Decimal("1"),
    "VEGETARIAN": Decimal("1.08"),
    "GLUTEN_FREE": Decimal("1.22"),
    "SEVERE_ALLERGEN": Decimal("1.45"),
}
# Step one: the per-member unit cost is rounded once per dietary class.
DIETARY_UNIT_CENTS = dict(
    (flag, rhu(Decimal(BASE_MEAL_CENTS) * multiplier))
    for flag, multiplier in DIETARY_MULTIPLIERS.items()
)


def stop_meal_cost(counts_by_flag):
    """Step two multiplies each already-rounded unit by head count and meals."""
    total = 0
    for flag, unit in DIETARY_UNIT_CENTS.items():
        total += unit * counts_by_flag.get(flag, 0) * MEALS_PER_STOP
    return total


# --------------------------------------------------------------------------
# 3.6 bed-night billing
# --------------------------------------------------------------------------
def housing_bed_night_capacity(occupied_bed_nights, minimum_billable_beds, agreement_nights,
                               effective_rate_cents):
    floor_nights = minimum_billable_beds * agreement_nights
    if floor_nights < 0:
        floor_nights = 0
    billable_bed_nights = max(occupied_bed_nights, floor_nights)
    rate = effective_rate_cents or 0
    return billable_bed_nights, billable_bed_nights * rate


# --------------------------------------------------------------------------
# 3.9 circuit settlement
# --------------------------------------------------------------------------
PLACEMENT_SHARES = {
    1: Decimal("0.30"),
    2: Decimal("0.22"),
    3: Decimal("0.16"),
    4: Decimal("0.12"),
    5: Decimal("0.09"),
}
FLAT_PLACEMENT_SHARE = Decimal("0.05")
SANCTION_CAP_RATE = Decimal("0.15")


def placement_prize_share(placement):
    """Sixth or worse earns a flat five percent."""
    return PLACEMENT_SHARES.get(placement, FLAT_PLACEMENT_SHARE)


def circuit_fee_rate(gross_cents):
    """Tiered on the FULL gross, not marginally."""
    if gross_cents < 1500000:
        return Decimal("0.04")
    if gross_cents < 3000000:
        return Decimal("0.055")
    return Decimal("0.07")


def show_settlement_provisional(appearance_fee_cents, prize_pool_cents, projected_placement):
    prize = rhu(Decimal(prize_pool_cents) * placement_prize_share(projected_placement))
    gross = appearance_fee_cents + prize
    fee = rhu(Decimal(gross) * circuit_fee_rate(gross))
    return {
        "provisional_prize_cents": prize,
        "provisional_gross_cents": gross,
        "provisional_circuit_fee_cents": fee,
        "provisional_net_cents": gross - fee,
    }


def show_settlement_final(appearance_fee_cents, prize_pool_cents, final_placement, lines,
                          provisional_net_cents):
    """`lines` is a list of dicts carrying kind, amount_cents and a parsed
    `_recorded_at` datetime plus `_index` (submission order)."""
    prize = rhu(Decimal(prize_pool_cents) * placement_prize_share(final_placement))
    adjustments = sum(
        line["amount_cents"] for line in lines if line["kind"] == "PRIZE_ADJUSTMENT"
    )
    gross = appearance_fee_cents + prize + adjustments
    # Only once the gross stands complete is the fee tier read off it.
    fee = rhu(Decimal(gross) * circuit_fee_rate(gross))

    replayed = sorted(
        [line for line in lines if line["kind"] != "PRIZE_ADJUSTMENT"],
        key=lambda line: (line["_recorded_at"], line["_index"]),
    )
    running_net = gross - fee
    rebate_allowance = fee
    sanctions_charged = 0
    rebate_applied = 0
    for line in replayed:
        if line["kind"] == "SANCTION_FEE":
            cap = rhu(Decimal(running_net) * SANCTION_CAP_RATE)
            charged = min(line["amount_cents"], cap)
            running_net -= charged
            sanctions_charged += charged
        elif line["kind"] == "FEE_REBATE":
            applied = min(line["amount_cents"], rebate_allowance)
            rebate_allowance -= applied
            running_net += applied
            rebate_applied += applied
    return {
        "final_prize_cents": prize,
        "final_gross_cents": gross,
        "final_circuit_fee_cents": fee,
        "sanctions_charged_cents": sanctions_charged,
        "rebate_applied_cents": rebate_applied,
        "final_net_cents": running_net,
        "variance_cents": running_net - provisional_net_cents,
        "remittance_line_count": len(lines),
    }
