"""Business logic: constants, calculations, and state-transition cascades."""

import math
from datetime import date, timedelta

import db
from helpers import bump, clock_date


def _to_date(v):
    if isinstance(v, date):
        return v
    return date(int(v[0:4]), int(v[5:7]), int(v[8:10]))

# ---------------------------------------------------------------------------
# Constants (scaffold calculations tables)
# ---------------------------------------------------------------------------

TIER_ORDER = ["ULTRA_LOW_BUDGET", "MODIFIED_LOW_BUDGET", "LOW_BUDGET", "BASIC"]

TIER_CAPS = {
    "ULTRA_LOW_BUDGET": 30000000,
    "MODIFIED_LOW_BUDGET": 75000000,
    "LOW_BUDGET": 250000000,
    "BASIC": None,  # uncapped
}

BOND_REQUIRED_BY_TIER = {
    "ULTRA_LOW_BUDGET": 2500000,
    "MODIFIED_LOW_BUDGET": 5000000,
    "LOW_BUDGET": 10000000,
    "BASIC": 25000000,
}

MIN_CREW_BY_TIER_DEPT = {
    "ULTRA_LOW_BUDGET": {"CAMERA": 1, "GRIP_ELECTRIC": 1, "SOUND": 1},
    "MODIFIED_LOW_BUDGET": {"CAMERA": 2, "GRIP_ELECTRIC": 2, "SOUND": 1},
    "LOW_BUDGET": {"CAMERA": 3, "GRIP_ELECTRIC": 2, "SOUND": 2},
    "BASIC": {"CAMERA": 4, "GRIP_ELECTRIC": 3, "SOUND": 2},
}

MEAL_WINDOW_MINUTES = 360
MEAL_PENALTY_UNIT_MINUTES = 30

TURNAROUND_HOURS_BY_TIER = {
    "ULTRA_LOW_BUDGET": 12,
    "MODIFIED_LOW_BUDGET": 12,
    "LOW_BUDGET": 10,
    "BASIC": 10,
}

CONTRIBUTION_RATE_NUM = {
    "ULTRA_LOW_BUDGET": 17,
    "MODIFIED_LOW_BUDGET": 18,
    "LOW_BUDGET": 19,
    "BASIC": 20,
}

DAILY_WAGE_CAP_CENTS = {
    "ULTRA_LOW_BUDGET": 100000,
    "MODIFIED_LOW_BUDGET": 150000,
    "LOW_BUDGET": 250000,
    "BASIC": 500000,
}

FILING_WINDOW_DAYS = 30
AUDIT_PENALTY_RATE_NUM = 110
GRIEVANCE_RESTRICTION_THRESHOLD = 2
MAX_REVIEW_ROUNDS = 3

OPEN_GRIEVANCE_STATUSES = {"FILED", "INVESTIGATING", "PROPOSED_SETTLEMENT", "ESCALATED"}


# ---------------------------------------------------------------------------
# Calculation: budget_tier_selection
# ---------------------------------------------------------------------------

def tier_covers(tier, budget_cents):
    cap = TIER_CAPS[tier]
    return cap is None or budget_cents <= cap


def smallest_covering_tier(budget_cents):
    for tier in TIER_ORDER:
        if tier_covers(tier, budget_cents):
            return tier
    return "BASIC"


# ---------------------------------------------------------------------------
# Calculation: work_log_penalties
# ---------------------------------------------------------------------------

def round_half_up_div(numerator, denominator):
    """round_half_up(numerator / denominator) to whole units (both ints)."""
    return (2 * numerator + denominator) // (2 * denominator)


def compute_log_penalties(log):
    """Compute meal/turnaround penalty fields on the log dict in place."""
    assignment = db.crew_assignments[log["crew_assignment_id"]]
    production = db.productions[assignment["production_id"]]
    rate = assignment["daily_rate_cents"]
    tier = production["agreement_tier"]

    call = log["call_time_minutes"]
    wrap = log["wrap_time_minutes"]
    breaks = log.get("meal_breaks") or []
    if breaks:
        first_meal_start = min(b["start_minutes"] for b in breaks)
    else:
        first_meal_start = wrap

    delay_minutes = first_meal_start - (call + MEAL_WINDOW_MINUTES)
    if delay_minutes <= 0:
        units = 0
    else:
        units = math.ceil(delay_minutes / MEAL_PENALTY_UNIT_MINUTES)
    # Pinned rounding order: round the per-unit penalty FIRST, then multiply.
    unit_penalty_cents = round_half_up_div(rate, 32)
    meal_penalty_cents = units * unit_penalty_cents

    # Turnaround: previous calendar day's non-VOIDED log of the same assignment.
    prev_date = (_to_date(log["work_date"]) - timedelta(days=1)).isoformat()
    prev_log = None
    for other in db.work_day_logs.values():
        if (other["crew_assignment_id"] == log["crew_assignment_id"]
                and other["work_date"] == prev_date
                and other["status"] != "VOIDED"
                and other["id"] != log["id"]):
            prev_log = other
            break

    turnaround_violation = False
    turnaround_penalty_cents = 0
    if prev_log is not None:
        elapsed_rest_minutes = (1440 - prev_log["wrap_time_minutes"]) + call
        threshold = TURNAROUND_HOURS_BY_TIER[tier] * 60
        if elapsed_rest_minutes < threshold:
            turnaround_violation = True
            turnaround_penalty_cents = round_half_up_div(rate, 8)

    log["meal_penalty_units"] = units
    log["meal_penalty_cents"] = meal_penalty_cents
    log["turnaround_violation"] = turnaround_violation
    log["turnaround_penalty_cents"] = turnaround_penalty_cents
    log["penalty_cents"] = meal_penalty_cents + turnaround_penalty_cents


# ---------------------------------------------------------------------------
# Calculation: contribution_dues
# ---------------------------------------------------------------------------

def compute_dues(production, logs, tier):
    """Returns (gross_wages_cents, contributions_due_cents) for the given logs
    at the given tier. Multiply first, then one round_half_up at the end."""
    cap = DAILY_WAGE_CAP_CENTS[tier]
    rate_num = CONTRIBUTION_RATE_NUM[tier]
    gross = 0
    for log in logs:
        assignment = db.crew_assignments[log["crew_assignment_id"]]
        gross += min(assignment["daily_rate_cents"], cap)
    due = round_half_up_div(gross * rate_num, 100)
    return gross, due


# ---------------------------------------------------------------------------
# Calculation: grievance_filing_deadline (two passes, no further iteration)
# ---------------------------------------------------------------------------

def _fm_effective_end_for_tolling(event):
    if event.get("end_date") is not None:
        return _to_date(event["end_date"])
    if event.get("lifted_date") is not None:
        return _to_date(event["lifted_date"])
    return clock_date()


def compute_filing_deadline(production_id, incident_date):
    """Returns the final deadline date (inclusive)."""
    provisional_deadline = incident_date + timedelta(days=FILING_WINDOW_DAYS)

    intervals = []
    for event in db.force_majeure_events.values():
        if event["production_id"] != production_id:
            continue
        start = _to_date(event["start_date"])
        end = _fm_effective_end_for_tolling(event)
        if end > start:
            intervals.append((start, end))

    # Merge overlapping/adjacent intervals into their union.
    intervals.sort()
    merged = []
    for start, end in intervals:
        if merged and start <= merged[-1][1]:
            if end > merged[-1][1]:
                merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))

    # Intersect with [incident_date, provisional_deadline]; whole days, end-exclusive.
    tolling_days = 0
    for start, end in merged:
        lo = max(start, incident_date)
        hi = min(end, provisional_deadline)
        if hi > lo:
            tolling_days += (hi - lo).days

    return incident_date + timedelta(days=FILING_WINDOW_DAYS + tolling_days)


# ---------------------------------------------------------------------------
# Calculation: audit_assessment
# ---------------------------------------------------------------------------

def compute_assessment(production, scope_period_indices):
    """Returns (assessment_cents, alt_assessment_cents)."""
    scope = set(scope_period_indices)
    tier = production["agreement_tier"]
    per_period_total = 0
    net_shortfall = 0
    for report in db.contribution_reports.values():
        if (report["production_id"] != production["id"]
                or report["status"] != "ACCEPTED"
                or report["period_index"] not in scope):
            continue
        logs = []
        for lid in report["work_day_log_ids"]:
            log = db.work_day_logs.get(lid)
            if log is not None and log["status"] != "VOIDED":
                logs.append(log)
        _gross, expected = compute_dues(production, logs, tier)
        shortfall = expected - (report["final_contributions_due_cents"] or 0)
        # per_period variant: floor each period at zero BEFORE the penalty.
        per_period_total += round_half_up_div(max(0, shortfall) * AUDIT_PENALTY_RATE_NUM, 100)
        net_shortfall += shortfall
    aggregate = round_half_up_div(max(0, net_shortfall) * AUDIT_PENALTY_RATE_NUM, 100)
    return per_period_total, aggregate


# ---------------------------------------------------------------------------
# Calculation: posture_derivation (pinned priority FROZEN > RESTRICTED > CLEAR)
# ---------------------------------------------------------------------------

def recompute_posture(production):
    pid = production["id"]
    for event in db.force_majeure_events.values():
        if event["production_id"] == pid and event["status"] == "ACTIVE":
            production["compliance_posture"] = "FROZEN"
            return production["compliance_posture"]

    open_grievances = sum(
        1 for g in db.grievances.values()
        if g["production_id"] == pid and g["status"] in OPEN_GRIEVANCE_STATUSES
    )
    unpaid_findings = any(
        a["production_id"] == pid
        and a["status"] == "FINDINGS_ISSUED"
        and a["assessment_paid_cents"] < (a["assessment_cents"] or 0)
        for a in db.audits.values()
    )
    bond = None
    for b in db.bonds.values():
        if b["production_id"] == pid:
            bond = b
            break
    bond_bad = bond is not None and bond["status"] in ("UNDERFUNDED", "FORFEITED")

    if (open_grievances >= GRIEVANCE_RESTRICTION_THRESHOLD
            or bond_bad
            or unpaid_findings):
        production["compliance_posture"] = "RESTRICTED"
    else:
        production["compliance_posture"] = "CLEAR"
    return production["compliance_posture"]


# ---------------------------------------------------------------------------
# Cascading transitions
# ---------------------------------------------------------------------------

def bond_recompute_held(bond):
    bond["amount_held_cents"] = (
        bond["total_posted_cents"]
        - bond["total_released_cents"]
        - bond["total_forfeited_cents"]
    )


def company_reinstatement_check(company):
    """After a bond re-post: SUSPENDED -> SIGNATORY when no bond of any of the
    company's productions remains FORFEITED or UNDERFUNDED."""
    if company["status"] != "SUSPENDED":
        return
    production_ids = {
        p["id"] for p in db.productions.values()
        if p["producer_company_id"] == company["id"]
    }
    for b in db.bonds.values():
        if b["production_id"] in production_ids and b["status"] in ("FORFEITED", "UNDERFUNDED"):
            return
    company["status"] = "SIGNATORY"
    bump(company)


def suspend_company_of_production(production):
    company = db.companies.get(production["producer_company_id"])
    if company is not None and company["status"] == "SIGNATORY":
        company["status"] = "SUSPENDED"
        bump(company)


def forfeit_bond(bond):
    """Bond {POSTED, UNDERFUNDED} -> FORFEITED (full forfeiture), cascading to
    the company and the production posture."""
    production = db.productions[bond["production_id"]]
    bond["total_forfeited_cents"] += bond["amount_held_cents"]
    bond_recompute_held(bond)  # amount_held_cents := 0
    bond["status"] = "FORFEITED"
    bump(bond)
    suspend_company_of_production(production)
    recompute_posture(production)


def apply_tier_upgrade_cascade(production):
    """After a budget revision changed the tier: recompute the bond requirement
    and flip POSTED -> UNDERFUNDED when the held amount falls short."""
    bond = None
    for b in db.bonds.values():
        if b["production_id"] == production["id"]:
            bond = b
            break
    if bond is None:
        return
    bond["amount_required_cents"] = BOND_REQUIRED_BY_TIER[production["agreement_tier"]]
    bond_recompute_held(bond)
    if bond["status"] == "POSTED" and bond["amount_held_cents"] < bond["amount_required_cents"]:
        bond["status"] = "UNDERFUNDED"
        bump(bond)
    recompute_posture(production)
