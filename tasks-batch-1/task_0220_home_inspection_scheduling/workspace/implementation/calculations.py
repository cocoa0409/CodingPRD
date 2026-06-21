"""Calculation engine (PRD §3.6-§3.8, scaffold §1.3).

All money is integer cents. Rounding is half-up, applied exactly where the PRD
pins it (the type-multiply step, the re-inspection discount step, and once per
defect in the risk score). Decimal is used for the rounding steps to avoid IEEE
754 drift.
"""
from decimal import Decimal, ROUND_HALF_UP

# Inspection-type fee multiplier (PRD §3.7).
TYPE_MULTIPLIER = {
    "BUYER": Decimal("1.00"),
    "SELLER": Decimal("0.90"),
    "FOUR_POINT": Decimal("0.75"),
    "WIND_MIT": Decimal("0.60"),
}

# Inspection-type base on-site minutes (PRD §3.4).
TYPE_BASE_MINUTES = {
    "BUYER": 180,
    "SELLER": 150,
    "FOUR_POINT": 90,
    "WIND_MIT": 60,
}

# Add-on fixed durations (PRD §3.4).
ADDON_DURATION = {
    "RADON": 30,
    "TERMITE": 20,
    "SEWER": 45,
}

# Defect severity weights (PRD §3.6).
DEFECT_WEIGHT = {
    "MINOR": 1,
    "MAJOR": 4,
    "CRITICAL": 10,
}
SCORE_SCALE = 100
COUNT_NORM = 3

# Severity band floors (PRD §3.6, inclusive on the floor).
MINOR_FLOOR = 1
MAJOR_FLOOR = 133
CRITICAL_FLOOR = 666

# Re-inspection discount banding (PRD §3.8).
BAND_LOW_CENTS = 50000
BAND_HIGH_CENTS = 100000
MAX_DISCOUNT = Decimal("0.90")


def round_half_up(value):
    """Round a Decimal to the nearest integer, ties away from zero (half up)."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def sqft_component_cents(square_footage, fs):
    """Marginal tiered square-footage component in cents (PRD §3.7)."""
    s = square_footage
    t1_max = fs["tier1_max_sqft"]
    t2_max = fs["tier2_max_sqft"]
    sqft_t1 = min(s, t1_max)
    sqft_t2 = max(0, min(s, t2_max) - t1_max)
    sqft_t3 = max(0, s - t2_max)
    return (
        sqft_t1 * fs["tier1_rate_cents_per_sqft"]
        + sqft_t2 * fs["tier2_rate_cents_per_sqft"]
        + sqft_t3 * fs["tier3_rate_cents_per_sqft"]
    )


def inspection_fee_cents(square_footage, inspection_type, fs, active_addon_prices):
    """Full fee for a given square footage (PRD §3.7).

    Order is pinned: tier component -> (base + tier) * type_mult rounded half up
    -> + flat ACTIVE add-on prices (not multiplied).
    """
    comp = sqft_component_cents(square_footage, fs)
    mult = TYPE_MULTIPLIER[inspection_type]
    typed = round_half_up(Decimal(fs["base_rate_cents"] + comp) * mult)
    addon_total = sum(active_addon_prices)
    return typed + addon_total


def reinspection_discount_fraction(parent_final_fee_cents, base_pct):
    """Select the discount fraction by the parent order's final-fee band (PRD §3.8)."""
    base = Decimal(str(base_pct))
    if parent_final_fee_cents < BAND_LOW_CENTS:
        d = base
    elif parent_final_fee_cents < BAND_HIGH_CENTS:
        d = base + Decimal("0.10")
    else:
        d = base + Decimal("0.20")
        if d > MAX_DISCOUNT:
            d = MAX_DISCOUNT
    return d


def reinspection_fee_cents(quoted_fee_cents, parent_final_fee_cents, base_pct):
    """Quoted fee discounted by the band-selected fraction, rounded half up."""
    d = reinspection_discount_fraction(parent_final_fee_cents, base_pct)
    return round_half_up(Decimal(quoted_fee_cents) * (Decimal("1") - d))


def order_duration_minutes(inspection_type, active_addon_durations):
    """Base type minutes + ACTIVE add-on minutes (PRD §3.4)."""
    base = TYPE_BASE_MINUTES[inspection_type]
    return base + sum(active_addon_durations)


def per_defect_points(severity):
    """Per-defect weighted points: round_half_up(weight * SCALE / NORM)."""
    weight = DEFECT_WEIGHT[severity]
    return round_half_up(Decimal(weight * SCORE_SCALE) / Decimal(COUNT_NORM))


def risk_score(defect_severities):
    """Sum of per-defect points (per-defect-then-sum order pinned, PRD §3.6)."""
    return sum(per_defect_points(sev) for sev in defect_severities)


def severity_band(final_risk_score):
    """Derive the band from final score; PASS at exactly 0 (PRD §3.6)."""
    f = final_risk_score
    if f == 0:
        return "PASS"
    if f < MAJOR_FLOOR:
        return "MINOR"
    if f < CRITICAL_FLOOR:
        return "MAJOR"
    return "CRITICAL"
