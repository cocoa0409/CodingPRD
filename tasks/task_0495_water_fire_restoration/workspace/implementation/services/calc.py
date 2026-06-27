"""Calculation rules (PRD §3.3, §3.4, §3.5, §3.6, §3.7; SCAFFOLD Table 3).

All money is integer cents. Rounding is always round-half-up via Decimal, never
float round() (which is banker's rounding) and never IEEE-754 float arithmetic
for money.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

# ---- Constants (SCAFFOLD Table 3) ----
P_ATM_HPA = Decimal("1013.25")
GRAINS_PER_LB = 7000
DRY_TOLERANCE_PCT = 4
WALL_PER_AM = 16
AM_DAY_RATE_CENTS = 2500
DEHU_DAY_RATE_CENTS = 8000
WARRANTY_DAYS = 365  # warranty window applied at completion (completed_at + WARRANTY_DAYS)

AM_DIVISOR = {1: 100, 2: 70, 3: 60, 4: 50}      # sqft per air mover, by sizing class
CLASS_FACTOR = {1: 0.5, 2: 1.0, 3: 1.5, 4: 2.0}  # ppd water load per sqft, by sizing class


def _d(value):
    return value if isinstance(value, Decimal) else Decimal(str(value))


def round_half_up(value, places):
    """Round to `places` decimal places, half-up; returns a Decimal."""
    d = _d(value)
    if places <= 0:
        q = Decimal("1")
    else:
        q = Decimal("1").scaleb(-places)
    return d.quantize(q, rounding=ROUND_HALF_UP)


def round_half_up_int(value):
    """Round to a whole integer, half-up."""
    return int(round_half_up(value, 0))


# ----------------------------------------------------------------------------
# Psychrometric grains-per-pound (PRD §3.4)
# ----------------------------------------------------------------------------
def compute_gpp(temp_f, relative_humidity_pct):
    """Grains-per-pound humidity ratio from dry-bulb temp (F) and RH (%).

    Magnus saturation-vapor-pressure formula; result rounded half-up to whole
    grains. The math uses float for the transcendental exp(), then round-half-up
    via Decimal for the final whole-grain quantization.
    """
    tc = (temp_f - 32) * 5 / 9
    es = 6.112 * math.exp(17.62 * tc / (243.12 + tc))   # saturation vapor pressure, hPa
    e = es * (relative_humidity_pct / 100)              # actual vapor pressure, hPa
    w = 0.62198 * e / (float(P_ATM_HPA) - e)            # humidity ratio, lb/lb
    return round_half_up_int(w * GRAINS_PER_LB)


# ----------------------------------------------------------------------------
# Chamber equipment sizing (PRD §3.3)
# ----------------------------------------------------------------------------
def sizing_class(job):
    """WATER jobs size at their water_class; FIRE/SMOKE jobs size at class 2."""
    if job["loss_type"] == "WATER":
        return job["water_class"]
    return 2


def compute_air_movers_required(floor_area_sqft, wet_wall_linear_ft, klass):
    floor_term = max(1, math.ceil(floor_area_sqft / AM_DIVISOR[klass]))
    wall_term = math.ceil(wet_wall_linear_ft / WALL_PER_AM)
    return floor_term + wall_term


def compute_dehumidifiers_required(floor_area_sqft, dehu_ppd_rating, klass):
    water_load_ppd = round_half_up(floor_area_sqft * CLASS_FACTOR[klass], 2)
    return math.ceil(water_load_ppd / _d(dehu_ppd_rating))


# ----------------------------------------------------------------------------
# Chamber dry determination (PRD §3.4)
# ----------------------------------------------------------------------------
def is_dry(latest_moisture_content_pct, dry_standard_pct):
    """Inclusive boundary: a value exactly at dry_standard_pct + 4 is DRY."""
    if latest_moisture_content_pct is None:
        return False
    return _d(latest_moisture_content_pct) <= _d(dry_standard_pct) + DRY_TOLERANCE_PCT


# ----------------------------------------------------------------------------
# Insurance ACV (PRD §3.5) — per-line depreciation rounding pinned BEFORE sum
# ----------------------------------------------------------------------------
def compute_acv_total_cents(line_items, depreciation_pct, tax_pct):
    acv_sum = 0
    dep_pct = _d(depreciation_pct)
    for line in line_items:
        rcv = line["qty"] * line["unit_price_cents"]
        dep = round_half_up_int(_d(rcv) * dep_pct / 100)   # whole cents, PER LINE
        acv_sum += (rcv - dep)
    tax = round_half_up_int(_d(acv_sum) * _d(tax_pct) / 100)
    return acv_sum + tax


# ----------------------------------------------------------------------------
# Scope-lines + forward-looking equipment estimate (PRD §3.5)
# ----------------------------------------------------------------------------
def compute_scope_lines_total_cents(line_items):
    return sum(line["qty"] * line["unit_price_cents"] for line in line_items)


def compute_equipment_estimate_cents(estimated_drying_days, chambers):
    """Forward-looking projection over all non-DECOMMISSIONED chambers using
    each chamber's REQUIRED counts (not actual placements)."""
    per_day = 0
    for c in chambers:
        per_day += (c["air_movers_required"] * AM_DAY_RATE_CENTS
                    + c["dehumidifiers_required"] * DEHU_DAY_RATE_CENTS)
    return estimated_drying_days * per_day


# ----------------------------------------------------------------------------
# Contents waterfall valuation (PRD §3.6)
# ----------------------------------------------------------------------------
def waterfall_allocate(items, claim_limit_cents):
    """items in created_at ASC order; mutates allocated_value_cents in place and
    returns the allocated total."""
    remaining = max(0, claim_limit_cents)
    allocated_total = 0
    for item in items:
        alloc = min(remaining, item["declared_value_cents"])
        item["allocated_value_cents"] = alloc
        remaining -= alloc
        allocated_total += alloc
    return allocated_total
