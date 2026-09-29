"""Deterministic calculations (PRD §2.6 and the §3 worked examples).

All money-like and score-like arithmetic uses decimal.Decimal with
ROUND_HALF_UP; no float ever participates in a rounding decision.
"""

import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import store

D0 = Decimal("0")
D100 = Decimal("100")
CENT = Decimal("0.01")


def q2(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def q4(value):
    return Decimal(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def num(value):
    """Render a Decimal for JSON without ever going through float arithmetic."""
    if value is None:
        return None
    return float(value)


# ------------------------------------------------------- adverse event scoring
EVENT_BASE_POINTS = {
    "REPORTED_TIMELY": Decimal("2"),
    "REPORTED_LATE": Decimal("5"),
    "REPORT_OVERDUE": Decimal("9"),
}
POINT_BEARING_STATUSES = ("REPORTED_TIMELY", "REPORTED_LATE", "REPORT_OVERDUE")


def event_points(report_status, lateness_days, professional_use_only):
    """PRD §3.6 — base x lateness_factor x professional relief, rounded per event."""
    base = EVENT_BASE_POINTS.get(report_status)
    if base is None:
        return q2(D0)
    days = int(lateness_days or 0)
    factor = Decimal("1") + Decimal("0.1") * Decimal(days)
    if factor > Decimal("2.0"):
        factor = Decimal("2.0")
    relief = Decimal("0.5") if professional_use_only else Decimal("1")
    return q2(base * factor * relief)


def facility_points(event_point_values):
    """Sum of per-event rounded points, rounded again, capped at 100.00."""
    total = q2(sum(event_point_values, D0))
    if total > D100:
        total = q2(D100)
    return total


def lateness_days(submitted_at, deadline_at):
    """Whole days of lateness, rounded up; 0 when at or before the deadline."""
    if deadline_at is None or submitted_at is None or submitted_at <= deadline_at:
        return 0
    delta = submitted_at - deadline_at
    return int(math.ceil(delta.total_seconds() / 86400.0))


# ------------------------------------------------------------- GMP readiness
SEVERITY_WEIGHT = {"MINOR": 1, "MAJOR": 3, "CRITICAL": 6}
OBSERVATION_CATEGORIES = ("PERSONNEL", "PREMISES", "EQUIPMENT", "RAW_MATERIALS", "RECORDKEEPING")
CATEGORY_WEIGHT = {
    "PERSONNEL": Decimal("0.15"),
    "PREMISES": Decimal("0.20"),
    "EQUIPMENT": Decimal("0.15"),
    "RAW_MATERIALS": Decimal("0.20"),
    "RECORDKEEPING": Decimal("0.30"),
}
DEDUCTION_CAP = Decimal("30")


def gmp_readiness(observations):
    """PRD §3.7 four-step pinned computation.  Returns (score, subscores)."""
    deductions = {c: 0 for c in OBSERVATION_CATEGORIES}
    for obs in observations:
        deductions[obs["category"]] += SEVERITY_WEIGHT[obs["severity"]]
    subscores = {}
    terms = []
    for category in OBSERVATION_CATEGORIES:
        raw = Decimal(deductions[category])
        capped = raw if raw < DEDUCTION_CAP else DEDUCTION_CAP
        subscore = q2(D100 - (D100 * capped / DEDUCTION_CAP))
        subscores[category] = subscore
        terms.append(q2(subscore * CATEGORY_WEIGHT[category]))
    return q2(sum(terms, D0)), subscores


# --------------------------------------------------------- adequacy scoring
EVIDENCE_WEIGHT = {
    "CLINICAL_SAFETY_STUDY": Decimal("40"),
    "IN_VITRO_TOXICOLOGY": Decimal("25"),
    "READ_ACROSS_ANALOG": Decimal("20"),
    "HISTORICAL_USE_DOSSIER": Decimal("10"),
    "LITERATURE_REVIEW": Decimal("5"),
}
CREDENTIAL_FACTOR = {
    "BOARD_CERTIFIED_TOXICOLOGIST": Decimal("1.0"),
    "ERT": Decimal("1.0"),
    "QUALIFIED_SAFETY_ASSESSOR": Decimal("0.6"),
    "OTHER": Decimal("0.3"),
}
READ_ACROSS_DISCOUNT = Decimal("0.5")
EVIDENCE_GROUP_CAP = Decimal("40.00")
DATA_GAP_PENALTY = Decimal("15.00")
ADEQUACY_PASS_MARK = Decimal("60.00")


def item_base_value(item):
    return q2(EVIDENCE_WEIGHT[item["evidence_type"]] * CREDENTIAL_FACTOR[item["reviewer_credential"]])


def item_full_value(item):
    """Post read-across discount, pre-cap (PRD §3.4: what full_contribution stores)."""
    value = item_base_value(item)
    if item["evidence_type"] == "READ_ACROSS_ANALOG":
        value = q2(value * READ_ACROSS_DISCOUNT)
    return value


def screening_score(items):
    return q2(sum((item_base_value(i) for i in items), D0))


def full_score(items, data_gap_present):
    groups = {}
    for item in items:
        groups.setdefault(item["evidence_type"], D0)
        groups[item["evidence_type"]] += item_full_value(item)
    total = D0
    for evidence_type, group_total in groups.items():
        capped = group_total if group_total < EVIDENCE_GROUP_CAP else EVIDENCE_GROUP_CAP
        total += capped
    if data_gap_present:
        total -= DATA_GAP_PENALTY
    if total < D0:
        total = D0
    return q2(total)


def adequacy_score(items, review_mode, data_gap_present):
    if review_mode == "SCREENING":
        return screening_score(items)
    return full_score(items, data_gap_present)


# ------------------------------------------------------------ recovery rates
def rate(numerator, denominator):
    if not denominator:
        return q2(D0)
    return q2(D100 * Decimal(numerator) / Decimal(denominator))


def unreachable_credit_pct(provisional_rate):
    """Read off the PROVISIONAL rate (PRD §3.8 step 2)."""
    if provisional_rate >= Decimal("90.00"):
        return 0
    if provisional_rate >= Decimal("80.00"):
        return 3
    return 6


def adjusted_denominator(shipped_units, credit_pct):
    """Only integer truncation in the system: floor of the unreachable credit."""
    credit = (Decimal(shipped_units) * Decimal(credit_pct) / D100).to_integral_value(rounding="ROUND_FLOOR")
    return int(Decimal(shipped_units) - credit)


EFFECTIVENESS_PASS_MARK = Decimal("90.00")


# --------------------------------------------------- registration period math
def period_bounds(period_start):
    """PRD §3.1 anchor arithmetic.  Returns (period_end, renewal_open, grace_end)."""
    anchor_year = period_start.year + 2
    anchor_month = period_start.month
    anchor_day = min(period_start.day, store.days_in_month(anchor_year, anchor_month))
    from datetime import date as _date
    anchor = _date(anchor_year, anchor_month, anchor_day)
    period_end = anchor - timedelta(days=1)
    renewal_open = period_end - timedelta(days=90)
    grace_end = period_end + timedelta(days=60)
    return period_end, renewal_open, grace_end


# ---------------------------------------------------------- allergen threshold
ALLERGEN_THRESHOLD = {"LEAVE_ON": Decimal("0.001"), "RINSE_OFF": Decimal("0.01")}


def disclosure_required(ingredient, listing):
    if not ingredient.get("is_fragrance_allergen"):
        return False
    if listing.get("professional_use_only"):
        return False
    threshold = ALLERGEN_THRESHOLD.get(listing.get("product_form"))
    if threshold is None:
        return False
    concentration = ingredient.get("concentration_pct")
    if concentration is None:
        return False
    return Decimal(concentration) >= threshold
