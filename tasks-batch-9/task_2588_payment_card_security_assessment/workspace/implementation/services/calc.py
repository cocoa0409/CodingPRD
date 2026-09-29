"""Pure calculation rules (PRD section 2.9 precision + SCAFFOLD 1.3 calculations).

All rounding is HALF UP; nothing here uses binary floating point arithmetic for
money, percentages or scores.
"""

from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

# --- requirement family risk points ---------------------------------------- #
FAMILY_RISK_POINTS = {
    "R1": 3, "R2": 2, "R3": 5, "R4": 4, "R5": 2, "R6": 4,
    "R7": 3, "R8": 3, "R9": 2, "R10": 4, "R11": 3, "R12": 1,
}

# --- component sampling ----------------------------------------------------- #
STRATUM_ORDER = ["SERVER", "NETWORK_DEVICE", "POS_TERMINAL", "APPLICATION", "DATABASE"]
SAMPLE_RATE = Decimal("0.25")
MIN_PER_STRATUM = 2

# --- facility sampling ------------------------------------------------------ #
FACILITY_SAMPLE_RATE = Decimal("0.34")
MIN_FACILITIES = 1

# --- compensating control worksheet rigor ---------------------------------- #
DEPTH_POINTS_PER_REF = 20
DEPTH_POINTS_CAP = 100
THIN_CONTROL_REF_FLOOR = 2
THIN_CONTROL_SCORE_CAP = Decimal("40.00")
RISK_OFFSET_BASE = 100
RISK_OFFSET_PER_POINT = 15
DEPTH_WEIGHT = Decimal("0.40")
MONITORING_WEIGHT = Decimal("0.35")
RISK_OFFSET_WEIGHT = Decimal("0.25")
CCW_RIGOR_FLOOR = Decimal("70.00")
CCW_MONITORING_CEILING = 30

# --- fee ------------------------------------------------------------------- #
HOURLY_RATE = Decimal("250.00")
BASE_HOURS = 160
PER_SAMPLE_COMPONENT_HOURS = 12
PER_FACILITY_HOURS = 30
PER_ACCEPTED_CCW_HOURS = 20
L1_SURCHARGE_PCT = Decimal("0.08")
VOLUME_TIERS = [
    (Decimal("120000"), Decimal("0.10")),
    (Decimal("90000"), Decimal("0.06")),
    (Decimal("60000"), Decimal("0.03")),
]

# --- scanning -------------------------------------------------------------- #
HIGH_CVSS_THRESHOLD = Decimal("4.0")
SCAN_WINDOW_DAYS = 90

# --- reassessment ---------------------------------------------------------- #
SCOPE_CHANGE_THRESHOLD = 3
REASSESSMENT_INTERVAL_DAYS = 365
ACCELERATED_REASSESSMENT_DAYS = 90
SCOPE_AFFECTING_CHANGE_TYPES = (
    "COMPONENT_ADDED_TO_CDE",
    "SEGMENT_RECLASSIFIED",
    "THIRD_PARTY_ADDED",
)

ELIGIBLE_SCOPE_CLASSES = ("CDE", "CONNECTED")


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def quant(value, places):
    exponent = Decimal(1).scaleb(-places)
    return dec(value).quantize(exponent, rounding=ROUND_HALF_UP)


def money(value):
    return quant(value, 2)


def as_float(value, places):
    return float(quant(value, places))


def ceil_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_CEILING))


# --------------------------------------------------------------------------- #
# component_sample_allocation
# --------------------------------------------------------------------------- #
def stratum_allocation(population_by_stratum):
    """Per-stratum ceiling before summation; strata iterated in the pinned order."""
    allocations = {}
    for stratum in STRATUM_ORDER:
        population = int(population_by_stratum.get(stratum, 0) or 0)
        if population == 0:
            allocations[stratum] = 0
            continue
        allocations[stratum] = min(
            population,
            max(MIN_PER_STRATUM, ceil_int(dec(population) * SAMPLE_RATE)),
        )
    return allocations


def coverage_ratio(sample_size, eligible_count):
    if not eligible_count:
        return Decimal("0.0000")
    return quant(dec(sample_size) / dec(eligible_count), 4)


# --------------------------------------------------------------------------- #
# facility_sample_selection
# --------------------------------------------------------------------------- #
def facility_sample(facility_names):
    """facility_names: iterable of the eligible population's facility names."""
    distinct = sorted(set(facility_names))
    population = len(distinct)
    if population == 0:
        return 0, 0, []
    size = min(population, max(MIN_FACILITIES, ceil_int(dec(population) * FACILITY_SAMPLE_RATE)))
    return population, size, distinct[:size]


# --------------------------------------------------------------------------- #
# ccw_rigor_score
# --------------------------------------------------------------------------- #
def monitoring_factor_for(interval_days):
    if interval_days <= 1:
        return Decimal("100")
    if interval_days <= 7:
        return Decimal("80")
    if interval_days <= 30:
        return Decimal("55")
    return Decimal("25")


def ccw_rigor(control_refs, monitoring_interval_days, risk_points):
    distinct_refs = len(set(control_refs or []))
    depth = min(Decimal(DEPTH_POINTS_CAP), Decimal(DEPTH_POINTS_PER_REF) * Decimal(distinct_refs))
    monitoring = monitoring_factor_for(int(monitoring_interval_days))
    risk_offset = max(
        Decimal(0),
        Decimal(RISK_OFFSET_BASE) - Decimal(RISK_OFFSET_PER_POINT) * Decimal(int(risk_points)),
    )
    raw = DEPTH_WEIGHT * depth + MONITORING_WEIGHT * monitoring + RISK_OFFSET_WEIGHT * risk_offset
    thin = distinct_refs < THIN_CONTROL_REF_FLOOR
    score = min(raw, THIN_CONTROL_SCORE_CAP) if thin else raw
    return {
        "control_depth_points": quant(depth, 2),
        "monitoring_factor": quant(monitoring, 2),
        "risk_offset_points": quant(risk_offset, 2),
        "rigor_score": quant(score, 2),
        "thin_control_capped": thin,
    }


# --------------------------------------------------------------------------- #
# compliance_projection
# --------------------------------------------------------------------------- #
def percentage(numerator, denominator):
    if not denominator:
        return Decimal("0.00")
    return quant(dec(numerator) / dec(denominator) * Decimal(100), 2)


# --------------------------------------------------------------------------- #
# assessment_fee_total
# --------------------------------------------------------------------------- #
def volume_tier_for(subtotal):
    for threshold, rate in VOLUME_TIERS:
        if subtotal >= threshold:
            return rate
    return Decimal("0.00")


def assessment_fee(merchant_level, component_sample_size, facility_sample_size,
                   accepted_ccw_count):
    """Returns (estimated_hours, assessment_fee_total) following the seven steps."""
    hours = (
        BASE_HOURS
        + PER_SAMPLE_COMPONENT_HOURS * int(component_sample_size or 0)
        + PER_FACILITY_HOURS * int(facility_sample_size or 0)
        + PER_ACCEPTED_CCW_HOURS * int(accepted_ccw_count or 0)
    )
    base = money(dec(hours) * HOURLY_RATE)
    surcharge = money(base * L1_SURCHARGE_PCT) if merchant_level == "L1" else Decimal("0.00")
    subtotal = base + surcharge
    tier = volume_tier_for(subtotal)
    discount = money(subtotal * tier)
    total = money(subtotal - discount)
    return hours, total


def severity_for_risk_points(risk_points):
    points = int(risk_points)
    if points >= 5:
        return "CRITICAL"
    if points == 4:
        return "HIGH"
    if points == 3:
        return "MEDIUM"
    return "LOW"


def severity_class_for_cvss(cvss_score):
    return "HIGH_OR_ABOVE" if dec(cvss_score) >= HIGH_CVSS_THRESHOLD else "LOW"
