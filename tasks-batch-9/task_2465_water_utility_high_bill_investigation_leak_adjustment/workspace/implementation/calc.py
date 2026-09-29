"""Deterministic calculations (PRD 3.x).  All money and rate math uses Decimal
with ROUND_HALF_UP.  No floats, no built-in round().
"""

from decimal import Decimal

from core import (
    ANOMALY_RATIO_THRESHOLD,
    AWWA_WEIGHT_HIGH,
    AWWA_WEIGHT_LOW,
    AWWA_WEIGHT_MID,
    BASELINE_SAMPLE_COUNT,
    D,
    DOWN_PAYMENT_MIN_BP,
    FAST_THRESHOLD_PCT,
    MAX_CREDIT_CENTS,
    MAX_CREDIT_PCT_BP,
    PAST_DUE_THRESHOLD_CENTS,
    SEWER_RELIEF_BASIS_GALLONS,
    SEWER_RELIEF_LEAK_TYPES,
    SLOW_THRESHOLD_PCT,
    SMALL_METER_MAX_INCHES,
    rhu,
    rhu_int,
)

THOUSAND = Decimal(1000)
BP_SCALE = Decimal(10000)


# ---------------------------------------------------------------------------
# tiered_water_charge
# ---------------------------------------------------------------------------
def tiered_water_charge(gallons, schedule, season):
    gallons = int(gallons)
    tier1_limit = int(schedule["tier1_limit_gallons"])
    tier2_limit = int(schedule["tier2_limit_gallons"])
    t1 = min(gallons, tier1_limit)
    t2 = max(0, min(gallons, tier2_limit) - tier1_limit)
    t3 = max(0, gallons - tier2_limit)

    line1 = rhu_int(D(t1) * D(schedule["tier1_rate_cents_per_kgal"]) / THOUSAND)
    line2 = rhu_int(D(t2) * D(schedule["tier2_rate_cents_per_kgal"]) / THOUSAND)
    rate3 = D(schedule["tier3_rate_cents_per_kgal"])
    if season == "SUMMER":
        surcharge = D(schedule["summer_surcharge_bp"])
        line3 = rhu_int(D(t3) * rate3 * (BP_SCALE + surcharge) / (THOUSAND * BP_SCALE))
    else:
        line3 = rhu_int(D(t3) * rate3 / THOUSAND)
    return int(schedule["base_charge_cents"]) + line1 + line2 + line3


# ---------------------------------------------------------------------------
# sewer_charge_with_submeter_credit
# ---------------------------------------------------------------------------
def sewer_charge(gallons, submeter_credit_gallons, schedule):
    """Cap first, then subtract the submeter credit."""
    capped = min(int(gallons), int(schedule["sewer_cap_gallons"]))
    billable = max(0, capped - int(submeter_credit_gallons))
    charge = rhu_int(D(billable) * D(schedule["sewer_rate_cents_per_kgal"]) / THOUSAND)
    return billable, charge


# ---------------------------------------------------------------------------
# seasonal_baseline
# ---------------------------------------------------------------------------
def seasonal_baseline(samples):
    """`samples` is the already-ordered candidate pool (most recent first)."""
    window = samples[:BASELINE_SAMPLE_COUNT]
    if len(window) < BASELINE_SAMPLE_COUNT:
        return None, len(window)
    total = sum(int(s) for s in window)
    return rhu_int(D(total) / D(BASELINE_SAMPLE_COUNT)), BASELINE_SAMPLE_COUNT


# ---------------------------------------------------------------------------
# anomaly_screen
# ---------------------------------------------------------------------------
def anomaly_screen(consumption_gallons, baseline_gallons):
    if baseline_gallons is None or int(baseline_gallons) == 0:
        return None, False
    ratio = rhu(D(int(consumption_gallons)) / D(int(baseline_gallons)), 3)
    return ratio, ratio >= ANOMALY_RATIO_THRESHOLD


# ---------------------------------------------------------------------------
# sewer_relief_basis
# ---------------------------------------------------------------------------
def sewer_relief_gallons(excess_gallons, sewer_billable_gallons, submeter_credit_gallons):
    headroom = max(0, int(sewer_billable_gallons) - int(submeter_credit_gallons))
    return min(int(excess_gallons), SEWER_RELIEF_BASIS_GALLONS, headroom)


# ---------------------------------------------------------------------------
# leak_adjustment_credit
# ---------------------------------------------------------------------------
def select_variant(leak_type, board_ordered):
    if board_ordered:
        return "BASELINE_REBILL"
    if leak_type in ("SERVICE_LINE", "UNDERGROUND"):
        return "BASELINE_REBILL"
    return "EXCESS_REPRICE"


def leak_adjustment_credit(bill, schedule, season, leak_type, baseline_gallons,
                           board_ordered=False, forced_variant=None):
    baseline = int(baseline_gallons or 0)
    consumption = int(bill["consumption_gallons"] or 0)
    excess = max(0, consumption - baseline)
    variant = forced_variant or select_variant(leak_type, board_ordered)

    water_charge = int(bill["water_charge_cents"] or 0)
    baseline_water = tiered_water_charge(baseline, schedule, season)

    if variant == "EXCESS_REPRICE":
        repriced = rhu_int(D(excess) * D(schedule["tier1_rate_cents_per_kgal"]) / THOUSAND)
        billed_for_excess = water_charge - baseline_water
        water_credit = max(0, billed_for_excess - repriced)
    else:
        water_credit = max(0, water_charge - baseline_water)

    relief = 0
    sewer_credit = 0
    if leak_type in SEWER_RELIEF_LEAK_TYPES and excess > 0:
        relief = sewer_relief_gallons(
            excess,
            int(bill["sewer_billable_gallons"] or 0),
            int(bill["submeter_credit_gallons"] or 0),
        )
        sewer_credit = rhu_int(D(relief) * D(schedule["sewer_rate_cents_per_kgal"]) / THOUSAND)

    gross = water_credit + sewer_credit

    total_charge = int(bill["total_charge_cents"] or 0)
    cap = min(rhu_int(D(total_charge) * D(MAX_CREDIT_PCT_BP) / BP_SCALE), MAX_CREDIT_CENTS)
    capped = min(gross, cap)
    cap_applied = capped < gross

    threshold = int(schedule["admin_fee_waiver_threshold_cents"])
    if capped >= threshold:
        admin_fee = 0
    else:
        admin_fee = min(int(schedule["admin_fee_cents"]), capped)

    net = capped - admin_fee

    return {
        "variant_applied": variant,
        "excess_gallons": excess,
        "water_credit_cents": water_credit,
        "sewer_relief_gallons": relief,
        "sewer_credit_cents": sewer_credit,
        "gross_credit_cents": gross,
        "cap_cents": cap,
        "capped_credit_cents": capped,
        "cap_applied": cap_applied,
        "admin_fee_charged_cents": admin_fee,
        "net_credit_cents": net,
    }


# ---------------------------------------------------------------------------
# bench_test_accuracy
# ---------------------------------------------------------------------------
def bench_test_accuracy(size_inches, low_pct, mid_pct, high_pct):
    low, mid, high = D(low_pct), D(mid_pct), D(high_pct)
    if D(size_inches) <= SMALL_METER_MAX_INCHES:
        method = "AWWA_WEIGHTED"
        accuracy = rhu(
            AWWA_WEIGHT_LOW * low + AWWA_WEIGHT_MID * mid + AWWA_WEIGHT_HIGH * high, 2
        )
    else:
        method = "SIMPLE_MEAN"
        accuracy = rhu((low + mid + high) / Decimal(3), 2)

    if accuracy > FAST_THRESHOLD_PCT:
        result = "FAST"
    elif accuracy < SLOW_THRESHOLD_PCT:
        result = "SLOW"
    else:
        result = "PASS"
    correction_factor = rhu(Decimal(100) / accuracy, 6)
    return method, accuracy, result, correction_factor


# ---------------------------------------------------------------------------
# read_correction_reallocation
# ---------------------------------------------------------------------------
def corrected_segment(target_value, prior_value, correction_factor):
    return rhu_int(D(int(target_value) - int(prior_value)) * D(correction_factor))


# ---------------------------------------------------------------------------
# payment_arrangement_schedule
# ---------------------------------------------------------------------------
def arrangement_schedule(total_amount_cents, down_payment_cents, installment_count):
    financed = int(total_amount_cents) - int(down_payment_cents)
    count = int(installment_count)
    installment = financed // count if financed >= 0 else -((-financed) // count)
    remainder = financed - installment * count
    final = installment + remainder
    return installment, final


def minimum_down_payment(total_amount_cents):
    return rhu_int(D(int(total_amount_cents)) * D(DOWN_PAYMENT_MIN_BP) / BP_SCALE)


# ---------------------------------------------------------------------------
# account_credit_status
# ---------------------------------------------------------------------------
def credit_status(balance_cents, arrangement_statuses):
    if "DEFAULTED" in arrangement_statuses:
        return "ARRANGEMENT_DEFAULTED"
    if "ACTIVE" in arrangement_statuses:
        return "IN_ARRANGEMENT"
    if int(balance_cents) > PAST_DUE_THRESHOLD_CENTS:
        return "PAST_DUE"
    return "CURRENT"
