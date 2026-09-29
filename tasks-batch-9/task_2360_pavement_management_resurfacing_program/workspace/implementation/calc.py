"""Deterministic arithmetic for the pavement program (PRD 2.6, 2.7, 3.x).

Every rounding operation in this specification is round-half-up, so all
numeric work runs through Decimal. Nothing here uses float arithmetic or the
built-in round().
"""
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP, getcontext

getcontext().prec = 60

# ---------------------------------------------------------------- constants

FUNCTIONAL_CLASSES = ("ARTERIAL", "COLLECTOR", "LOCAL")
SURFACE_TYPES = ("ASPHALT", "COMPOSITE")
TREATMENTS = ("CRACK_SEAL", "MILL_AND_OVERLAY", "RECONSTRUCTION")
LAST_TREATMENT_TYPES = ("NONE",) + TREATMENTS
UTILITIES = ("WATER", "SEWER", "FRANCHISE_GAS", "FRANCHISE_TELECOM")

# PRD 2.7 — two-slope decay, keyed on functional_class.
DECAY = {
    "ARTERIAL": ("2.2", "1.6"),
    "COLLECTOR": ("1.8", "1.3"),
    "LOCAL": ("1.4", "1.0"),
}
KNEE_YEARS = 8

# PRD 3.3 — construction rate in cents per square yard.
BASE_RATE_CENTS_PER_SY = {
    "CRACK_SEAL": {"LOCAL": 350, "COLLECTOR": 420, "ARTERIAL": 500},
    "MILL_AND_OVERLAY": {"LOCAL": 2800, "COLLECTOR": 3300, "ARTERIAL": 4100},
    "RECONSTRUCTION": {"LOCAL": 9500, "COLLECTOR": 11000, "ARTERIAL": 13500},
}
MOBILIZATION_CENTS = {
    "CRACK_SEAL": 250000,
    "MILL_AND_OVERLAY": 850000,
    "RECONSTRUCTION": 850000,
}
SERVICE_LIFE_YEARS = {"CRACK_SEAL": 5, "MILL_AND_OVERLAY": 15, "RECONSTRUCTION": 30}
PCI_GAIN_CAP = {
    "CRACK_SEAL": "8.0",
    "MILL_AND_OVERLAY": "45.0",
    "RECONSTRUCTION": "100.0",
}

# PRD 3.8 — calendar years of moratorium by treatment placed.
MORATORIUM_YEARS = {"CRACK_SEAL": 1, "MILL_AND_OVERLAY": 3, "RECONSTRUCTION": 5}

# PRD 3.6
NOTICE_LEAD_HOURS = 72
NOTICE_BUFFER_HOURS = 24

# PRD 3.9
SLA_HOURS = {"HIGH": 72, "MEDIUM": 168, "LOW": 720}
CUT_FEE_CENTS_PER_SQFT = 850
CUT_FEE_MINIMUM_CENTS = 45000

# PRD 3.7
AWARD_TOLERANCE_PCT = Decimal("0.10")


# ------------------------------------------------------------------ helpers

def D(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    return Decimal(str(value))


def rhu(value, places=0):
    """Round half up to `places` decimal places."""
    quant = Decimal(1).scaleb(-places)
    return D(value).quantize(quant, rounding=ROUND_HALF_UP)


def num(value, places):
    """Round half up and hand back a JSON-friendly number."""
    return float(rhu(value, places))


def cents(value):
    return int(rhu(value, 0))


def clamp(value, low, high):
    value = D(value)
    low = D(low)
    high = D(high)
    if value < low:
        return low
    if value > high:
        return high
    return value


def whole_days(start, end):
    """Whole days from start to end, fraction discarded."""
    return math.floor((end - start).total_seconds() / 86400)


def whole_years(start, end):
    """Age in whole years: whole days / 365, fraction discarded (PRD 2.7)."""
    return math.floor(whole_days(start, end) / 365)


def add_calendar_years(instant, years):
    try:
        return instant.replace(year=instant.year + years)
    except ValueError:  # 29 February
        return instant.replace(year=instant.year + years, month=2, day=28)


# ------------------------------------------------------- condition and bands

def condition_band(index):
    value = D(index)
    if value >= D("70.0"):
        return "GOOD"
    if value >= D("50.0"):
        return "FAIR"
    if value >= D("25.0"):
        return "POOR"
    return "FAILED"


def segment_area_sy(length_ft, width_ft):
    return num(D(length_ft) * D(width_ft) / D(9), 2)


def model_projected_condition_index(segment, at_instant):
    """MODEL_PROJECTED variant (PRD 2.7)."""
    anchor = segment.get("last_treatment_date") or segment["created_at"]
    age = whole_years(anchor, at_instant)
    pre = D(segment["decay_coefficient"])
    knee = D(segment["decay_knee_coefficient"])
    beyond = max(0, age - KNEE_YEARS)
    raw = D(segment["baseline_condition_index"]) - pre * D(age) - knee * D(beyond)
    return num(clamp(raw, 0, 100), 1)


def survey_measured_condition_index(segment, obs):
    """SURVEY_MEASURED variant with the pinned rounding order (PRD 3.2).

    Returns (deduct_total, measured_condition_index).
    """
    length = D(segment["length_ft"])
    area_sqft = length * D(segment["width_ft"])
    alligator_pct = rhu(D(obs["alligator_cracking_sqft"]) / area_sqft * D(100), 2)
    patching_pct = rhu(D(obs["patching_sqft"]) / area_sqft * D(100), 2)
    crack_density = rhu(D(obs["longitudinal_cracking_lf"]) / length * D(100), 2)
    rut_excess = max(D(0), D(obs["rutting_depth_in"]) - D("0.25"))
    iri_excess = max(D(0), D(obs["iri_in_per_mi"]) - D("95.0"))
    deduct_raw = (
        D("0.45") * alligator_pct
        + D("0.18") * crack_density
        + D("40.0") * rut_excess
        + D("0.12") * patching_pct
        + D("0.08") * iri_excess
    )
    coverage_factor = rhu(D(100) / D(obs["sample_coverage_pct"]), 4)
    deduct_total = rhu(deduct_raw * coverage_factor, 2)
    measured = rhu(clamp(D(100) - deduct_total, 0, 100), 1)
    return float(deduct_total), float(measured)


def area_weighted_index(pairs):
    """pairs: iterable of (area_sy, index). Returns 1-dp mean or None."""
    total_area = D(0)
    total_product = D(0)
    for area, index in pairs:
        total_area += D(area)
        total_product += D(area) * D(index)
    if total_area == 0:
        return None
    return num(total_product / total_area, 1)


# ---------------------------------------------------------- candidate pricing

def select_treatment(snapshot_index):
    value = D(snapshot_index)
    if value >= D("70.0"):
        return "CRACK_SEAL"
    if value >= D("40.0"):
        return "MILL_AND_OVERLAY"
    return "RECONSTRUCTION"


def width_factor(width_ft):
    raw = D(1) + D("0.01") * (D(width_ft) - D("24.0"))
    return rhu(clamp(raw, "1.00", "1.25"), 4)


def condition_penalty(snapshot_index):
    band = condition_band(snapshot_index)
    if band == "FAILED":
        return D("1.12")
    if band == "POOR":
        return D("1.05")
    return D("1.00")


def construction_cost_cents(area_sy, treatment_type, functional_class,
                           width_ft, snapshot_index):
    rate = D(BASE_RATE_CENTS_PER_SY[treatment_type][functional_class])
    product = (
        D(area_sy) * rate * width_factor(width_ft)
        * condition_penalty(snapshot_index)
    )
    return cents(product)


def candidate_pricing(segment, treatment_type, snapshot_index):
    """Returns the four priced candidate fields (PRD 3.3)."""
    estimated = construction_cost_cents(
        segment["area_sy"], treatment_type, segment["functional_class"],
        segment["width_ft"], snapshot_index,
    ) + MOBILIZATION_CENTS[treatment_type]
    life = SERVICE_LIFE_YEARS[treatment_type]
    gain = rhu(
        min(D(PCI_GAIN_CAP[treatment_type]), D(100) - D(snapshot_index)), 1
    )
    benefit = rhu(gain * D(life) * D(segment["area_sy"]), 2)
    cost_thousands = D(estimated) / D(100000)
    ratio = rhu(benefit / cost_thousands, 4) if cost_thousands != 0 else D(0)
    return {
        "expected_service_life_years": life,
        "treatment_pci_gain": float(gain),
        "estimated_cost_cents": estimated,
        "benefit_cost_ratio": float(ratio),
    }


# ------------------------------------------------------------ bundle pricing

def contingency_pct(base_cents):
    base = D(base_cents)
    if base < D(5000000):
        return D("0.15")
    if base < D(50000000):
        return D("0.10")
    return D("0.07")


# --------------------------------------------------------- acceptance testing

def density_factor(core_density_pct):
    value = D(core_density_pct)
    if value >= D("96.0"):
        return D("1.00")
    if value >= D("94.0"):
        return D("0.98")
    if value >= D("92.0"):
        return D("0.95")
    return D("0.00")


def smoothness_factor(iri):
    value = D(iri)
    if value <= D("60.0"):
        return D("1.02")
    if value <= D("95.0"):
        return D("1.00")
    if value <= D("120.0"):
        return D("0.97")
    return D("0.00")


def thickness_factor(thickness_in, design_thickness_in):
    value = D(thickness_in)
    design = D(design_thickness_in)
    if value >= design:
        return D("1.00")
    if value >= design - D("0.25"):
        return D("0.96")
    return D("0.00")


def acceptance_pay_factor(core_density_pct, iri, thickness_in,
                          design_thickness_in):
    """Returns (computed_pay_factor, computed_outcome)."""
    d = density_factor(core_density_pct)
    s = smoothness_factor(iri)
    t = thickness_factor(thickness_in, design_thickness_in)
    if d == 0 or s == 0 or t == 0:
        return float(rhu(0, 4)), "FAIL"
    factor = rhu(min(D("1.02"), d * s * t), 4)
    outcome = "PASS" if factor >= D("0.95") else "FAIL"
    return float(factor), outcome


# ------------------------------------------------------- contractor scoring

def score_components(passed, failed, days_late, remediation_events):
    if passed + failed == 0:
        quality = rhu("100.00", 2)
    else:
        quality = rhu(D(100) * D(passed) / D(passed + failed), 2)
    schedule = rhu(clamp(D(100) - D("2.5") * D(days_late), 0, 100), 2)
    remediation = rhu(clamp(D(100) - D("8.0") * D(remediation_events), 0, 100), 2)
    composite = rhu(
        D("0.45") * quality + D("0.30") * schedule + D("0.25") * remediation, 1
    )
    return {
        "quality": float(quality),
        "schedule": float(schedule),
        "remediation": float(remediation),
        "composite": float(composite),
    }


def standing_for(interim_score):
    value = D(interim_score)
    if value >= D("80.0"):
        return "GOOD_STANDING"
    if value >= D("60.0"):
        return "WATCH"
    return "SUSPENDED"


# -------------------------------------------------------------- cut permits

def moratorium_remaining_days(moratorium_until, now):
    if moratorium_until is None:
        return 0
    seconds = math.floor((moratorium_until - now).total_seconds())
    return max(0, seconds // 86400)


def fee_tier(remaining_days):
    if remaining_days >= 1096:
        return D("3.0")
    if remaining_days >= 366:
        return D("2.0")
    if remaining_days >= 1:
        return D("1.5")
    return D("1.0")


def cut_permit_fee(cut_area_sqft, moratorium_until, emergency, now):
    """Returns (moratorium_remaining_days, fee_multiplier, degradation_fee_cents)."""
    remaining = moratorium_remaining_days(moratorium_until, now)
    tier = fee_tier(remaining)
    if emergency:
        multiplier = max(D("1.0"), tier - D("0.5"))
    else:
        multiplier = tier
    multiplier = rhu(multiplier, 1)
    base_fee = max(CUT_FEE_MINIMUM_CENTS,
                   cents(D(cut_area_sqft) * D(CUT_FEE_CENTS_PER_SQFT)))
    fee = cents(D(base_fee) * multiplier)
    return int(remaining), float(multiplier), fee


# ------------------------------------------------------------ service level

def sla_due_at(created_at, severity):
    return created_at + timedelta(hours=SLA_HOURS[severity])
