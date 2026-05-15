"""Pricing, SOH assessment, grading, cascade, and degradation calculations."""

from decimal import Decimal

from db import DB, new_id
from services.common import init_append_only, now_iso
from services.numeric import clamp, round_half_up, round_half_up_cents, round_half_up_float


PER_SWAP_BASE_CENTS = 500

TOU_RATE = {
    "PEAK": 40,
    "SHOULDER": 25,
    "OFF_PEAK": 15,
}
SOC_DIFF_MULTIPLIER = Decimal("1.20")

SUBSCRIPTION_DEDUCTION = {
    "NONE": 0,
    "BASIC": 500,
    "PREMIUM": 1500,
}

RESISTANCE_BASELINE_MOHM = Decimal("50")
RESISTANCE_PENALTY_PER_MOHM = Decimal("0.10")
TEMP_HIGH_C = Decimal("35")
TEMP_LOW_C = Decimal("10")
TEMP_PENALTY_PER_C = Decimal("0.05")
CYCLE_BASELINE = 500
CYCLE_PENALTY_PER_CYCLE = Decimal("0.005")

GRADE_A_FLOOR = Decimal("90.0")
GRADE_C_FLOOR = Decimal("70.0")

CASCADE_ENERGY_STORAGE_MAX_CYCLES = 1500
CASCADE_LSV_MAX_CYCLES = 2500

DEGRADATION_WINDOW = 5


# ---------------- pricing ----------------------------------------------------

def compute_swap_billing(*, outgoing_soc_pct, incoming_soc_pct,
                         rated_capacity_kwh, tou_zone,
                         subscription_tier, subscription_swaps_remaining):
    """Compute the swap billing components. All amounts in integer cents.

    Returns a dict with the same keys persisted on BillingRecord.
    """
    out_soc = Decimal(str(outgoing_soc_pct))
    in_soc = Decimal(str(incoming_soc_pct))
    rated_kwh = Decimal(str(rated_capacity_kwh))

    soc_delta = in_soc - out_soc
    if soc_delta < 0:
        soc_delta = Decimal("0")

    energy_kwh = (soc_delta / Decimal("100")) * rated_kwh
    tou_rate_cents = Decimal(str(TOU_RATE.get(tou_zone, TOU_RATE["SHOULDER"])))

    soc_diff_cents = round_half_up_cents(energy_kwh * tou_rate_cents * SOC_DIFF_MULTIPLIER)
    tou_pass_through_cents = round_half_up_cents(energy_kwh * tou_rate_cents * Decimal("1.00"))

    subtotal = PER_SWAP_BASE_CENTS + soc_diff_cents + tou_pass_through_cents

    deduction = 0
    if subscription_swaps_remaining and subscription_swaps_remaining > 0:
        deduction = SUBSCRIPTION_DEDUCTION.get(subscription_tier, 0)

    amount_due = subtotal - deduction
    if amount_due < 0:
        amount_due = 0

    return {
        "per_swap_base_cents": PER_SWAP_BASE_CENTS,
        "soc_diff_cents": int(soc_diff_cents),
        "tou_pass_through_cents": int(tou_pass_through_cents),
        "subscription_deduction_cents": int(deduction),
        "amount_due_cents": int(amount_due),
    }


# ---------------- SOH assessment ---------------------------------------------

def compute_soh_pct(*, capacity_test_kwh, internal_resistance_mohm,
                    avg_temperature_c, cycle_count_at_assessment,
                    rated_capacity_kwh) -> float:
    """Compute SOH percent, rounded half-up to 2 decimals, clamped to [0, 100]."""
    cap_kwh = Decimal(str(capacity_test_kwh))
    rated_kwh = Decimal(str(rated_capacity_kwh))
    resistance = Decimal(str(internal_resistance_mohm))
    temp = Decimal(str(avg_temperature_c))
    cycles = Decimal(str(cycle_count_at_assessment))

    if rated_kwh == 0:
        capacity_factor = Decimal("0")
    else:
        capacity_factor = (cap_kwh / rated_kwh) * Decimal("100.0")

    resistance_excess = resistance - RESISTANCE_BASELINE_MOHM
    if resistance_excess < 0:
        resistance_excess = Decimal("0")
    resistance_penalty = resistance_excess * RESISTANCE_PENALTY_PER_MOHM

    if temp > TEMP_HIGH_C:
        temperature_penalty = (temp - TEMP_HIGH_C) * TEMP_PENALTY_PER_C
    elif temp < TEMP_LOW_C:
        temperature_penalty = (TEMP_LOW_C - temp) * TEMP_PENALTY_PER_C
    else:
        temperature_penalty = Decimal("0")

    cycle_excess = cycles - Decimal(CYCLE_BASELINE)
    if cycle_excess < 0:
        cycle_excess = Decimal("0")
    cycle_penalty = cycle_excess * CYCLE_PENALTY_PER_CYCLE

    raw = capacity_factor - resistance_penalty - temperature_penalty - cycle_penalty
    clamped = clamp(raw, Decimal("0"), Decimal("100"))
    rounded = round_half_up(clamped, 2)
    return float(rounded)


def grade_for_soh(soh_pct, ev_soh_floor_pct) -> str:
    soh = Decimal(str(soh_pct))
    floor = Decimal(str(ev_soh_floor_pct))
    if soh >= GRADE_A_FLOOR:
        return "A"
    if soh >= floor:
        return "B"
    if soh >= GRADE_C_FLOOR:
        return "C"
    return "RETIRED_EV"


def cascade_stage_for_battery(battery: dict) -> str:
    if battery.get("recall_flag"):
        return "END_OF_LIFE"
    cycles = int(battery.get("cycle_count", 0))
    if cycles < CASCADE_ENERGY_STORAGE_MAX_CYCLES:
        return "ENERGY_STORAGE"
    if cycles < CASCADE_LSV_MAX_CYCLES:
        return "LOW_SPEED_VEHICLE"
    return "END_OF_LIFE"


def compute_degradation_slope(battery_id: str) -> float:
    """Fit slope across the most recent DEGRADATION_WINDOW assessments for this battery."""
    rows = [r for r in DB["soh_assessments"].values() if r.get("battery_id") == battery_id]
    rows.sort(key=lambda r: (r.get("created_at", ""), r.get("id", "")))
    window = rows[-DEGRADATION_WINDOW:]
    if len(window) < 2:
        return 0.0
    xs = [Decimal(str(r["cycle_count_at_assessment"])) for r in window]
    ys = [Decimal(str(r["soh_pct_out"])) for r in window]
    n = Decimal(len(window))
    mean_x = sum(xs, Decimal("0")) / n
    mean_y = sum(ys, Decimal("0")) / n
    numerator = sum(((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)), Decimal("0"))
    denominator = sum(((x - mean_x) * (x - mean_x) for x in xs), Decimal("0"))
    if denominator == 0:
        return 0.0
    slope = numerator / denominator
    return float(round_half_up(slope, 4))


def create_soh_assessment(battery: dict, body_inputs: dict, rated_capacity_kwh) -> dict:
    """Create a SOHAssessment row, compute soh_pct, grade and slope; return the row."""
    row = {
        "id": new_id(),
        "battery_id": battery["id"],
        "capacity_test_kwh": body_inputs["capacity_test_kwh"],
        "internal_resistance_mohm": body_inputs["internal_resistance_mohm"],
        "avg_temperature_c": body_inputs["avg_temperature_c"],
        "cycle_count_at_assessment": int(battery["cycle_count"]),
        "degradation_slope": 0.0,
        "soh_pct_out": 0.0,
        "soh_grade_out": "A",
    }
    init_append_only(row)
    DB["soh_assessments"][row["id"]] = row

    soh_pct = compute_soh_pct(
        capacity_test_kwh=row["capacity_test_kwh"],
        internal_resistance_mohm=row["internal_resistance_mohm"],
        avg_temperature_c=row["avg_temperature_c"],
        cycle_count_at_assessment=row["cycle_count_at_assessment"],
        rated_capacity_kwh=rated_capacity_kwh,
    )
    row["soh_pct_out"] = soh_pct

    # Grade derived from the (now-rounded) soh_pct relative to the model's floor.
    from services.lookups import battery_model_by_code
    bm = battery_model_by_code(battery["battery_model_code"])
    floor = bm["ev_soh_floor_pct"] if bm else 80.0
    grade = grade_for_soh(soh_pct, floor)
    row["soh_grade_out"] = grade

    row["degradation_slope"] = compute_degradation_slope(battery["id"])
    return row
