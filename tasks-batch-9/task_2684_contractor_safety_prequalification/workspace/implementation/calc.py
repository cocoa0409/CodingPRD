"""Domain constants and every calculation rule from PRD sections 2.7 and 3.x."""
import calendar
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

# ------------------------------------------------------------------ enums ----

GRADING_POLICIES = ("STRICT", "BALANCED")
HAZARD_CLASSES = ("GENERAL", "HEIGHTS", "CONFINED_SPACE", "ELECTRICAL", "HOT_WORK", "EXCAVATION")
TRADE_CODES = (
    "GENERAL_BUILDING",
    "ELECTRICAL_TRADE",
    "MECHANICAL_TRADE",
    "SCAFFOLDING",
    "ROOFING",
    "EARTHWORK",
)
COVERAGE_TYPES = ("GL", "WC", "AUTO", "UMBRELLA")
CONTRACTOR_STATUSES = ("ACTIVE", "SUSPENDED", "DEBARRED")
GRADES = ("A", "B", "C", "F")
SITE_MIN_GRADES = ("A", "B", "C")
PROGRAM_TYPES = (
    "HAZCOM",
    "DISCIPLINE_POLICY",
    "FALL_PROTECTION",
    "CONFINED_SPACE",
    "LOTO",
    "HOT_WORK",
    "EXCAVATION",
)
QUALIFICATION_CODES = (
    "OSHA10",
    "OSHA30",
    "FALL_PROTECTION_COMPETENT",
    "CONFINED_SPACE_ENTRANT",
    "LOTO_AUTHORIZED",
    "HOT_WORK_PERMIT",
    "EXCAVATION_COMPETENT",
)
PREQUAL_STATUSES = (
    "DRAFT",
    "SUBMITTED",
    "UNDER_REVIEW",
    "APPROVED",
    "CONDITIONAL",
    "REJECTED",
    "SUSPENDED",
    "EXPIRED",
)
AUDIT_STATES = ("NOT_SELECTED", "SELECTED", "PASSED", "FAILED")
STAT_VERIFICATION_STATUSES = ("PENDING", "VERIFIED", "REJECTED")
PROGRAM_REVIEW_STATUSES = ("SUBMITTED", "ACCEPTED", "DEFICIENT", "WAIVED")
PLAN_STATUSES = ("OPEN", "SUBMITTED", "ACCEPTED", "REJECTED", "OVERDUE")
GRANT_STATUSES = ("GRANTED", "REVOKED", "EXPIRED")
REVOCATION_REASONS = ("CLIENT_REVOKED", "PREQUAL_SUSPENDED", "PREQUAL_EXPIRED", "PREQUAL_REJECTED")
SEVERITIES = ("FIRST_AID", "RECORDABLE", "LOST_TIME", "FATALITY")
INCIDENT_REVIEW_STATUSES = ("OPEN", "CLOSED")
REQUIREMENT_CODES = ("TRIR", "DART", "EMR", "CITATION_POINTS", "HAZARD_CLASS")
VARIANCE_STATUSES = ("REQUESTED", "APPROVED", "DENIED")
LINK_STATUSES = ("ACTIVE", "TERMINATED")
LIFECYCLE_STATUSES = ("NOT_YET_EFFECTIVE", "CURRENT", "EXPIRING_SOON", "LAPSED", "SUPERSEDED")

HIGH_HAZARD_CLASSES = frozenset(
    ["HEIGHTS", "CONFINED_SPACE", "ELECTRICAL", "HOT_WORK", "EXCAVATION"]
)

# -------------------------------------------------------------- constants ----

OSHA_BASIS = Decimal("200000")
CITATION_WEIGHT_WILLFUL = 5
CITATION_WEIGHT_SERIOUS = 2
CITATION_WEIGHT_OTHER = 1
CONDITIONAL_CURE_DAYS = 90
ACCESS_COOLDOWN_HOURS = 24
INCIDENT_LOOKBACK_DAYS = 365
EXPIRING_SOON_DAYS = 30
AGGREGATE_DEPLETION_PER_INCIDENT = 250000
FLOW_DOWN_GL_OCCURRENCE_FLOOR = 500000

PER_OCCURRENCE_FLOORS = {"GL": 1000000, "WC": 500000, "AUTO": 1000000, "UMBRELLA": 2000000}
AGGREGATE_FLOORS = {"GL": 2000000, "WC": 1000000, "AUTO": 1000000, "UMBRELLA": 4000000}
TIER_COVERAGE_MULTIPLIER = {1: Decimal("1.0"), 2: Decimal("1.5"), 3: Decimal("1.5")}
TIGHTENING_FACTOR = {1: Decimal("1.00"), 2: Decimal("0.85"), 3: Decimal("0.70")}

SEVERITY_RANK = {"FIRST_AID": 1, "RECORDABLE": 2, "LOST_TIME": 3, "FATALITY": 4}
SEVERE_SEVERITIES = frozenset(["RECORDABLE", "LOST_TIME", "FATALITY"])
REVIEW_FLAG_SEVERITIES = frozenset(["LOST_TIME", "FATALITY"])
GRADE_RANK = {"F": 0, "C": 1, "B": 2, "A": 3}

GRADE_BANDS = {
    "BALANCED": (("A", Decimal("85.00")), ("B", Decimal("70.00")), ("C", Decimal("55.00"))),
    "STRICT": (("A", Decimal("90.00")), ("B", Decimal("78.00")), ("C", Decimal("66.00"))),
}

PROGRAM_REQUIREMENTS = {
    "GENERAL": ["HAZCOM", "DISCIPLINE_POLICY"],
    "HEIGHTS": ["FALL_PROTECTION"],
    "CONFINED_SPACE": ["CONFINED_SPACE"],
    "ELECTRICAL": ["LOTO"],
    "HOT_WORK": ["HOT_WORK"],
    "EXCAVATION": ["EXCAVATION"],
}

QUALIFICATION_REQUIREMENTS = {
    "GENERAL": ["OSHA10"],
    "HEIGHTS": ["OSHA30", "FALL_PROTECTION_COMPETENT"],
    "CONFINED_SPACE": ["OSHA30", "CONFINED_SPACE_ENTRANT"],
    "ELECTRICAL": ["OSHA30", "LOTO_AUTHORIZED"],
    "HOT_WORK": ["OSHA10", "HOT_WORK_PERMIT"],
    "EXCAVATION": ["OSHA30", "EXCAVATION_COMPETENT"],
}

METRIC_ORDER = ("TRIR", "DART", "EMR", "CITATION_POINTS")

# ---------------------------------------------------------------- rounding ----

Q4 = Decimal("0.0001")
Q2 = Decimal("0.01")
Q0 = Decimal("1")


def q4(value):
    return Decimal(value).quantize(Q4, rounding=ROUND_HALF_UP)


def q2(value):
    return Decimal(value).quantize(Q2, rounding=ROUND_HALF_UP)


def q0(value):
    return int(Decimal(value).quantize(Q0, rounding=ROUND_HALF_UP))


def whole_days(start, end):
    """Complete 86,400-second days between two instants, truncated toward zero."""
    seconds = (end - start).total_seconds()
    return int(seconds / 86400)


def add_months(instant, months):
    """Calendar-month arithmetic keeping the day of month, clamped to month length."""
    total = instant.month - 1 + int(months)
    year = instant.year + total // 12
    month = total % 12 + 1
    day = min(instant.day, calendar.monthrange(year, month)[1])
    return instant.replace(year=year, month=month, day=day)


# ------------------------------------------------------------ normalization ----


def citation_points(willful, serious, other):
    return (
        CITATION_WEIGHT_WILLFUL * int(willful)
        + CITATION_WEIGHT_SERIOUS * int(serious)
        + CITATION_WEIGHT_OTHER * int(other)
    )


def incident_rate(count, hours_worked):
    hours = Decimal(hours_worked)
    if hours == 0:
        return q4(Decimal("0"))
    return q4((Decimal(count) * OSHA_BASIS) / hours)


def sub_score(value, threshold):
    """PRD 3.4: at-or-below -> 100 - 50*(v/t); above -> 50 - 50*((v-t)/t), floored at 0."""
    value = Decimal(value)
    threshold = Decimal(threshold)
    if value <= threshold:
        result = q2(Decimal("100") - (Decimal("50") * (value / threshold)))
    else:
        excess = value - threshold
        result = q2(Decimal("50") - (Decimal("50") * (excess / threshold)))
        if result < Decimal("0.00"):
            result = Decimal("0.00")
    return result


def composite_score(metrics, thresholds, weights):
    """metrics/thresholds keyed by METRIC_ORDER names; each weighted product is
    rounded to 2dp BEFORE the sum, then the total is rounded again."""
    total = Decimal("0.00")
    subs = {}
    for metric in METRIC_ORDER:
        sub = sub_score(metrics[metric], thresholds[metric])
        subs[metric] = sub
        total = total + q2(sub * Decimal(weights[metric]))
    return q2(total), subs


def grade_band(score, grading_policy):
    for letter, floor in GRADE_BANDS[grading_policy]:
        if Decimal(score) >= floor:
            return letter
    return "F"


# ------------------------------------------------- threshold resolution -------


def hazard_tier(hazard_profile, severity_rank):
    """PRD 3.6 step 2: base tier from the hazard profile, escalated by a
    lost-time or fatal incident in the client-scoped window, capped at 3."""
    base = 2 if (set(hazard_profile) & HIGH_HAZARD_CLASSES) else 1
    if severity_rank >= 3:
        return min(base + 1, 3)
    return base


def base_hazard_tier(hazard_profile):
    return 2 if (set(hazard_profile) & HIGH_HAZARD_CLASSES) else 1


def tighten_thresholds(client, tier, provisional):
    """PRD 3.6 step 3. The provisional variant forces the factor to 1.00."""
    factor = Decimal("1.00") if provisional else TIGHTENING_FACTOR[tier]
    return (
        {
            "TRIR": q4(Decimal(client["max_trir"]) * factor),
            "DART": q4(Decimal(client["max_dart_rate"]) * factor),
            "EMR": q4(Decimal(client["max_emr"]) * factor),
            "CITATION_POINTS": q4(Decimal(client["max_citation_points"]) * factor),
        },
        factor,
    )


def overlay_variances(thresholds, variance_values):
    """PRD 3.6 step 4: an approved, unexpired variance raises a tightened
    ceiling to the greater of the two. Order-independent, so a plain max()."""
    out = dict(thresholds)
    for code, requested in variance_values.items():
        if code in out:
            candidate = q4(Decimal(requested))
            if candidate > out[code]:
                out[code] = candidate
    return out


def tolerance_ceiling(threshold, conditional_band_pct):
    multiplier = Decimal("1") + (Decimal(conditional_band_pct) / Decimal("100"))
    return q4(Decimal(threshold) * multiplier)


def grading_decision(metrics, thresholds, conditional_band_pct, letter):
    """PRD 3.6: classify each metric, then choose the outcome. Returns
    (status, deficiency_codes)."""
    hard = []
    soft = []
    for metric in METRIC_ORDER:
        value = Decimal(metrics[metric])
        ceiling = Decimal(thresholds[metric])
        tolerance = tolerance_ceiling(ceiling, conditional_band_pct)
        if value > tolerance:
            hard.append(metric)
        elif value > ceiling:
            soft.append(metric)
    if hard or letter == "F":
        codes = [m for m in METRIC_ORDER if m in hard or m in soft]
        if letter == "F":
            codes.append("COMPOSITE_F")
        return "REJECTED", codes
    if soft or letter == "C":
        codes = [m for m in METRIC_ORDER if m in soft]
        if letter == "C":
            codes.append("COMPOSITE_C")
        return "CONDITIONAL", codes
    return "APPROVED", []


# ------------------------------------------------------------- insurance ------


def scaled_floor(base_floor, tier):
    """Both adequacy bases scale the floor by the contractor's base hazard tier
    and round half-up to whole dollars before comparing."""
    return q0(Decimal(base_floor) * TIER_COVERAGE_MULTIPLIER.get(tier, Decimal("1.0")))


def per_occurrence_adequate(coverage_type, each_occurrence_limit, tier):
    floor = scaled_floor(PER_OCCURRENCE_FLOORS[coverage_type], tier)
    return int(each_occurrence_limit) >= floor


def available_aggregate(aggregate_limit, open_severe_incident_count):
    return int(aggregate_limit) - (
        AGGREGATE_DEPLETION_PER_INCIDENT * int(open_severe_incident_count)
    )


def aggregate_adequate(coverage_type, aggregate_limit, open_severe_incident_count, tier):
    available = available_aggregate(aggregate_limit, open_severe_incident_count)
    floor = scaled_floor(AGGREGATE_FLOORS[coverage_type], tier)
    return available >= floor


def lifecycle_status(cert, clock):
    """PRD 3.5: five clauses, first match wins. SUPERSEDED is only ever written
    by the create-time sweep, so a fresh recomputation preserves it."""
    if cert.get("verification_status") == "REJECTED" and cert.get("lifecycle_status") == "SUPERSEDED":
        return "SUPERSEDED"
    if clock < cert["effective_date"]:
        return "NOT_YET_EFFECTIVE"
    if clock >= cert["expiration_date"]:
        return "LAPSED"
    if whole_days(clock, cert["expiration_date"]) <= EXPIRING_SOON_DAYS:
        return "EXPIRING_SOON"
    return "CURRENT"


LIVE_LIFECYCLE = frozenset(["CURRENT", "EXPIRING_SOON"])


def intervals_intersect_half_open(a_start, a_end, b_start, b_end):
    """Coverage intervals are half-open [start, end)."""
    return a_start < b_end and b_start < a_end


def windows_overlap_closed(a_start, a_end, b_start, b_end):
    """Access windows are closed [start, end]; touching endpoints collide."""
    return a_start <= b_end and b_start <= a_end


# ------------------------------------------------------- derived demand sets ---


def required_program_set(hazard_profile):
    out = set()
    for hazard in hazard_profile:
        out.update(PROGRAM_REQUIREMENTS.get(hazard, []))
    return out


def required_qualification_set(required_hazard_classes):
    out = set()
    for hazard in required_hazard_classes:
        out.update(QUALIFICATION_REQUIREMENTS.get(hazard, []))
    return out


def gate_status_from_severities(open_severities):
    severities = set(open_severities)
    if severities & REVIEW_FLAG_SEVERITIES:
        return "LOCKED"
    if "RECORDABLE" in severities:
        return "RESTRICTED"
    return "OPEN"


def effective_min_rank(min_grade, gate_status):
    """PRD 3.8: a RESTRICTED gate raises the base rank by one, capped at 3."""
    base = GRADE_RANK[min_grade]
    if gate_status == "RESTRICTED":
        return min(base + 1, 3)
    return base


def audit_draw_size(pool_size, audit_sample_rate_pct):
    exact = (Decimal(audit_sample_rate_pct) / Decimal("100")) * Decimal(pool_size)
    return int(math.ceil(exact))
