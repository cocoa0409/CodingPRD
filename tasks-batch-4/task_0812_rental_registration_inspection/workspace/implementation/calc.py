"""Deterministic calculation rules: scoring, fees, penalties."""
import math
from decimal import Decimal
from timeutil import round_half_up, round_cents

# ---- inspection_result_score ----
SEVERITY_WEIGHT = {"MINOR": 1, "MAJOR": 3, "CRITICAL": 10}
CATEGORY_MULT = {
    "LIFE_SAFETY": Decimal("2.0"),
    "HABITABILITY": Decimal("1.0"),
    "LEAD_PAINT": Decimal("1.5"),
    "STRUCTURAL": Decimal("1.5"),
}
MANDATORY_CATEGORIES = ["LIFE_SAFETY", "HABITABILITY"]
PASS_THRESHOLD = Decimal("5.0")

# ---- license_fee ----
TIER_1_CENTS = 15000
TIER_2_CENTS = 30000
TIER_3_CENTS = 60000
TIER_4_CENTS = 120000
LEAD_SURCHARGE_CENTS = 5000
LEAD_YEAR = 1978
LATE_MULTIPLIER = Decimal("1.5")
REINSTATEMENT_FEE_CENTS = 10000

# ---- violation_penalty ----
CURE_DAYS = {"MINOR": 30, "MAJOR": 14, "CRITICAL": 3}
DAILY_CENTS = {"MINOR": 1000, "MAJOR": 2500, "CRITICAL": 10000}
MAX_RAW_CENTS = {"MINOR": 30000, "MAJOR": 75000, "CRITICAL": 300000}
ADMIN_FEE_RATE = Decimal("0.075")

# ---- escalation ----
ESCALATION_CRITICAL_COUNT = 2

NOTICE_ACK_DAYS = 30
REINSPECTION_MIN_HOURS = 48
COOLDOWN_HOURS = 24

OPEN_VIOLATION_STATUSES = {"OPEN", "REMEDIATION_SUBMITTED", "ESCALATED"}


def inspection_score(items, final):
    """Compute the habitability score.

    items: list of checklist item dicts (category, code, result, severity).
    final: when True, add a synthetic CRITICAL FAIL for each mandatory
    category with zero recorded items.
    Returns (score_float, passes_bool).
    """
    base = Decimal(0)
    has_critical_fail = False
    for it in items:
        if it["result"] == "FAIL":
            base += Decimal(SEVERITY_WEIGHT[it["severity"]]) * CATEGORY_MULT[it["category"]]
            if it["severity"] == "CRITICAL":
                has_critical_fail = True

    all_mandatory_covered = all(
        any(it["category"] == cat for it in items) for cat in MANDATORY_CATEGORIES
    )

    if final:
        for cat in MANDATORY_CATEGORIES:
            if not any(it["category"] == cat for it in items):
                base += Decimal(SEVERITY_WEIGHT["CRITICAL"]) * CATEGORY_MULT[cat]

    score = round_half_up(base, 1)

    passes = (score < PASS_THRESHOLD) and (not has_critical_fail)
    if final:
        passes = passes and all_mandatory_covered
    return float(score), passes


def license_fee(unit_count, year_built, term_years, late):
    """Return (fee_cents, lead_surcharge_applied)."""
    if unit_count == 1:
        tier_base = TIER_1_CENTS
    elif 2 <= unit_count <= 4:
        tier_base = TIER_2_CENTS
    elif 5 <= unit_count <= 20:
        tier_base = TIER_3_CENTS
    else:
        tier_base = TIER_4_CENTS

    lead_applied = year_built < LEAD_YEAR
    lead = LEAD_SURCHARGE_CENTS if lead_applied else 0
    annual = tier_base + lead
    base_fee = annual * term_years

    if not late:
        fee = base_fee
    else:
        fee = round_cents(Decimal(base_fee) * LATE_MULTIPLIER) + REINSTATEMENT_FEE_CENTS
    return fee, lead_applied


def violation_penalty(violation, now):
    """Per-violation penalty in whole cents. 0 unless overdue and accruing."""
    if violation["status"] not in OPEN_VIOLATION_STATUSES:
        return 0
    cure = violation.get("cure_deadline")
    if cure is None:
        return 0
    if now <= cure:
        return 0
    sev = violation["severity"]
    delta = now - cure
    days_overdue = math.ceil(delta.total_seconds() / 86400.0)
    raw = min(DAILY_CENTS[sev] * days_overdue, MAX_RAW_CENTS[sev])
    return round_cents(Decimal(raw) * (Decimal(1) + ADMIN_FEE_RATE))
