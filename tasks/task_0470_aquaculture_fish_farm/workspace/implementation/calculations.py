"""The six calculation rules (SCAFFOLD §1.3 / PRD §3). All rounding is 2 dp,
round-half-up (PRD §2.6). Time-gated rules use the logical clock (PRD §2.11)."""
from decimal import Decimal, ROUND_HALF_UP

from common import D, round2, days_between, add_days
from db import store

# --- estimate_biomass constants (PRD §3.2) ---
GROWTH_TIER1_DAYS = 90
GROWTH_TIER2_DAYS = 180
SURVIVAL_DECAY_PER_DAY = Decimal("0.0005")
SURVIVAL_FLOOR = Decimal("0.80")

# --- compute_fcr constant (PRD §3.3 / §3.7) ---
FCR_GAIN_FLOOR = Decimal("0.01")

# --- compute_order_total discount tiers (PRD §3.10) ---
DISCOUNT_TIERS = {
    "NONE": Decimal("0.00"),
    "BRONZE": Decimal("0.05"),
    "SILVER": Decimal("0.10"),
    "GOLD": Decimal("0.15"),
}

# --- classify_reading thresholds (PRD §3.4) ---
DO_CRITICAL = Decimal("4.0")
DO_WARNING = Decimal("6.0")
NH3_CRITICAL = Decimal("1.0")
NH3_WARNING = Decimal("0.5")


def days_elapsed_since(stocked_at_dt):
    """Whole days elapsed between stocked_at and the logical clock (floor)."""
    return days_between(store.clock, stocked_at_dt)


def estimate_biomass(cohort, species, stocked_at_dt):
    """PRD §3.2 growth model. Returns estimated_biomass_kg rounded to 2 dp."""
    days = days_elapsed_since(stocked_at_dt)
    if days < 0:
        days = 0
    if days <= GROWTH_TIER1_DAYS:
        growth_factor = Decimal("1.00")
    elif days <= GROWTH_TIER2_DAYS:
        growth_factor = Decimal("0.75")
    else:
        growth_factor = Decimal("0.50")

    base_growth = D(species["base_daily_growth_g"])
    stocked_avg = D(cohort["stocked_avg_weight_g"])
    target = D(species["target_market_weight_g"])

    est_avg_weight_g = stocked_avg + D(days) * base_growth * growth_factor
    if est_avg_weight_g > target:
        est_avg_weight_g = target

    survival = Decimal("1") - SURVIVAL_DECAY_PER_DAY * D(days)
    if survival < SURVIVAL_FLOOR:
        survival = SURVIVAL_FLOOR

    biomass = D(cohort["fish_count"]) * est_avg_weight_g * survival / Decimal("1000")
    return float(biomass.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def provisional_fcr(cohort):
    """PRD §3.3. Provisional FCR uses the growth-model estimate for the gain."""
    estimated = D(cohort["estimated_biomass_kg"])
    stocked_biomass = D(cohort["fish_count"]) * D(cohort["stocked_avg_weight_g"]) / Decimal("1000")
    gain = estimated - stocked_biomass
    if gain < FCR_GAIN_FLOOR:
        gain = FCR_GAIN_FLOOR
    fcr = D(cohort["cumulative_feed_kg"]) / gain
    return float(fcr.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def final_fcr(cohort, harvested_fish_count, harvested_live_weight_kg):
    """PRD §3.7. Final FCR uses actual landed weight for the gain."""
    stocked_equiv = D(harvested_fish_count) * D(cohort["stocked_avg_weight_g"]) / Decimal("1000")
    gain = D(harvested_live_weight_kg) - stocked_equiv
    if gain < FCR_GAIN_FLOOR:
        gain = FCR_GAIN_FLOOR
    fcr = D(cohort["cumulative_feed_kg"]) / gain
    return float(fcr.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def estimate_processing_yield(input_live_weight_kg, default_processing_yield_pct):
    """PRD §3.9 estimated yield = input live weight * species default yield pct."""
    return round2(D(input_live_weight_kg) * D(default_processing_yield_pct))


def compute_treatment_window(started_at_dt, duration_days, withdrawal_days):
    """PRD §3.7. Returns (treatment_end_at, withdrawal_end_at) as datetimes."""
    treatment_end = add_days(started_at_dt, duration_days)
    withdrawal_end = add_days(treatment_end, withdrawal_days)
    return treatment_end, withdrawal_end


def classify_reading(dissolved_oxygen_mg_l, ammonia_mg_l):
    """PRD §3.4 threshold classification. DO strict <, ammonia strict >."""
    do = D(dissolved_oxygen_mg_l)
    nh3 = D(ammonia_mg_l)
    if do < DO_CRITICAL or nh3 > NH3_CRITICAL:
        return "CRITICAL"
    if do < DO_WARNING or nh3 > NH3_WARNING:
        return "WARNING"
    return "NORMAL"


def severity_to_posture(severity):
    """Reading-derived posture (PRD §3.4)."""
    if severity == "CRITICAL":
        return "FROZEN"
    if severity == "WARNING":
        return "RESTRICTED"
    return "OPEN"


_POSTURE_SEVERITY = {"OPEN": 0, "RESTRICTED": 1, "FROZEN": 2}


def more_severe(a, b):
    """Return the more severe of two postures (PRD §2.7), treating None as OPEN."""
    a = a or "OPEN"
    b = b or "OPEN"
    return a if _POSTURE_SEVERITY[a] >= _POSTURE_SEVERITY[b] else b


def compute_order_total(lines_with_lots, discount_tier):
    """PRD §3.10 pinned rounding: per-line round, sum, discount, final round.
    lines_with_lots: iterable of (line, lot)."""
    summed = Decimal("0")
    for line, lot in lines_with_lots:
        subtotal = (D(line["weight_kg"]) * D(lot["price_per_kg"])).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP)
        summed += subtotal
    tier_pct = DISCOUNT_TIERS[discount_tier]
    total = (summed * (Decimal("1") - tier_pct)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(total)


def line_subtotal(weight_kg, price_per_kg):
    """PRD §3.10 per-line subtotal, rounded to 2 dp before summation."""
    return round2(D(weight_kg) * D(price_per_kg))
