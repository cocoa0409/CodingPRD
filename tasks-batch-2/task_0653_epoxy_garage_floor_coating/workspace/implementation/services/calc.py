"""Calculation rules (SCAFFOLD §1.3 / PRD §2.7, §3.3, §3.4, §3.6, §3.7).

All money is whole integer cents. Non-integer cent results are rounded HALF UP
(PRD §2.7). The pricing engine rounds at each pinned intermediate step.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

# ---- calc condition_score constants ----
W_OIL = Decimal("0.30")
W_CRACK = Decimal("0.40")
W_SPALL = Decimal("0.20")
W_MOIST = Decimal("0.10")
CRACK_DENSITY_CAP = 50
TIER_HEAVY_MIN = 70
TIER_MODERATE_MIN = 35

# ---- calc quote_pricing constants ----
SYSTEM_RATE = {"FLAKE_STANDARD": 350, "FLAKE_PREMIUM": 500, "METALLIC": 800}
PREP_RATE = {"LIGHT": 150, "MODERATE": 275, "HEAVY": 450}
CRACK_INCLUDED_FT = {"LIGHT": 0, "MODERATE": 10, "HEAVY": 25}
CRACK_RATE_PER_FT = 900
MIN_BILLABLE_SQFT = 250
METALLIC_MULT = Decimal("1.20")
SEASON_MULT = {"PEAK": Decimal("1.15"), "STANDARD": Decimal("1.00"), "OFF": Decimal("0.90")}
MOBILIZATION_CENTS = 25000
VOLUME_TIER_1_MIN = 300000
VOLUME_TIER_2_MIN = 600000

# ---- calc cure_window constants ----
INSTALL_DURATION_HOURS = 8
FOOT_TRAFFIC_HOURS = 24
VEHICLE_TRAFFIC_HOURS = 72
METALLIC_EXTRA_CURE_HOURS = 24

# ---- calc warranty_proration constants ----
DEFAULT_TERM_MONTHS = 180
PEEL_FACTOR = Decimal("1.00")
HOT_TIRE_FACTOR = Decimal("0.50")

# ---- calc referral_credit_ledger constant ----
REFERRAL_CREDIT_CENTS = 15000


def round_half_up(value):
    """Round a Decimal/number to the nearest whole integer, half up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# (1) condition_score -> prep_tier  (PRD §3.3)
# ---------------------------------------------------------------------------
def condition_score(oil_stain_pct, crack_density, spalling, moisture_pct):
    crack_norm = (Decimal(min(crack_density, CRACK_DENSITY_CAP)) / Decimal(CRACK_DENSITY_CAP)) * Decimal(100)
    spall_pts = Decimal(100) if spalling else Decimal(0)
    raw = (W_OIL * Decimal(oil_stain_pct)
           + W_CRACK * crack_norm
           + W_SPALL * spall_pts
           + W_MOIST * Decimal(moisture_pct))
    score = round_half_up(raw)
    if score >= TIER_HEAVY_MIN:
        tier = "HEAVY"
    elif score >= TIER_MODERATE_MIN:
        tier = "MODERATE"
    else:
        tier = "LIGHT"
    return score, tier


def billable_crack_ft(crack_linear_ft, prep_tier):
    included = CRACK_INCLUDED_FT[prep_tier]
    return max(0, crack_linear_ft - included)


# ---------------------------------------------------------------------------
# (2) quote_pricing  (PRD §3.4)  — pinned evaluation order, rounding per step
# ---------------------------------------------------------------------------
def quote_pricing(sqft_in, crack_ft_in, prep_tier, coating_family, sku, install_season):
    priced_sqft = max(sqft_in, MIN_BILLABLE_SQFT)

    # system material (METALLIC complexity mult on material only, rounded)
    base_material = Decimal(SYSTEM_RATE[sku]) * Decimal(priced_sqft)
    if coating_family == "METALLIC":
        system_material_cents = round_half_up(base_material * METALLIC_MULT)
    else:
        system_material_cents = int(base_material)  # rate*sqft is already integer cents

    # prep labor (tier rate + crack adder, then seasonal mult, rounded)
    base_labor = Decimal(PREP_RATE[prep_tier]) * Decimal(priced_sqft)
    included_ft = CRACK_INCLUDED_FT[prep_tier]
    extra_ft = max(0, crack_ft_in - included_ft)
    crack_add = Decimal(extra_ft) * Decimal(CRACK_RATE_PER_FT)
    prep_labor_cents = round_half_up((base_labor + crack_add) * SEASON_MULT[install_season])

    # PINNED ORDER: discount keyed on (material + labor) BEFORE mobilization
    pre_discount = system_material_cents + prep_labor_cents
    if pre_discount >= VOLUME_TIER_2_MIN:
        volume_pct = Decimal("0.10")
        volume_discount_pct_bps = 1000
    elif pre_discount >= VOLUME_TIER_1_MIN:
        volume_pct = Decimal("0.05")
        volume_discount_pct_bps = 500
    else:
        volume_pct = Decimal("0.00")
        volume_discount_pct_bps = 0
    discount_cents = round_half_up(Decimal(pre_discount) * volume_pct)

    # mobilization added AFTER discount, never discounted, exact constant
    grand_total_cents = (pre_discount - discount_cents) + MOBILIZATION_CENTS

    return {
        "priced_sqft": priced_sqft,
        "system_material_cents": system_material_cents,
        "prep_labor_cents": prep_labor_cents,
        "volume_discount_pct_bps": volume_discount_pct_bps,
        "discount_cents": discount_cents,
        "mobilization_cents": MOBILIZATION_CENTS,
        "grand_total_cents": grand_total_cents,
    }


# ---------------------------------------------------------------------------
# (3) financing_payment  (PRD §3.4)
# ---------------------------------------------------------------------------
def financing_payment(principal_cents, apr_bps, term_months):
    # monthly rate at full floating precision
    r = (apr_bps / 10000.0) / 12.0
    if r == 0:
        return round_half_up(Decimal(principal_cents) / Decimal(term_months))
    factor = (1 + r) ** term_months
    monthly = principal_cents * (r * factor) / (factor - 1)
    return round_half_up(Decimal(str(monthly)))


# ---------------------------------------------------------------------------
# (4) warranty_proration  (PRD §3.7)
# ---------------------------------------------------------------------------
def warranty_proration(covered_install_price_cents, months_elapsed, term_months, defect_type):
    remaining = max(0, term_months - months_elapsed)
    if defect_type == "PEEL":
        defect_factor = PEEL_FACTOR
    elif defect_type == "HOT_TIRE":
        defect_factor = HOT_TIRE_FACTOR
    else:
        defect_factor = Decimal(0)
    product = (Decimal(covered_install_price_cents)
               * (Decimal(remaining) / Decimal(term_months))
               * defect_factor)
    return round_half_up(product)


# ---------------------------------------------------------------------------
# (5) cure_window  (PRD §3.6)
# ---------------------------------------------------------------------------
def cure_window(install_date, coating_family):
    install_end = install_date + timedelta(hours=INSTALL_DURATION_HOURS)
    foot_traffic_ok_at = install_end + timedelta(hours=FOOT_TRAFFIC_HOURS)
    vehicle_base = install_end + timedelta(hours=VEHICLE_TRAFFIC_HOURS)
    if coating_family == "METALLIC":
        vehicle_traffic_ok_at = vehicle_base + timedelta(hours=METALLIC_EXTRA_CURE_HOURS)
    else:
        vehicle_traffic_ok_at = vehicle_base
    return install_end, foot_traffic_ok_at, vehicle_traffic_ok_at


# ---------------------------------------------------------------------------
# whole months floor between two UTC datetimes  (PRD §3.7 months_elapsed)
# ---------------------------------------------------------------------------
def whole_months_floor(start, end):
    """Whole calendar months elapsed from start to end, floored.

    A month is counted only when the same day-of-month (and time within the day)
    has been reached or passed.
    """
    if end < start:
        return 0
    months = (end.year - start.year) * 12 + (end.month - start.month)
    # If we have not yet reached the day/time anchor in the final month, drop one.
    if (end.day, end.hour, end.minute, end.second, end.microsecond) < \
       (start.day, start.hour, start.minute, start.second, start.microsecond):
        months -= 1
    return max(0, months)


def coverage_expiry(coverage_start_at, term_months):
    """coverage_start_at + term_months (calendar-month addition)."""
    total = coverage_start_at.month - 1 + term_months
    year = coverage_start_at.year + total // 12
    month = total % 12 + 1
    # clamp day to month length
    import calendar
    day = min(coverage_start_at.day, calendar.monthrange(year, month)[1])
    return coverage_start_at.replace(year=year, month=month, day=day)
