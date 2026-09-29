"""Constants and pure calculation rules (PRD 2.6, 3.3-3.9)."""

import calendar
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

# ---- credits / severities -------------------------------------------------
CREDIT = {
    "COMPLIANT": Decimal("1.0"),
    "PARTIAL": Decimal("0.5"),
    "NON_COMPLIANT": Decimal("0"),
}

SEVERITY_POINTS = {"LOW": 1, "MODERATE": 3, "HIGH": 7, "IMMEDIATE_THREAT": 15}
SEVERITY_DAYS = {"LOW": 45, "MODERATE": 30, "HIGH": 14, "IMMEDIATE_THREAT": 1}

PENALTY_CAP = 40
POSTURE_RESTRICT_POINTS = 15

BAND_READY_MIN = Decimal("90.00")
BAND_CONDITIONAL_MIN = Decimal("75.00")
BAND_AT_RISK_MIN = Decimal("60.00")

# ---- survey window prediction --------------------------------------------
MIN_INTERVAL_MONTHS = 18
MAX_INTERVAL_MONTHS = 36
COMMAND_CENTER_LEAD_DAYS = 30
FOLLOW_UP_LEAD_DAYS = 60

# ---- finding classification ----------------------------------------------
RATE_PATTERN_MIN = Decimal("0.3400")
RATE_WIDESPREAD_MIN = Decimal("0.8000")
HARM_BONUS = 2
INDEX_CAP = 6
DEADLINE_DAYS_HIGH = 45
DEADLINE_DAYS_STANDARD = 60

# ---- esc response deadlines ----------------------------------------------
CLARIFICATION_DAYS = 21
CLARIFICATION_CAP_DAYS = 10
MAX_CLARIFICATION_ROUNDS = 2

# ---- periodic performance review ----------------------------------------
RATING_POINTS = {"COMPLIANT": 100, "PARTIAL": 50, "NON_COMPLIANT": 0}
STATE_POINTS = {"EVIDENCE_COMPLETE": 100, "MAPPED": 50, "UNMAPPED": 0, "DEFICIENT": 0}
OVERSTATEMENT_THRESHOLD = Decimal("10.00")
CHAPTER_AT_RISK_PPR_COUNT = 2
CHAPTER_AT_RISK_DEFICIENT_COUNT = 2

# ---- occupancy -----------------------------------------------------------
TURNAROUND_BUFFER_MINUTES = 60
ROUNDING_CONCURRENCY_LIMIT = 2

# ---- enum sets -----------------------------------------------------------
CHAPTER_READINESS_FLAGS = ("ON_TRACK", "AT_RISK")
RISK_TIERS = ("DIRECT_IMPACT", "INDIRECT_IMPACT", "SITUATIONAL_DECISION_RULE")
COMPLIANCE_STATES = ("UNMAPPED", "MAPPED", "EVIDENCE_COMPLETE", "DEFICIENT")
DESIGNATIONS = ("PRIMARY", "SECONDARY")
OWNER_STATUSES = ("ACTIVE", "REVOKED")
DOC_TYPES = ("POLICY", "LOG", "TRAINING_RECORD", "INSPECTION_REPORT", "CONTRACT")
VALIDATION_STATES = ("DRAFT", "SUBMITTED", "VALIDATED", "REJECTED", "EXPIRED")
UNIT_TYPES = ("MED_SURG", "ICU", "ED", "OR", "BEHAVIORAL_HEALTH", "AMBULATORY")
POSTURES = ("OPEN", "RESTRICTED", "LOCKED_FOR_SURVEY")
READINESS_BANDS = ("NOT_ASSESSED", "NOT_READY", "AT_RISK", "CONDITIONAL", "READY")
TRACER_TYPES = ("PATIENT", "SYSTEM", "INDIVIDUAL")
TRACER_STATES = ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "ABORTED")
OBSERVATION_RESULTS = ("COMPLIANT", "PARTIAL", "NON_COMPLIANT", "NOT_APPLICABLE")
ROUND_TYPES = ("LIFE_SAFETY", "ENVIRONMENT_OF_CARE")
SESSION_STATES = ("OPEN", "CLOSED")
SEVERITIES = ("LOW", "MODERATE", "HIGH", "IMMEDIATE_THREAT")
TICKET_STATES = ("OPEN", "IN_PROGRESS", "REMEDIATED", "VERIFIED", "ESCALATED")
WINDOW_STATES = ("PROJECTED", "ELIGIBLE", "ACTIVE_SURVEY", "CLOSED")
COMMAND_CENTER_STATES = ("STANDBY", "ACTIVATED", "DEMOBILIZED")
CLASSIFICATIONS = ("LIMITED", "PATTERN", "WIDESPREAD")
RISK_LEVELS = ("LOW", "MODERATE", "HIGH", "IMMEDIATE_THREAT")
FINDING_STATES = (
    "DRAFT",
    "RESPONSE_PENDING",
    "RESPONSE_SUBMITTED",
    "CLARIFICATION_REQUESTED",
    "CONDITION_LEVEL_ESCALATED",
    "FOLLOW_UP_PENDING",
    "ACCEPTED",
)
DECISIONS = ("PENDING", "CLARIFICATION_REQUESTED", "ACCEPTED", "REJECTED")
REVIEW_DECISIONS = ("CLARIFICATION_REQUESTED", "ACCEPTED", "REJECTED")
PPR_STATES = ("SUBMITTED", "RETURNED_FOR_REASSESSMENT", "ATTESTED")
RATINGS = ("COMPLIANT", "PARTIAL", "NON_COMPLIANT")

TICKET_OPEN_STATES = ("OPEN", "IN_PROGRESS", "REMEDIATED", "ESCALATED")


# ---- rounding ------------------------------------------------------------
def q(value, places):
    exp = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(exp, rounding=ROUND_HALF_UP)


def q2(value):
    return q(value, 2)


def q4(value):
    return q(value, 4)


# ---- date arithmetic -----------------------------------------------------
def add_days(dt, days):
    return dt + timedelta(days=days)


def add_months(dt, months):
    """Same day-of-month `months` later, clamped to the last day of the target
    month; time of day preserved (PRD 3.6)."""
    total = dt.month - 1 + months
    year = dt.year + total // 12
    month = total % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return dt.replace(year=year, month=month, day=min(dt.day, last_day))


def floor_to_minute(dt):
    return dt.replace(second=0, microsecond=0)


def floor_to_second(dt):
    return dt.replace(microsecond=0)


# ---- readiness band ------------------------------------------------------
def readiness_band(score):
    if score >= BAND_READY_MIN:
        return "READY"
    if score >= BAND_CONDITIONAL_MIN:
        return "CONDITIONAL"
    if score >= BAND_AT_RISK_MIN:
        return "AT_RISK"
    return "NOT_READY"


# ---- mock tracer score ---------------------------------------------------
def mock_tracer_score(observations):
    """Returns (scored_weight, earned_weight, tracer_score, contributes)."""
    scored = Decimal("0")
    earned = Decimal("0")
    for obs in observations:
        if obs["result"] == "NOT_APPLICABLE":
            continue
        scored += obs["weight"]
        earned += obs["weight"] * CREDIT[obs["result"]]
    if scored == 0:
        return scored, earned, Decimal("0.00"), False
    return scored, earned, q2(earned / scored * 100), True


# ---- finding risk classification ----------------------------------------
CLASS_INDEX = {"LIMITED": 0, "PATTERN": 1, "WIDESPREAD": 2}
TIER_INDEX = {"SITUATIONAL_DECISION_RULE": 0, "INDIRECT_IMPACT": 1, "DIRECT_IMPACT": 2}


def finding_risk_classification(observed, sampled, risk_tier, harm):
    rate = q4(Decimal(observed) / Decimal(sampled))
    if rate < RATE_PATTERN_MIN:
        classification = "LIMITED"
    elif rate < RATE_WIDESPREAD_MIN:
        classification = "PATTERN"
    else:
        classification = "WIDESPREAD"
    raw_index = CLASS_INDEX[classification] + TIER_INDEX[risk_tier] + (HARM_BONUS if harm else 0)
    raw_index = min(raw_index, INDEX_CAP)
    if raw_index <= 1:
        risk_level = "LOW"
    elif raw_index == 2:
        risk_level = "MODERATE"
    elif raw_index in (3, 4):
        risk_level = "HIGH"
    else:
        risk_level = "IMMEDIATE_THREAT"
    condition_level = risk_level == "IMMEDIATE_THREAT" or (
        classification == "WIDESPREAD" and risk_tier == "DIRECT_IMPACT"
    )
    deadline_days = (
        DEADLINE_DAYS_HIGH if risk_level in ("HIGH", "IMMEDIATE_THREAT") else DEADLINE_DAYS_STANDARD
    )
    return {
        "noncompliance_rate": rate,
        "classification": classification,
        "risk_level": risk_level,
        "condition_level": condition_level,
        "response_deadline_days": deadline_days,
    }


# ---- deficiency due date -------------------------------------------------
def deficiency_due_at(clock, severity, band_snapshot):
    base_days = SEVERITY_DAYS[severity]
    accelerated = False
    if band_snapshot in ("AT_RISK", "NOT_READY"):
        base_days = max(1, base_days // 2)
        accelerated = True
    return add_days(clock, base_days), accelerated


# ---- esc response deadlines ---------------------------------------------
def esc_due_initial(survey_closed_at, response_deadline_days):
    return add_days(survey_closed_at, response_deadline_days)


def esc_due_clarification(clock, initial_response_due_at):
    candidate = add_days(clock, CLARIFICATION_DAYS)
    cap = add_days(initial_response_due_at, CLARIFICATION_CAP_DAYS)
    return min(candidate, cap)
