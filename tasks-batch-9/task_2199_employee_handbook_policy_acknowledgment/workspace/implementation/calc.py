"""Pinned-order calculations."""
from decimal import Decimal, ROUND_HALF_UP

import clock

REASON_FACTOR = {"RELIGIOUS": 20, "MEDICAL": 25, "COLLECTIVE_BARGAINING": 45, "ROLE_CONFLICT": 65}
CATEGORY_FACTOR = {"SAFETY": 90, "DATA_PRIVACY": 75, "COMPENSATION": 55, "CODE_OF_CONDUCT": 40, "LEAVE": 25}
DURATION_DENOMINATOR_DAYS = Decimal(180)
GRANT_RISK_CEILING = Decimal("70.00")

A11Y_AA_MIN = Decimal("90.00")
A11Y_AAA_MIN = Decimal("96.00")
A11Y_ACCESSIBLE_MIN = Decimal("96.00")

BUFFER_NO_SLACK_DAYS = 7
BUFFER_TIGHT_DAYS = 3
BUFFER_COMFORTABLE_DAYS = 1
SLACK_TIGHT_UPPER = 9

ON_LEAVE_EXTENSION_DAYS = 14
ACCESSIBLE_FLOOR_DAYS = 21
SAFETY_CAP_DAYS = 7

TIER2_MIN_DAYS = 7
TIER3_MIN_DAYS = 14
MAX_TIER = 3

DISPUTE_FLOOR_DAYS = 1095
EMPTY_DENOMINATOR_RESULT = Decimal("100.00")


def q2(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def q4(value):
    return Decimal(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def num(dec):
    """Serialize a Decimal as a JSON number preserving trailing 2dp."""
    if dec is None:
        return None
    return float(dec)


def coverage(numerator, denominator):
    if denominator == 0:
        return EMPTY_DENOMINATOR_RESULT
    return q2(Decimal(100) * Decimal(numerator) / Decimal(denominator))


def a11y_index(section_scores, section_count):
    """Round each section to 2dp, then sum exactly, then divide and round to 2dp."""
    per_section = [q2(Decimal(str(s)) * Decimal(100)) for s in section_scores]
    rounded_sum = sum(per_section, Decimal(0))
    return q2(rounded_sum / Decimal(section_count))


def conformance_level(index):
    if index < A11Y_AA_MIN:
        return "FAIL"
    if index < A11Y_AAA_MIN:
        return "AA"
    return "AAA"


def risk_scores(reason_code, requested_days, prior_exception_count, category):
    f_reason = Decimal(REASON_FACTOR[reason_code])
    raw_duration = Decimal(requested_days) * Decimal(100) / DURATION_DENOMINATOR_DAYS
    f_duration = q4(min(Decimal(100), raw_duration))
    f_history = min(Decimal(100), Decimal(prior_exception_count) * Decimal(30))
    f_category = Decimal(CATEGORY_FACTOR[category])
    weighted = (
        Decimal("0.20") * f_reason
        + Decimal("0.15") * f_duration
        + Decimal("0.25") * f_history
        + Decimal("0.40") * f_category
    )
    peak = max(f_reason, f_duration, f_history, f_category)
    aggregate = q2(weighted)
    conservative = q2(Decimal("0.60") * peak + Decimal("0.40") * weighted)
    return conservative, aggregate


def legal_review_deadline(scope_jurisdictions, effective_date, now):
    base_days = max(j["min_legal_review_days"] for j in scope_jurisdictions)
    lead_days = clock.floor_days(effective_date, now)
    slack_days = lead_days - base_days
    if slack_days <= 0:
        buffer_days = BUFFER_NO_SLACK_DAYS
    elif slack_days <= SLACK_TIGHT_UPPER:
        buffer_days = BUFFER_TIGHT_DAYS
    else:
        buffer_days = BUFFER_COMFORTABLE_DAYS
    return clock.add_days(effective_date, -(base_days + buffer_days))


def ack_deadline_days(jur_days, doc_max_days, employment_status, needs_accessible, category):
    d = min(int(jur_days), int(doc_max_days))
    if employment_status == "ON_LEAVE":
        d = d + ON_LEAVE_EXTENSION_DAYS
    if needs_accessible:
        d = max(d, ACCESSIBLE_FLOOR_DAYS)
    if category == "SAFETY":
        d = min(d, SAFETY_CAP_DAYS)
    return d


def days_overdue(due_date, now):
    if now <= due_date:
        return 0
    return clock.floor_days(now, due_date)


def escalation_tier(days_over, category):
    if days_over < TIER2_MIN_DAYS:
        base = 1
    elif days_over < TIER3_MIN_DAYS:
        base = 2
    else:
        base = 3
    if category == "SAFETY":
        return min(MAX_TIER, base + 1)
    return base


def retention_until(retained_from, retention_years):
    calendar_base = clock.add_calendar_years(retained_from, retention_years)
    dispute_floor = clock.add_days(retained_from, DISPUTE_FLOOR_DAYS)
    return max(calendar_base, dispute_floor)
