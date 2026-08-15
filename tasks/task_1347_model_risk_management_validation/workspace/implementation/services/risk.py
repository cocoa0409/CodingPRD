"""Calculation rules (scaffold §1.3): model_risk_score, finding_deadline_days,
open_findings_count, monitoring_posture, inventory_risk_index,
validation_due_at_schedule, consecutive_breach_escalation helpers.
"""
from decimal import Decimal, ROUND_HALF_UP

from db import store
from utils import add_months

OPEN_FINDING_STATES = ("OPEN", "OVERDUE", "ESCALATED")

COMPLEXITY_POINTS = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
SCOPE_POINTS = {"SINGLE_DESK": 0, "MULTI_DESK": 1, "ENTERPRISE": 2}
SEVERITY_PENALTY = {"CRITICAL": 10, "HIGH": 5, "MEDIUM": 2, "LOW": 1}

TIER_1_MIN = 70
TIER_2_MIN = 40
SCORE_CAP = 100

REVALIDATION_MONTHS = {"TIER_1": 6, "TIER_2": 12, "TIER_3": 24}
MAJOR_CHANGE_REVALIDATION_MONTHS = 3

BASE_DAYS = {"LOW": 90, "MEDIUM": 60, "HIGH": 30, "CRITICAL": 14}
TIER_MULTIPLIER = {
    "TIER_1": Decimal("1.0"),
    "TIER_2": Decimal("1.5"),
    "TIER_3": Decimal("2.0"),
}
MONITORING_URGENCY_DEDUCTION = 5
MIN_DAYS = 7
MAX_DAYS = 365
ESCALATION_GRACE_DAYS = 7

CONSECUTIVE_BREACH_LIMIT = 3
VENDOR_MIN_COMPLETENESS = 70


def exposure_points(exposure_amount):
    if exposure_amount < 1_000_000:
        return 1
    if exposure_amount < 10_000_000:
        return 2
    if exposure_amount < 100_000_000:
        return 3
    return 4


def findings_penalty(model_id):
    total = 0
    for f in store.findings.values():
        if f["model_id"] == model_id and f["status"] in OPEN_FINDING_STATES:
            total += SEVERITY_PENALTY[f["severity"]]
    return total


def compute_score(model):
    """Composite risk score. VALIDATOR_ASSESSED variant applies once
    assessed_complexity is set; otherwise DEV_DECLARED. Integer arithmetic."""
    assessed = model["assessed_complexity"] is not None
    complexity = model["assessed_complexity"] if assessed else model["declared_complexity"]
    weight = 25 if assessed else 20
    score = (
        weight * COMPLEXITY_POINTS[complexity]
        + 10 * SCOPE_POINTS[model["usage_scope"]]
        + 10 * exposure_points(model["exposure_amount"])
        + findings_penalty(model["id"])
    )
    return min(SCORE_CAP, score)


def tier_of(score):
    if score >= TIER_1_MIN:
        return "TIER_1"
    if score >= TIER_2_MIN:
        return "TIER_2"
    return "TIER_3"


def recompute_risk(model):
    """Recompute risk_score/risk_tier in place. If the tier changed, refresh
    validation_due_at from the anchor (last_validated_at else created_at)."""
    model["risk_score"] = compute_score(model)
    new_tier = tier_of(model["risk_score"])
    if new_tier != model["risk_tier"]:
        model["risk_tier"] = new_tier
        anchor = model["last_validated_at"] or model["created_at"]
        model["validation_due_at"] = add_months(anchor, REVALIDATION_MONTHS[new_tier])


def deadline_days(severity, tier, source):
    """finding_deadline_days: base * tier multiplier (round-half-up on the
    multiplication only), minus 5 for MONITORING, clamped into [7, 365]."""
    scaled = (Decimal(BASE_DAYS[severity]) * TIER_MULTIPLIER[tier]).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    days = int(scaled)
    if source == "MONITORING":
        days -= MONITORING_URGENCY_DEDUCTION
    return min(MAX_DAYS, max(MIN_DAYS, days))


def open_findings_count(model_id):
    return sum(
        1
        for f in store.findings.values()
        if f["model_id"] == model_id and f["status"] in OPEN_FINDING_STATES
    )


def monitoring_posture(model_id):
    """BREACHED iff at least one OPEN BreachEvent exists on any metric of the model."""
    for mt in store.metrics.values():
        if mt["model_id"] != model_id:
            continue
        for b in store.breach_events.values():
            if b["metric_id"] == mt["id"] and b["status"] == "OPEN":
                return "BREACHED"
    return "NORMAL"


def is_breach(metric, value):
    """Strict comparison; equality with the threshold is NEVER a breach."""
    if metric["direction"] == "ABOVE_IS_BREACH":
        return value > metric["threshold_value"]
    return value < metric["threshold_value"]


def inventory_risk_index(models, aggregation_method):
    """Single final round-half-up to 2 decimal places; no intermediate rounding."""
    if not models:
        return 0.0
    if aggregation_method == "EQUAL_WEIGHTED":
        total = sum(m["risk_score"] for m in models)
        value = Decimal(total) / Decimal(len(models))
    else:
        total_exposure = sum(m["exposure_amount"] for m in models)
        if total_exposure == 0:
            return 0.0
        weighted = sum(
            Decimal(m["risk_score"]) * Decimal(m["exposure_amount"]) for m in models
        )
        value = weighted / Decimal(total_exposure)
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
