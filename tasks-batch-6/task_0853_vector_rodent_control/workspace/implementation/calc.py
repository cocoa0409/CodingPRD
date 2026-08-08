"""All program constants and the nine calculations (PRD 3.2, 3.4, 3.6, 3.7, 3.8)."""

import datetime
from decimal import Decimal, ROUND_HALF_UP

import lclock

# --- program constants ---------------------------------------------------

DUPLICATE_COMPLAINT_WINDOW_HOURS = 48
OFFICER_TRAVEL_BUFFER_MINUTES = 30
INSPECTION_MIN_DURATION_MINUTES = 30
INSPECTION_MAX_DURATION_MINUTES = 240
READING_MIN_INTERVAL_HOURS = 24
MAX_ASSESSMENTS_PER_INSPECTION = 1
MAX_NON_VOID_INVOICES_PER_ORDER = 1
MAX_EXTENSIONS_PER_ORDER = 1
EXTENSION_MAX_DAYS = 14
EXTENSION_MIN_DAYS = 1
ESCALATION_MAX_LEVEL = 2
CHRONIC_THRESHOLD = Decimal("60.00")
POSTURE_ELEVATED_THRESHOLD = Decimal("40.00")
POSTURE_HOTSPOT_THRESHOLD = Decimal("70.00")
APPROVAL_LIMIT_CENTS = 500000
INVOICE_DUE_DAYS = 30
LIEN_MIN_BALANCE_CENTS = 25000
LIEN_MIN_DAYS_PAST_DUE = 60

SEVERITY_BASE = {"ROUTINE": Decimal(20), "HIGH": Decimal(40), "CRITICAL": Decimal(60)}
TYPE_WEIGHT = {
    "RODENT_SIGHTING": Decimal(10),
    "HARBORAGE": Decimal(15),
    "GARBAGE_ACCUMULATION": Decimal(12),
    "DEAD_ANIMAL": Decimal(8),
    "MOSQUITO_BREEDING": Decimal(18),
}
CHRONIC_PROPERTY_BONUS = Decimal(15)
POSTURE_BONUS = {"NORMAL": Decimal(0), "ELEVATED": Decimal(5), "HOTSPOT": Decimal(12)}
PRIORITY_SCORE_MAX = Decimal(100)

SLA_HOURS = {"ROUTINE": 168, "HIGH": 72, "CRITICAL": 24}

HARBORAGE_WEIGHT = Decimal("0.40")
ATTRACTANT_WEIGHT = Decimal("0.35")
SANITATION_WEIGHT = Decimal("0.25")
BURROW_SURCHARGE_PER_BURROW = Decimal("3.0")
BURROW_SURCHARGE_CAP = Decimal("15.0")
TIER_MODERATE_MIN = Decimal("35.00")
TIER_SEVERE_MIN = Decimal("65.00")

CHRONIC_LOOKBACK_DAYS = 365
CHRONIC_DECAY_PER_30_DAYS = Decimal("0.10")
REPEAT_OFFENSE_SURCHARGE = Decimal("8.0")

SURVEILLANCE_WINDOW_DAYS = 30
SIGN_SCALE = Decimal("12.5")
COMPLAINT_SCALE = Decimal("20.0")
BAIT_WEIGHT = Decimal("0.50")
SIGN_WEIGHT = Decimal("0.30")
COMPLAINT_WEIGHT = Decimal("0.20")

ABATEMENT_BASE_COMPLIANCE_DAYS = 14
ABATEMENT_SEVERE_COMPLIANCE_DAYS = 7
ABATEMENT_HOTSPOT_COMPLIANCE_DAYS = 5
ABATEMENT_ESCALATED_COMPLIANCE_DAYS = 7

LABOR_RATE_CENTS_PER_HOUR = Decimal(8525)
ESTIMATED_LABOR_HOURS = {"LOW": Decimal(2), "MODERATE": Decimal(4), "SEVERE": Decimal(8)}
MATERIALS_ESTIMATE_CENTS = {"LOW": 5000, "MODERATE": 12000, "SEVERE": 25000}
PENALTY_MULTIPLIER = {0: Decimal("1.00"), 1: Decimal("1.25"), 2: Decimal("1.50")}
EDUCATION_CREDIT_RATE = Decimal("0.10")
ADMIN_FEE_RATE = Decimal("0.15")
HARDSHIP_TIER_HIGH_MIN_CENTS = 100000
HARDSHIP_RATE_HIGH = Decimal("0.10")
HARDSHIP_TIER_LOW_MIN_CENTS = 50000
HARDSHIP_RATE_LOW = Decimal("0.05")

OPEN_COMPLAINT_STATUSES = (
    "RECEIVED",
    "TRIAGED",
    "INSPECTION_SCHEDULED",
    "INSPECTED",
    "ABATEMENT_ORDERED",
)
CLOSED_COMPLAINT_STATUSES = (
    "CLOSED_NO_VIOLATION",
    "CLOSED_RESOLVED",
    "CLOSED_WITHDRAWN",
    "CLOSED_DUPLICATE",
)
NON_TERMINAL_ORDER_STATUSES = (
    "ISSUED",
    "SERVED",
    "REINSPECTION_SCHEDULED",
    "ESCALATED",
    "CITY_ABATED",
)


# --- rounding ------------------------------------------------------------

_TWO = Decimal("0.01")
_ONE = Decimal("1")


def rhu2(value):
    """Round half-up to two decimal places (PRD 2.7)."""
    return Decimal(value).quantize(_TWO, rounding=ROUND_HALF_UP)


def rhu_cents(value):
    """Round half-up to a whole number of cents (PRD 2.7)."""
    return int(Decimal(value).quantize(_ONE, rounding=ROUND_HALF_UP))


def num(value):
    """Render a 2dp Decimal for JSON."""
    if value is None:
        return None
    return float(value)


# --- 1. complaint_priority_score ----------------------------------------


def complaint_priority_score(severity, complaint_type, chronic_flag, posture):
    total = (
        SEVERITY_BASE[severity]
        + TYPE_WEIGHT[complaint_type]
        + (CHRONIC_PROPERTY_BONUS if chronic_flag else Decimal(0))
        + POSTURE_BONUS[posture]
    )
    return rhu2(min(PRIORITY_SCORE_MAX, total))


# --- 2. complaint_response_deadline --------------------------------------


def complaint_response_deadline(created_at, severity):
    return created_at + datetime.timedelta(hours=SLA_HOURS[severity])


# --- 3. assessment_infestation_index -------------------------------------


def assessment_infestation_index(harborage, attractant, sanitation, burrow_count):
    base = (
        HARBORAGE_WEIGHT * Decimal(harborage)
        + ATTRACTANT_WEIGHT * Decimal(attractant)
        + SANITATION_WEIGHT * Decimal(sanitation)
    ) * Decimal(10)
    surcharge = min(BURROW_SURCHARGE_CAP, BURROW_SURCHARGE_PER_BURROW * Decimal(burrow_count))
    index = rhu2(min(Decimal("100.0"), base + surcharge))
    if index >= TIER_SEVERE_MIN:
        tier = "SEVERE"
    elif index >= TIER_MODERATE_MIN:
        tier = "MODERATE"
    else:
        tier = "LOW"
    return index, tier


# --- 4. property_chronic_score (PROVISIONAL / REVIEWED) ------------------


def chronic_score_provisional(infestation_index):
    """PROVISIONAL variant: the new assessment's index, verbatim."""
    return rhu2(infestation_index)


def chronic_score_reviewed(qualifying, now):
    """REVIEWED variant.

    ``qualifying`` is a list of (infestation_index, completed_at) pairs already
    filtered to the parcel's COMPLETED / VIOLATION_FOUND assessments inside the
    365-day lookback and ordered by completed_at then created_at ascending.
    """
    n = len(qualifying)
    if n == 0:
        return Decimal("0.00"), False
    weighted_sum = Decimal(0)
    weight_sum = Decimal(0)
    for index, completed_at in qualifying:
        age_days = (now - completed_at) // datetime.timedelta(days=1)
        blocks = age_days // 30
        weight = Decimal("1.0") - CHRONIC_DECAY_PER_30_DAYS * Decimal(blocks)
        if weight < 0:
            weight = Decimal("0.0")
        weighted_sum += Decimal(index) * weight
        weight_sum += weight
    if weight_sum == 0:
        weighted = Decimal(0)
    else:
        weighted = weighted_sum / weight_sum
    score = rhu2(min(Decimal("100.0"), weighted + REPEAT_OFFENSE_SURCHARGE * Decimal(n - 1)))
    return score, score >= CHRONIC_THRESHOLD


def in_chronic_lookback(completed_at, now):
    if completed_at is None:
        return False
    delta = now - completed_at
    return datetime.timedelta(0) <= delta <= datetime.timedelta(days=CHRONIC_LOOKBACK_DAYS)


# --- 5. zone_rodent_index ------------------------------------------------


def posture_for(index):
    if index >= POSTURE_HOTSPOT_THRESHOLD:
        return "HOTSPOT"
    if index >= POSTURE_ELEVATED_THRESHOLD:
        return "ELEVATED"
    return "NORMAL"


def zone_rodent_index(window_readings, open_complaint_rows, now):
    """Returns a dict with every component of the composite index."""
    window_start = now - datetime.timedelta(days=SURVEILLANCE_WINDOW_DAYS)
    window_end = now
    count = len(window_readings)
    if count == 0:
        bait_component = Decimal("0.00")
        sign_component = Decimal("0.00")
    else:
        take_sum = sum(Decimal(r["take_pct"]) for r in window_readings)
        sign_sum = sum(Decimal(r["activity_sign_count"]) for r in window_readings)
        bait_component = rhu2(take_sum / Decimal(count))
        sign_component = rhu2(min(Decimal("100.0"), SIGN_SCALE * (sign_sum / Decimal(count))))
    complaint_count = len(open_complaint_rows)
    complaint_component = rhu2(min(Decimal("100.0"), COMPLAINT_SCALE * Decimal(complaint_count)))
    index = rhu2(
        BAIT_WEIGHT * bait_component
        + SIGN_WEIGHT * sign_component
        + COMPLAINT_WEIGHT * complaint_component
    )
    return {
        "rodent_index": index,
        "posture": posture_for(index),
        "bait_component": bait_component,
        "sign_component": sign_component,
        "complaint_component": complaint_component,
        "in_window_reading_count": count,
        "open_complaint_count": complaint_count,
        "window_start": window_start,
        "window_end": window_end,
    }


# --- 6. abatement_compliance_deadline ------------------------------------


def abatement_compliance_deadline(served_at, tier_at_issue, zone_posture, escalation_level,
                                  extension_days_total):
    base_days = ABATEMENT_BASE_COMPLIANCE_DAYS
    if tier_at_issue == "SEVERE":
        base_days = min(base_days, ABATEMENT_SEVERE_COMPLIANCE_DAYS)
    if zone_posture == "HOTSPOT":
        base_days = min(base_days, ABATEMENT_HOTSPOT_COMPLIANCE_DAYS)
    if escalation_level >= 1:
        base_days = min(base_days, ABATEMENT_ESCALATED_COMPLIANCE_DAYS)
    return served_at + datetime.timedelta(days=base_days + (extension_days_total or 0))


# --- 7. cost_recovery_invoice_total (ESTIMATE / FINAL) -------------------


def cost_recovery_invoice_total(labor_hours, materials_cents, escalation_level,
                                education_advisory_served, hardship_certified):
    """The eleven pinned steps of PRD 3.7."""
    labor_line = rhu_cents(Decimal(labor_hours) * LABOR_RATE_CENTS_PER_HOUR)          # 1
    materials_line = int(materials_cents)                                             # 2
    subtotal = labor_line + materials_line                                            # 3
    multiplier = PENALTY_MULTIPLIER[min(escalation_level, ESCALATION_MAX_LEVEL)]
    penalty_line = rhu_cents(Decimal(subtotal) * (multiplier - Decimal("1.00")))       # 4
    if education_advisory_served:                                                     # 5
        education_credit = rhu_cents(Decimal(subtotal) * EDUCATION_CREDIT_RATE)
    else:
        education_credit = 0
    fee_base = subtotal + penalty_line - education_credit                             # 6
    admin_fee = rhu_cents(Decimal(fee_base) * ADMIN_FEE_RATE)                         # 7
    pre_discount_total = fee_base + admin_fee                                         # 8
    if hardship_certified and pre_discount_total >= HARDSHIP_TIER_HIGH_MIN_CENTS:     # 9
        hardship_rate = HARDSHIP_RATE_HIGH
    elif hardship_certified and pre_discount_total >= HARDSHIP_TIER_LOW_MIN_CENTS:
        hardship_rate = HARDSHIP_RATE_LOW
    else:
        hardship_rate = Decimal("0.00")
    hardship_discount = rhu_cents(Decimal(subtotal) * hardship_rate)                   # 10
    total = pre_discount_total - hardship_discount                                     # 11
    return {
        "labor_line_cents": labor_line,
        "materials_line_cents": materials_line,
        "subtotal_cents": subtotal,
        "penalty_line_cents": penalty_line,
        "education_credit_cents": education_credit,
        "fee_base_cents": fee_base,
        "admin_fee_cents": admin_fee,
        "pre_discount_total_cents": pre_discount_total,
        "hardship_discount_cents": hardship_discount,
        "total_cents": total,
    }
