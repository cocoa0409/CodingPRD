"""The ten calculation rules of the PRD, implemented with exact precision:

1. inherent_risk_score            — dual variant (WEIGHTED 8L+12I / CONSERVATIVE 20*max)
2. engagement_priority_score      — risk + tiered recency + scrutiny, capped at 100
3. plan_high_risk_coverage_pct    — covered/universe share, 100.0 on empty universe
4. engagement_hours_rollup        — per-item half-hour ceil, THEN sum (pinned order)
5. budget_utilization             — final vs provisional variants, 2dp half-up
6. finding_severity_rating        — composite L*I banded by the pinned config
7. action_plan_overdue_days       — whole-day granularity; due-today is not overdue
8. extension_cumulative_days      — approved-day shifts, caps 2 / 180 inclusive
9. committee_pack_snapshot        — pinned finalize-time aggregates
10. qa_rating_determination       — mean of four dimensions, FAIL/PASS boundaries
"""
from decimal import Decimal

from db import db
from util import CLOCK, dec, days_overdue, full_months_between, item_hours, parse_dt, round2

# --- calculation 1: inherent_risk_score ---
WEIGHTED_LIKELIHOOD_COEF = 8
WEIGHTED_IMPACT_COEF = 12
CONSERVATIVE_AXIS_MULTIPLIER = 20
TIER_CRITICAL_MIN = 85
TIER_HIGH_MIN = 70
TIER_MODERATE_MIN = 40


def compute_risk_score(likelihood: int, impact: int, regulatory_scrutiny: bool):
    """Variant pinned at creation: CONSERVATIVE iff the entity is under scrutiny."""
    if regulatory_scrutiny:
        return "CONSERVATIVE", CONSERVATIVE_AXIS_MULTIPLIER * max(likelihood, impact)
    return "WEIGHTED", WEIGHTED_LIKELIHOOD_COEF * likelihood + WEIGHTED_IMPACT_COEF * impact


def risk_tier(score: int) -> str:
    if score >= TIER_CRITICAL_MIN:
        return "CRITICAL"
    if score >= TIER_HIGH_MIN:
        return "HIGH"
    if score >= TIER_MODERATE_MIN:
        return "MODERATE"
    return "LOW"


# --- calculation 2: engagement_priority_score ---
def compute_priority_score(entity) -> int:
    risk = entity.get("current_inherent_risk_score") or 0
    last = entity.get("last_audit_completed_at")
    if last is None:
        months = 999  # never audited => infinite recency
    else:
        months = full_months_between(parse_dt(last).date(), CLOCK.today())
    if months >= 36:
        recency = 30
    elif months >= 24:
        recency = 20
    elif months >= 12:
        recency = 10
    else:
        recency = 0
    scrutiny = 1 if entity.get("regulatory_scrutiny") else 0
    return min(100, risk + recency + 15 * scrutiny)


# --- calculation 3: plan_high_risk_coverage_pct ---
HIGH_RISK_SCORE_MIN = 70


def compute_plan_coverage(plan_id) -> float:
    universe = [
        e for e in db["auditable_entities"].values()
        if e["status"] == "ACTIVE"
        and e.get("current_inherent_risk_score") is not None
        and e["current_inherent_risk_score"] >= HIGH_RISK_SCORE_MIN
    ]
    if not universe:
        return 100.0
    covered_ids = {
        eng["auditable_entity_id"]
        for eng in db["engagements"].values()
        if eng["audit_plan_id"] == plan_id and eng["status"] != "CANCELLED"
    }
    covered = [e for e in universe if e["id"] in covered_ids]
    return round2(Decimal(100) * Decimal(len(covered)) / Decimal(len(universe)))


# --- calculations 4 & 5: engagement_hours_rollup + budget_utilization ---
def engagement_hours(engagement_id):
    """Returns (signed_count, actual_hours Decimal, provisional_hours Decimal).
    Per-item rounding FIRST (ceil to 0.5), then summation — pinned order."""
    signed_count = 0
    actual = Decimal(0)
    provisional = Decimal(0)
    for wp in db["workpapers"].values():
        if wp["engagement_id"] != engagement_id:
            continue
        if wp["status"] == "SIGNED_OFF":
            signed_count += 1
            actual += item_hours(wp["hours_worked"])
            provisional += item_hours(wp["hours_worked"])
        elif wp["status"] == "SUBMITTED":
            provisional += item_hours(wp["hours_worked"])
    return signed_count, actual, provisional


def utilization(hours: Decimal, budget_hours) -> float:
    return round2(Decimal(100) * hours / dec(budget_hours))


def signoff_would_exceed_budget(eng, wp) -> bool:
    """Fiscal gate: current actual + this item <= budget * 1.10 (110%)."""
    prospective = dec(eng["actual_hours"]) + item_hours(wp["hours_worked"])
    cap = dec(eng["budget_hours"]) * dec("1.10")
    return prospective > cap


# --- calculation 6: finding_severity_rating ---
def compute_severity(composite: int, config) -> str:
    """All band boundaries inclusive; config pinned on the finding at creation."""
    if composite >= config["critical_min"]:
        return "CRITICAL"
    if composite >= config["high_min"]:
        return "HIGH"
    if composite >= config["moderate_min"]:
        return "MODERATE"
    return "LOW"


def config_bands_valid(moderate_min: int, high_min: int, critical_min: int) -> bool:
    return 1 <= moderate_min < high_min < critical_min <= 25


# --- calculation 7: action_plan_overdue_days ---
def is_overdue(action_plan) -> bool:
    """Not VALIDATED and at least one full day overdue against the logical clock;
    due today (0 days) is not overdue."""
    if action_plan["status"] == "VALIDATED":
        return False
    return days_overdue(action_plan["due_date"], CLOCK) >= 1


# --- calculation 8: extension_cumulative_days ---
MAX_EXTENSIONS_PER_PLAN = 2
MAX_CUMULATIVE_EXTENSION_DAYS = 180


# --- calculation 9: committee_pack_snapshot ---
def compute_pack_snapshot(pack):
    engagements_all = [
        e for e in db["engagements"].values()
        if e["audit_plan_id"] == pack["audit_plan_id"]
    ]
    non_cancelled = [e for e in engagements_all if e["status"] != "CANCELLED"]
    if not non_cancelled:
        completion = 0.0
    else:
        closed = [e for e in non_cancelled if e["status"] == "CLOSED"]
        completion = round2(Decimal(100) * Decimal(len(closed)) / Decimal(len(non_cancelled)))
    # Findings reach through ALL engagements of the plan, CANCELLED included.
    eng_ids = {e["id"] for e in engagements_all}
    plan_findings = [f for f in db["findings"].values() if f["engagement_id"] in eng_ids]
    finding_ids = {f["id"] for f in plan_findings}
    overdue = len([
        ap for ap in db["action_plans"].values()
        if ap["finding_id"] in finding_ids and is_overdue(ap)
    ])
    resolved = [f for f in plan_findings if f["status"] in ("AGREED", "ESCALATED", "FINAL")]
    critical = len([f for f in resolved if f["severity"] == "CRITICAL"])
    high = len([f for f in resolved if f["severity"] == "HIGH"])
    return {
        "snapshot_plan_completion_pct": completion,
        "snapshot_overdue_action_count": overdue,
        "snapshot_critical_findings": critical,
        "snapshot_high_findings": high,
    }


# --- calculation 10: qa_rating_determination ---
def compute_qa_overall(doc: int, fieldwork: int, reporting: int, independence: int):
    """overall_score = round_half_up(mean, 2). FAIL if any dimension <= 2 or
    overall < 3.0; PASS if every dimension >= 4 and overall >= 4.0; else
    PASS_WITH_DEFICIENCIES. Boundaries: 3.0 escapes FAIL; PASS requires 4.0."""
    overall_dec = (Decimal(doc + fieldwork + reporting + independence) / Decimal(4)).quantize(
        Decimal("0.01"), rounding="ROUND_HALF_UP"
    )
    dims = (doc, fieldwork, reporting, independence)
    if min(dims) <= 2 or overall_dec < Decimal("3.0"):
        rating = "FAIL"
    elif min(dims) >= 4 and overall_dec >= Decimal("4.0"):
        rating = "PASS"
    else:
        rating = "PASS_WITH_DEFICIENCIES"
    return float(overall_dec), rating
