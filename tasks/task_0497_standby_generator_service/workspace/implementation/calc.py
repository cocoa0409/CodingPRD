"""Calculation rules (PRD §3, SCAFFOLD §1.3). All money in integer cents,
round-half-up. No floats for monetary rounding."""
import math
from decimal import Decimal, ROUND_HALF_UP

# ---- Constants -------------------------------------------------------------
POWER_FACTOR = Decimal("0.8")
KW_QUANTUM = Decimal("0.25")

HOURS_PER_MONTH_EQUIV = 50
COVERAGE_VALUE_CENTS = 240000

MONITORING_ADDON_CENTS = 6000
BUNDLE_DISCOUNT = Decimal("0.10")
TIER1_KW = 14
TIER2_KW = 24

TAX_RATE = Decimal("0.0875")

EXERCISE_INTERVAL_DAYS = 7
HEALTH_THRESHOLD = 70

BTU_PER_KW = 10000

REGISTRATION_BONUS_MONTHS = 12
GRACE_DAYS = 7
VISIT_BUFFER_HOURS = 4


def round_half_up(value):
    """Round a Decimal to a whole integer using ROUND_HALF_UP."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _to_decimal(x):
    return Decimal(str(x))


# ---- (1) Load sizing -------------------------------------------------------
def run_load_sizing(appliances, method):
    """Return (peak_demand_w:int, required_kw:float).

    R = sum(running_watts). surge_delta = starting - running.
    STAGGERED: R + max(surge_delta). FULL_LOAD: R + sum(surge_delta).
    required_va = peak / 0.8; required_kw = ceil_to_quarter(va / 1000).
    """
    running_total = sum(a["running_watts"] for a in appliances)
    deltas = [a["starting_watts"] - a["running_watts"] for a in appliances]
    if method == "FULL_LOAD":
        surge = sum(deltas)
    else:  # STAGGERED (default)
        surge = max(deltas) if deltas else 0
    peak_demand_w = running_total + surge

    required_va = _to_decimal(peak_demand_w) / POWER_FACTOR
    kw_raw = required_va / Decimal(1000)
    # ceil_to_quarter: ceil(x / 0.25) * 0.25
    quanta = (kw_raw / KW_QUANTUM).to_integral_value(rounding="ROUND_CEILING")
    required_kw = quanta * KW_QUANTUM
    return int(peak_demand_w), _kw_to_number(required_kw)


def _kw_to_number(dec):
    """Render a quarter-kW Decimal as a JSON-friendly number (int when whole)."""
    if dec == dec.to_integral_value():
        return int(dec)
    return float(dec)


# ---- (2) Warranty refund ---------------------------------------------------
def run_warranty_refund(warranty_total_months, calendar_elapsed, runtime_hours,
                        refund_basis):
    """refund_cents = round_half_up(COVERAGE_VALUE_CENTS * remaining / total)."""
    total = warranty_total_months
    if total <= 0:
        return 0
    usage_elapsed = math.ceil(_to_decimal(runtime_hours) / Decimal(HOURS_PER_MONTH_EQUIV))
    if refund_basis == "USAGE":
        elapsed = max(calendar_elapsed, usage_elapsed)
    else:  # CALENDAR (default)
        elapsed = calendar_elapsed
    remaining = max(0, total - elapsed)
    value = _to_decimal(COVERAGE_VALUE_CENTS) * Decimal(remaining) / Decimal(total)
    return round_half_up(value)


# ---- (3) Maintenance plan price -------------------------------------------
def run_plan_price(rated_kw, frequency, monitoring_bundled):
    if rated_kw <= TIER1_KW:
        visit_price = 18000
    elif rated_kw <= TIER2_KW:
        visit_price = 26000
    else:
        visit_price = 34000
    visits_per_year = 2 if frequency == "SEMI_ANNUAL" else 1
    subtotal = visit_price * visits_per_year + (MONITORING_ADDON_CENTS if monitoring_bundled else 0)
    if monitoring_bundled and frequency == "SEMI_ANNUAL":
        # discount applied to the integer subtotal BEFORE rounding
        annual = round_half_up(_to_decimal(subtotal) * (Decimal(1) - BUNDLE_DISCOUNT))
    else:
        annual = subtotal
    return annual, visits_per_year


# ---- (4) Repair invoice ----------------------------------------------------
def run_repair_invoice(labor_cents, parts_cents):
    """Per-line-then-sum: tax each present line, round, then sum. Zero lines skipped."""
    total = 0
    for line in (labor_cents, parts_cents):  # fixed order: labor, then parts
        if line == 0:
            continue
        total += round_half_up(_to_decimal(line) * (Decimal(1) + TAX_RATE))
    return total


# ---- (5) Exercise compliance score ----------------------------------------
def run_compliance_score(days_active, completed_success):
    """expected = floor(days_active / 7). score = clamp(round_half_up(100*c/e),0,100)."""
    days_active = max(0, days_active)
    expected = days_active // EXERCISE_INTERVAL_DAYS
    if expected <= 0:
        return 100
    score = round_half_up(_to_decimal(100) * Decimal(completed_success) / Decimal(expected))
    return max(0, min(100, score))


# ---- (6) Fuel BTU adequacy -------------------------------------------------
def run_fuel_adequacy(required_kw, fuel_supply_btu_per_hr, existing_load_btu_per_hr):
    required_btu = int(_to_decimal(required_kw) * BTU_PER_KW)
    available_btu = fuel_supply_btu_per_hr - (existing_load_btu_per_hr or 0)
    return available_btu >= required_btu  # boundary inclusive
