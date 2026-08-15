"""Calculation rules per SCAFFOLD §1.3 and PRD §3.

All money is integer cents. Gas-load figures at 1 decimal, pressure-drop at 3
decimals. Rounding is half-up at the stated precision via decimal.Decimal.
"""

import math
from decimal import Decimal, ROUND_HALF_UP

# --- load_calculation constants ---
BTU_PER_CFH = 1000

# --- meter_sizing constants ---
BASE_CAPACITY_CFPH = {"AL_425": 425, "AL_800": 800, "AL_1400": 1400, "AL_2300": 2300, "AL_5000": 5000}
PAIRED_REGULATOR = {"AL_425": "R_325", "AL_800": "R_750", "AL_1400": "R_1200", "AL_2300": "R_2100", "AL_5000": "R_4500"}
PRESSURE_MEDIUM_MULTIPLIER = 2.0

# --- ciac constants ---
BASE_ALLOWANCE_FT = 100
ALLOWANCE_FT_PER_APPLIANCE = 25
STANDARD_UNIT_COST_CENTS_PER_FT = 4500
CROSSING_SURCHARGE_CENTS = 15000
ROCK_SURCHARGE_CENTS_PER_FT = 2000
GROSS_UP_NUM = 21
GROSS_UP_DEN = 79

# --- permit_fee constants ---
SURFACE_RATE_CENTS_PER_SQFT = {"ASPHALT": 350, "CONCRETE": 525, "LANDSCAPE": 150}
FILING_FEE_CENTS = 7500

# --- leak_test_acceptance constants ---
ALLOW_REF_DROP_PSI = Decimal("0.300")
ALLOW_REF_DURATION_MIN = 60

# --- commitment_dates constants ---
PERMIT_MIN_DAYS = 10
PERMIT_MEDIAN_DAYS = 20
CONSTRUCTION_FT_PER_DAY_OPTIMISTIC = 150
CONSTRUCTION_FT_PER_DAY_CONSERVATIVE = 100
METER_SET_DAYS = 5
CONSERVATIVE_BUFFER_DAYS = 5

# --- delay_penalty_credit constants ---
MAX_CREDIT_CENTS = 50000

# --- turn-on safety ---
CO_FAIL_THRESHOLD_PPM = 9.0


def round_half_up(value, places):
    """Round a numeric value half-up to `places` decimal places, returning float/int."""
    q = Decimal(1).scaleb(-places)
    d = Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP)
    if places == 0:
        return int(d)
    return float(d)


# ---------------------------------------------------------------------------
# load_calculation
# ---------------------------------------------------------------------------

def counted_load_cfph(quantity, btuh_input_rating):
    """per row: round_half_up(quantity x btuh_input_rating / 1000, 1)"""
    return round_half_up(Decimal(quantity) * Decimal(btuh_input_rating) / Decimal(BTU_PER_CFH), 1)


def diversity_factor(n):
    if n == 1:
        return Decimal("1.00")
    if 2 <= n <= 3:
        return Decimal("0.85")
    if 4 <= n <= 6:
        return Decimal("0.75")
    return Decimal("0.65")  # n >= 7


def load_calculation(load_rows):
    """Returns (appliance_count, total_connected_load_cfph, diversity_adjusted_load_cfph)."""
    n = len(load_rows)
    total = sum(Decimal(str(r["counted_load_cfph"])) for r in load_rows)
    total_connected = round_half_up(total, 1)
    diversity_adjusted = round_half_up(Decimal(str(total_connected)) * diversity_factor(n), 1) if n > 0 else 0.0
    return n, total_connected, diversity_adjusted


# ---------------------------------------------------------------------------
# meter_sizing
# ---------------------------------------------------------------------------

def meter_sizing(diversity_adjusted_load_cfph, pressure_class):
    """Returns (meter_model, regulator_model) or None when nothing fits.

    Smallest pressure-adjusted capacity >= load; exact equality selects that model.
    """
    multiplier = PRESSURE_MEDIUM_MULTIPLIER if pressure_class == "MEDIUM" else 1
    load = Decimal(str(diversity_adjusted_load_cfph))
    for model in ("AL_425", "AL_800", "AL_1400", "AL_2300", "AL_5000"):
        capacity = Decimal(BASE_CAPACITY_CFPH[model]) * Decimal(str(multiplier))
        if capacity >= load:
            return model, PAIRED_REGULATOR[model]
    return None


# ---------------------------------------------------------------------------
# ciac_provisional / ciac_final_true_up
# ---------------------------------------------------------------------------

def ciac_provisional(design_footage_ft, crossings, rock_excavation_expected, appliance_count):
    """Pinned evaluation order; returns a dict of the provisional fields."""
    allowance_ft = BASE_ALLOWANCE_FT + ALLOWANCE_FT_PER_APPLIANCE * appliance_count
    base_cost = design_footage_ft * STANDARD_UNIT_COST_CENTS_PER_FT
    surcharges = len(crossings) * CROSSING_SURCHARGE_CENTS + (
        design_footage_ft * ROCK_SURCHARGE_CENTS_PER_FT if rock_excavation_expected else 0
    )
    net_ciac = max(0, base_cost + surcharges - allowance_ft * STANDARD_UNIT_COST_CENTS_PER_FT)
    gross_up = int(
        (Decimal(net_ciac) * Decimal(GROSS_UP_NUM) / Decimal(GROSS_UP_DEN)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    total_due = net_ciac + gross_up
    return {
        "crossings_count": len(crossings),
        "allowance_ft": allowance_ft,
        "provisional_base_cost_cents": base_cost,
        "provisional_surcharges_cents": surcharges,
        "provisional_net_ciac_cents": net_ciac,
        "provisional_gross_up_cents": gross_up,
        "provisional_total_due_cents": total_due,
    }


def ciac_final_true_up(actual_footage_ft, actual_unit_cost_cents, actual_crossings,
                       actual_rock_excavation, allowance_ft, provisional_total_due_cents):
    """Final variant over as-built inputs; returns final_* fields and the signed delta."""
    final_base = actual_footage_ft * actual_unit_cost_cents
    final_surcharges = len(actual_crossings) * CROSSING_SURCHARGE_CENTS + (
        actual_footage_ft * ROCK_SURCHARGE_CENTS_PER_FT if actual_rock_excavation else 0
    )
    final_net = max(0, final_base + final_surcharges - allowance_ft * STANDARD_UNIT_COST_CENTS_PER_FT)
    final_gross_up = int(
        (Decimal(final_net) * Decimal(GROSS_UP_NUM) / Decimal(GROSS_UP_DEN)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    final_total = final_net + final_gross_up
    delta = final_total - provisional_total_due_cents
    return {
        "final_net_ciac_cents": final_net,
        "final_gross_up_cents": final_gross_up,
        "final_total_due_cents": final_total,
        "ciac_delta_cents": delta,
    }


# ---------------------------------------------------------------------------
# permit_fee — per-segment rounding FIRST, then sum, then filing fee
# ---------------------------------------------------------------------------

def permit_fee(crossings):
    total = 0
    for seg in crossings:
        area = Decimal(str(seg["length_ft"])) * Decimal(str(seg["width_ft"]))
        raw = area * Decimal(SURFACE_RATE_CENTS_PER_SQFT[seg["surface_type"]])
        total += int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return total + FILING_FEE_CENTS


# ---------------------------------------------------------------------------
# leak_test_acceptance
# ---------------------------------------------------------------------------

def leak_test_acceptance(test_duration_min, observed_pressure_drop_psi):
    """max_allowed = round_half_up(0.300 * 60 / duration, 3); PASS iff observed <= max (equality passes)."""
    max_allowed = (ALLOW_REF_DROP_PSI * Decimal(ALLOW_REF_DURATION_MIN) / Decimal(test_duration_min)).quantize(
        Decimal("0.001"), rounding=ROUND_HALF_UP
    )
    observed = Decimal(str(observed_pressure_drop_psi))
    result = "PASS" if observed <= max_allowed else "FAIL"
    return float(max_allowed), result


# ---------------------------------------------------------------------------
# commitment_dates
# ---------------------------------------------------------------------------

def commitment_dates(base_date, design_footage_ft, crossings_count):
    """Returns (optimistic_date, conservative_date) as ISO date strings."""
    import datetime as _dt

    permit_required = crossings_count > 0
    optimistic_days = (PERMIT_MIN_DAYS if permit_required else 0) + math.ceil(
        design_footage_ft / CONSTRUCTION_FT_PER_DAY_OPTIMISTIC
    ) + METER_SET_DAYS
    conservative_days = (PERMIT_MEDIAN_DAYS if permit_required else 0) + math.ceil(
        design_footage_ft / CONSTRUCTION_FT_PER_DAY_CONSERVATIVE
    ) + METER_SET_DAYS + CONSERVATIVE_BUFFER_DAYS
    optimistic = base_date + _dt.timedelta(days=optimistic_days)
    conservative = base_date + _dt.timedelta(days=conservative_days)
    return optimistic.isoformat(), conservative.isoformat()


# ---------------------------------------------------------------------------
# delay_penalty_credit
# ---------------------------------------------------------------------------

def delay_penalty_credit(committed_completion_date_iso, completed_date, delay_attribution):
    """Credit applies only when delay attribution is UTILITY; tiered 2500/5000, capped at 50000."""
    import datetime as _dt

    if delay_attribution != "UTILITY":
        return 0
    committed = _dt.date.fromisoformat(committed_completion_date_iso)
    days_late = (completed_date - committed).days
    if days_late <= 0:
        return 0
    credit = min(days_late, 5) * 2500 + max(0, days_late - 5) * 5000
    return min(MAX_CREDIT_CENTS, credit)


# ---------------------------------------------------------------------------
# turn-on safety computation
# ---------------------------------------------------------------------------

def turn_on_verified(co_reading_ppm, odor_detected, ignition_verified, venting_verified):
    """VERIFIED iff !odor && ignition && venting && co < 9.0 (equality 9.0 FAILS)."""
    return (
        (not odor_detected)
        and ignition_verified
        and venting_verified
        and float(co_reading_ppm) < CO_FAIL_THRESHOLD_PPM
    )
