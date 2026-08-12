"""Calculation rules (SCAFFOLD §1.3). Pure functions; money/masses via Decimal."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

# sludge_mass_estimate constants
SLUDGE_RATIO = {
    "GASOLINE": Decimal("0.02"),
    "DISTILLATE": Decimal("0.03"),
    "JET": Decimal("0.015"),
    "CRUDE": Decimal("0.08"),
    "CHEMICAL": Decimal("0.05"),
    "VEGOIL": Decimal("0.04"),
}
SURFACE_FACTOR = {
    "LOW": Decimal("0.5"),
    "MEDIUM": Decimal("1.0"),
    "HIGH": Decimal("2.0"),
}

# contractor_safety_score constants
SCORE_BASE = Decimal("100.0")
INCIDENT_FACTOR = Decimal("2.0")
VIOLATION_FACTOR = Decimal("1.0")
NEAR_MISS_FACTOR = Decimal("0.25")
TRAINING_FACTOR = Decimal("0.5")
ROLLING_WINDOW_DAYS = 365

# flush_volume_liters constants
BASE_FACTOR = {
    "LOW": Decimal("0.02"),
    "MEDIUM": Decimal("0.035"),
    "HIGH": Decimal("0.05"),
}
CLASS_MULTIPLIER = {
    "COMPATIBLE_DIRECT": Decimal("0.5"),
    "REQUIRES_FLUSH": Decimal("1.0"),
    "REQUIRES_FULL_STRIP": Decimal("1.8"),
}
LINES_ALLOWANCE_L = 5000
MIN_FLUSH_L = 2000
MAX_FLUSH_L = 200000

# changeover_compatibility constants
FORBIDDEN_PAIRS = [("CRUDE", "JET"), ("JET", "CRUDE")]
FULL_STRIP_GROUPS = {"CHEM", "VEG"}

# waste_disposal_cost_cents constants
HAZARD_MULTIPLIER = {
    "NON_HAZARDOUS": Decimal("1.0"),
    "HAZARDOUS": Decimal("2.5"),
}

# job_invoice_total_cents constants
FLUSH_RATE_CENTS_PER_LITER = 2
TIER1_MIN_CENTS = 1000000
TIER1_PCT = Decimal("0.10")
TIER2_MIN_CENTS = 500000
TIER2_PCT = Decimal("0.05")

# gas_free_limits_check constants
LEL_LIMIT_PCT = Decimal("10.0")
O2_MIN_PCT = Decimal("19.5")
O2_MAX_PCT = Decimal("23.5")
H2S_LIMIT_PPM = Decimal("10.0")
BENZENE_LIMIT_PPM = Decimal("1.0")
CERT_VALIDITY_HOURS = 12
REVALIDATE_EXTENSION_HOURS = 6

# tank_window_conflict_check
BUFFER_HOURS = 24


def changeover_class(from_product, to_product):
    """Evaluated strictly in this order (PRD §3.4)."""
    if from_product["compatibility_group"] == to_product["compatibility_group"]:
        return "COMPATIBLE_DIRECT"
    pair = (from_product["family"], to_product["family"])
    if pair in FORBIDDEN_PAIRS:
        return "FORBIDDEN"
    if (from_product["compatibility_group"] in FULL_STRIP_GROUPS
            or to_product["compatibility_group"] in FULL_STRIP_GROUPS):
        return "REQUIRES_FULL_STRIP"
    return "REQUIRES_FLUSH"


def sludge_mass_kg(volume_liters, from_product, tank):
    """Whole kg, round-half-up. Used for both PROVISIONAL (sounding) and
    FINAL_BASIS (metered) variants — identical formula, different volume source."""
    raw = (Decimal(volume_liters) * SLUDGE_RATIO[from_product["family"]]
           + Decimal(tank["capacity_m3"]) * SURFACE_FACTOR[from_product["viscosity_class"]])
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def flush_volume_liters(tank, from_product, changeover, lines_included):
    """Ceiling applied exactly once at the final step, then clamped."""
    if changeover == "FORBIDDEN":
        return None
    raw = (Decimal(tank["capacity_m3"]) * 1000
           * BASE_FACTOR[from_product["viscosity_class"]]
           * CLASS_MULTIPLIER[changeover])
    if lines_included:
        raw += LINES_ALLOWANCE_L
    v = int(raw.to_integral_value(rounding=ROUND_CEILING))
    return min(MAX_FLUSH_L, max(MIN_FLUSH_L, v))


def safety_score(events, variant, now_dt):
    """2 decimal places, round-half-up, clamped to [0.00, 100.00].
    ROLLING_12MO includes events with occurred_at >= now - 365d (inclusive)."""
    score = SCORE_BASE
    cutoff = now_dt - timedelta(days=ROLLING_WINDOW_DAYS)
    for ev in events:
        if variant == "ROLLING_12MO" and ev["occurred_at"] < cutoff:
            continue
        w = Decimal(ev["severity_weight"])
        kind = ev["kind"]
        if kind == "INCIDENT":
            score -= INCIDENT_FACTOR * w
        elif kind == "VIOLATION":
            score -= VIOLATION_FACTOR * w
        elif kind == "NEAR_MISS":
            score -= NEAR_MISS_FACTOR * w
        elif kind == "TRAINING_CREDIT":
            score += TRAINING_FACTOR * w
    if score < 0:
        score = Decimal("0")
    if score > 100:
        score = Decimal("100")
    return score.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def line_cost_cents(kg, rate_cents_per_kg, hazard_class):
    """Per-line round-half-up to whole cents FIRST; the caller sums (pinned order)."""
    raw = (Decimal(kg) * Decimal(str(rate_cents_per_kg))
           * HAZARD_MULTIPLIER[hazard_class])
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def invoice_total_cents(job):
    """Pinned evaluation order (PRD §3.8): waste -> flush charge -> pre_total ->
    tier off pre_total -> discount on base fee (only rounding step) -> total."""
    waste = job["waste_cost_cents"] or 0
    flush_charge = (job["flush_volume_liters"] or 0) * FLUSH_RATE_CENTS_PER_LITER
    pre_total = job["base_service_fee_cents"] + waste + flush_charge
    if pre_total >= TIER1_MIN_CENTS:
        tier = TIER1_PCT
    elif pre_total >= TIER2_MIN_CENTS:
        tier = TIER2_PCT
    else:
        tier = Decimal("0")
    discount = int((Decimal(job["base_service_fee_cents"]) * tier).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))
    return pre_total - discount


def mass_balance_passes(job, terminal):
    """Inclusive boundary: delta exactly equal to the tolerance passes.
    Tolerance bound computed to 2 decimal places, round-half-up."""
    expected = job["expected_solids_kg"]
    if expected is None:
        return False
    actual = job["shipped_solids_kg"] or 0
    bound = (Decimal(expected)
             * Decimal(str(terminal["mass_balance_tolerance_pct"]))
             / Decimal(100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return abs(Decimal(actual) - Decimal(expected)) <= bound


def gas_free_within_limits(lel_pct, o2_pct, h2s_ppm, benzene_ppm):
    """LEL and benzene STRICT upper bounds; O2 band CLOSED; H2S INCLUSIVE."""
    lel = Decimal(str(lel_pct))
    o2 = Decimal(str(o2_pct))
    h2s = Decimal(str(h2s_ppm))
    benz = Decimal(str(benzene_ppm))
    return (lel < LEL_LIMIT_PCT
            and O2_MIN_PCT <= o2 <= O2_MAX_PCT
            and h2s <= H2S_LIMIT_PPM
            and benz < BENZENE_LIMIT_PPM)
