"""Calculation rules (SCAFFOLD 1.3 / PRD 2.9, 3.1-3.9).

All money is Decimal, rounded half-up, at exactly the points the PRD pins.
"""

import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

# --- costing constants (SCAFFOLD calculations.work_order_billable_amount) ---
STANDARD_LABOR_RATE = Decimal("80.00")
AFTER_HOURS_MULTIPLIER = Decimal("1.5")
LABOR_CAP_HOURS = Decimal("12")
MIN_CALLOUT_AMOUNT = Decimal("150.00")
PRIORITY_SURCHARGE = {
    "P1": Decimal("0.25"),
    "P2": Decimal("0.10"),
    "P3": Decimal("0"),
    "P4": Decimal("0"),
}
SLA_RESPONSE_PENALTY_PCT = Decimal("0.10")
SLA_RESOLVE_PENALTY_PCT = Decimal("0.15")
SLA_PENALTY_CAP_PCT = Decimal("0.25")

# --- vendor performance ---
W_RESPONSE = Decimal("0.4")
W_RESOLVE = Decimal("0.3")
W_QA = Decimal("0.3")
ROLLING_WINDOW_N = 3
PROBATION_STRIKES = 2
SUSPENSION_STRIKES = 3

# --- asset condition ---
RUNTIME_DECAY_BLOCK_HOURS = Decimal("1000")
RUNTIME_DECAY_POINTS = Decimal("5")
FAILURE_PENALTY_POINTS = Decimal("12")
RETIREMENT_SCORE_THRESHOLD = Decimal("20")

# --- pm promotion defaults ---
PM_DEFAULT_HOURS = 3
PM_DEFAULT_PARTS = 200.00

# --- posture thresholds ---
FROZEN_OOS_CRITICAL_THRESHOLD = 1
RESTRICTED_OPEN_P1_THRESHOLD = 2

OPEN_WO_STATUSES = ("NEW", "DISPATCHED", "IN_PROGRESS", "PENDING_QA")


def D(value):
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def round2(value):
    return D(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def round3(value):
    return D(value).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def money(value):
    """Serialise a Decimal money value as a JSON number."""
    if value is None:
        return None
    return float(round2(value))


# ---------------------------------------------------------------------------
# work_order_billable_amount
# ---------------------------------------------------------------------------
def is_after_hours(reference_instant):
    hour = reference_instant.hour
    return hour < 8 or hour >= 18


def gross_amount(hours, parts, labor_rate, priority, reference_instant):
    """Core costing computation, rounded exactly once at the end."""
    hours = D(hours)
    parts = D(parts)
    rate = D(labor_rate)

    billed_hours = min(hours, LABOR_CAP_HOURS)
    labor = billed_hours * rate
    if is_after_hours(reference_instant):
        labor = labor * AFTER_HOURS_MULTIPLIER
    surcharge = labor * PRIORITY_SURCHARGE[priority]

    if parts <= Decimal("500"):
        markup_pct = Decimal("0.15")
    elif parts <= Decimal("2000"):
        markup_pct = Decimal("0.10")
    else:
        markup_pct = Decimal("0.05")
    parts_billed = parts * (Decimal("1") + markup_pct)

    gross = labor + surcharge + parts_billed
    if gross < MIN_CALLOUT_AMOUNT:
        gross = MIN_CALLOUT_AMOUNT
    return round2(gross)


def provisional_estimate(hours, parts, labor_rate, priority, reference_instant):
    return gross_amount(hours, parts, labor_rate, priority, reference_instant)


def final_settlement(hours, parts, labor_rate, priority, reference_instant, penalty_pct):
    gross = gross_amount(hours, parts, labor_rate, priority, reference_instant)
    penalty = round2(gross * D(penalty_pct))
    return round2(gross - penalty)


def penalty_pct_for(sla_response_met, sla_resolve_met):
    pct = Decimal("0")
    if sla_response_met is False:
        pct += SLA_RESPONSE_PENALTY_PCT
    if sla_resolve_met is False:
        pct += SLA_RESOLVE_PENALTY_PCT
    return min(SLA_PENALTY_CAP_PCT, pct)


# ---------------------------------------------------------------------------
# capital_project_budget
# ---------------------------------------------------------------------------
def contingency_pct_for(base_cost):
    base = D(base_cost)
    if base <= Decimal("100000"):
        return Decimal("0.10")
    if base <= Decimal("500000"):
        return Decimal("0.07")
    return Decimal("0.05")


# ---------------------------------------------------------------------------
# asset_condition_score
# ---------------------------------------------------------------------------
def condition_score(runtime_hours, failure_count):
    runtime = D(runtime_hours)
    blocks = Decimal(math.floor(runtime / RUNTIME_DECAY_BLOCK_HOURS))
    runtime_decay = blocks * RUNTIME_DECAY_POINTS
    failure_penalty = D(failure_count) * FAILURE_PENALTY_POINTS
    score = Decimal("100") - runtime_decay - failure_penalty
    score = max(Decimal("0"), min(Decimal("100"), score))
    return round2(score)


# ---------------------------------------------------------------------------
# sla_evaluation
# ---------------------------------------------------------------------------
def whole_minutes(start, end):
    return int((end - start).total_seconds() // 60)


def add_minutes(instant, minutes):
    return instant + timedelta(minutes=int(minutes))


# ---------------------------------------------------------------------------
# pm_compliance_state
# ---------------------------------------------------------------------------
def compliance_state(next_due_at, grace_days, clock):
    if next_due_at is None:
        return "ON_TIME"
    grace_end = next_due_at + timedelta(days=int(grace_days or 0))
    if clock < next_due_at:
        return "ON_TIME"
    if clock <= grace_end:
        return "DUE"
    return "OVERDUE"


# ---------------------------------------------------------------------------
# vendor_performance_score
# ---------------------------------------------------------------------------
def performance_score(selected, failed_qa_counts):
    """selected: list of COMPLETED dispatch rows; failed_qa_counts: {wo_id: int}."""
    n = len(selected)
    if n == 0:
        return round2(Decimal("100"))
    total = Decimal(n)
    response_hits = sum(1 for d in selected if d.get("sla_response_met") is True)
    resolve_hits = sum(1 for d in selected if d.get("sla_resolve_met") is True)
    qa_hits = sum(1 for d in selected if failed_qa_counts.get(d["work_order_id"], 0) == 0)
    score = Decimal("100") * (
        W_RESPONSE * (Decimal(response_hits) / total)
        + W_RESOLVE * (Decimal(resolve_hits) / total)
        + W_QA * (Decimal(qa_hits) / total)
    )
    return round2(score)
