"""Calculations: submittal required dates, RFI due dates, business-day duration,
impact cost delta, escalation levels, expediting priority score, reviewer selector,
crew window conflict check, owner report metrics."""
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import store
from timeutil import (
    add_business_days,
    sub_business_days,
    business_day_duration,
)


# ---------------------------------------------------------------------------
# Constants (scaffold calculations)
# ---------------------------------------------------------------------------

SUB_MARKUP_PCT = Decimal("0.10")
GC_MARKUP_TIER1 = Decimal("0.05")
GC_MARKUP_TIER2 = Decimal("0.07")
BOND_PCT = Decimal("0.02")
CONTINGENCY_ALLOWANCE_PCT = Decimal("0.15")

L2_MIN_DAYS = 7
L3_MIN_DAYS = 14

W_LATE = 3
LATE_CAP_DAYS = 20
W_CRIT = 1
W_FLOAT = 2
SCORE_CAP = 100

CRITICALITY_POINTS = {"CRITICAL": 40, "HIGH": 20, "STANDARD": 0}

LLI_ADVANCE_CHAIN = ["IDENTIFIED", "QUOTED", "PO_ISSUED", "IN_PRODUCTION", "SHIPPED", "DELIVERED"]


# ---------------------------------------------------------------------------
# Clock helpers
# ---------------------------------------------------------------------------

def clock_date():
    """Current clock UTC date."""
    return store.clock.date()


def holidays_set(project):
    return project["_holidays_set"]


# ---------------------------------------------------------------------------
# Submittal required dates (PRD 3.1)
# ---------------------------------------------------------------------------

def recompute_submittal_dates(submittal, section, project):
    """Backward business-day pass: approval first, submission second."""
    rod = submittal.get("required_on_site_date")
    if rod is None:
        submittal["required_approval_date"] = None
        submittal["required_submission_date"] = None
        return
    hol = holidays_set(project)
    approval = sub_business_days(rod, section["lead_time_days"], hol)
    submission = sub_business_days(approval, section["review_days"], hol)
    submittal["required_approval_date"] = approval
    submittal["required_submission_date"] = submission


# ---------------------------------------------------------------------------
# Impact cost delta (PRD 3.6)
# ---------------------------------------------------------------------------

def _layer_round(x):
    """Round to whole cents, half-up, at every layer."""
    return int(Decimal(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def impact_cost_delta_provisional(estimated_cost_cents):
    """PROVISIONAL variant: base=estimated, tier1, includes allowance layer."""
    base = Decimal(estimated_cost_cents)
    layer1 = _layer_round(base * (1 + SUB_MARKUP_PCT))
    layer2 = _layer_round(Decimal(layer1) * (1 + GC_MARKUP_TIER1))
    layer2a = _layer_round(Decimal(layer2) * (1 + CONTINGENCY_ALLOWANCE_PCT))
    delta = _layer_round(Decimal(layer2a) * (1 + BOND_PCT))
    return delta


def impact_cost_delta_final(sub_quote_cents, gc_markup_tier):
    """FINAL variant: base=sub_quote, no allowance; tier chooses GC markup."""
    markup = GC_MARKUP_TIER2 if gc_markup_tier == 2 else GC_MARKUP_TIER1
    base = Decimal(sub_quote_cents)
    layer1 = _layer_round(base * (1 + SUB_MARKUP_PCT))
    layer2 = _layer_round(Decimal(layer1) * (1 + markup))
    delta = _layer_round(Decimal(layer2) * (1 + BOND_PCT))
    return delta


def select_gc_tier(spent_before, threshold):
    return 2 if spent_before >= threshold else 1


# ---------------------------------------------------------------------------
# Long-lead item computations (PRD 3.4)
# ---------------------------------------------------------------------------

def compute_days_late(lli):
    if lli["status"] == "DELIVERED":
        return 0
    rod = lli.get("required_on_site_date")
    if rod is None:
        return 0
    cd = clock_date()
    if cd <= rod:
        return 0
    return (cd - rod).days


def compute_escalation_level(days_late):
    if days_late <= 0:
        return 0
    if days_late >= L3_MIN_DAYS:
        return 3
    if days_late >= L2_MIN_DAYS:
        return 2
    return 1


def compute_priority_score(lli, submittal):
    days_late = lli["days_late"]
    crit_points = CRITICALITY_POINTS.get(lli["criticality"], 0)
    rod = lli.get("required_on_site_date")
    remaining_float = 0
    if rod is not None:
        remaining_float = (rod - clock_date()).days  # negative when late
    raw = (
        W_LATE * min(days_late, LATE_CAP_DAYS)
        + W_CRIT * crit_points
        + W_FLOAT * max(0, -remaining_float)
    )
    if submittal is not None and submittal.get("deferral_status") == "DEFERRED_APPROVED":
        raw = raw // 2
    return max(0, min(SCORE_CAP, raw))


def recompute_lli(lli, submittal):
    """Recompute days_late/escalation_level/priority_score; returns (old_level, new_level)."""
    old_level = lli["escalation_level"]
    lli["days_late"] = compute_days_late(lli)
    lli["escalation_level"] = compute_escalation_level(lli["days_late"])
    lli["priority_score"] = compute_priority_score(lli, submittal)
    return old_level, lli["escalation_level"]


# ---------------------------------------------------------------------------
# Reviewer selector (scaffold calculations)
# ---------------------------------------------------------------------------

def select_reviewer(project_id, required_discipline):
    """Candidates: ACTIVE, discipline match, open_review_count < review_capacity.
    Ranked by open_review_count ASC, created_at ASC. Returns None when empty."""
    candidates = [
        r for r in store.reviewers.values()
        if r["project_id"] == project_id
        and r["reviewer_status"] == "ACTIVE"
        and r["discipline"] == required_discipline
        and r["open_review_count"] < r["review_capacity"]
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda r: (r["open_review_count"], r["_seq"]))
    return candidates[0]


# ---------------------------------------------------------------------------
# Crew window conflict check (PRD 3.7)
# ---------------------------------------------------------------------------

def crew_window_conflict(project, candidate, exclude_id=None):
    """Check candidate {subcontractor_id, start_date, end_date} against other
    non-CANCELLED activities of the same sub. Half-open windows; buffer days of
    gap allowed."""
    buffer = timedelta(days=project["mobilization_buffer_days"])
    w_start = candidate["start_date"]
    w_end = candidate["end_date"]
    sub_id = candidate["subcontractor_id"]
    for other in store.installation_activities.values():
        if other["project_id"] != project["id"]:
            continue
        if other["subcontractor_id"] != sub_id:
            continue
        if other["status"] == "CANCELLED":
            continue
        if exclude_id is not None and other["id"] == exclude_id:
            continue
        x_start = other["start_date"]
        x_end = other["end_date"]
        # conflict iff W.start < X.end + buffer AND X.start < W.end + buffer
        if w_start < (x_end + buffer) and x_start < (w_end + buffer):
            return True
    return False


# ---------------------------------------------------------------------------
# Owner report metrics (PRD 3.9)
# ---------------------------------------------------------------------------

def compute_owner_report_metrics(project_id, period_start, period_end):
    """Returns dict with the five metrics."""
    open_submittals = sum(
        1 for s in store.submittals.values()
        if s["project_id"] == project_id and s["review_status"] not in ("CLOSED", "VOID")
    )
    overdue_rfis = sum(
        1 for r in store.rfis.values()
        if r["project_id"] == project_id and r["is_overdue"]
    )
    # avg_rfi_response_days
    project = store.projects.get(project_id)
    hol = project["_holidays_set"] if project else set()
    durations = []
    for r in store.rfis.values():
        if r["project_id"] != project_id:
            continue
        if r["status"] not in ("ANSWERED", "CLOSED"):
            continue
        answered = r.get("answered_date")
        opened = r.get("opened_date")
        if answered is None or opened is None:
            continue
        if not (period_start <= answered <= period_end):
            continue
        durations.append(business_day_duration(opened, answered, hol))
    if durations:
        mean = Decimal(sum(durations)) / Decimal(len(durations))
        avg_rfi_response_days = float(mean.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    else:
        avg_rfi_response_days = 0.0

    # first_pass_yield_pct — submittals whose revision_number 0 revision has returned_date in period
    returned = 0
    passed = 0
    for rev in store.revisions.values():
        sub = store.submittals.get(rev["submittal_id"])
        if sub is None or sub["project_id"] != project_id:
            continue
        if rev["revision_number"] != 0:
            continue
        rd = rev.get("returned_date")
        if rd is None:
            continue
        if not (period_start <= rd <= period_end):
            continue
        returned += 1
        if rev.get("action_code") in ("A", "B"):
            passed += 1
    if returned:
        pct = (Decimal(passed) * Decimal(100) / Decimal(returned)).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP
        )
        first_pass_yield_pct = float(pct)
    else:
        first_pass_yield_pct = 0.0

    open_escalation_events = sum(
        1 for e in store.escalation_events.values()
        if e["project_id"] == project_id and e["event_date"] <= period_end
    )

    return {
        "open_submittals": open_submittals,
        "overdue_rfis": overdue_rfis,
        "avg_rfi_response_days": avg_rfi_response_days,
        "first_pass_yield_pct": first_pass_yield_pct,
        "open_escalation_events": open_escalation_events,
    }
