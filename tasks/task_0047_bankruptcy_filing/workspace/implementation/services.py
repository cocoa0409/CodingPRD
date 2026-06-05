"""Business logic: calculations, derived-field reconciliation, state machines.

All monetary amounts are integer cents (PRD 2.8); arithmetic is exact integer
math with no rounding. Where a value could go negative it is floored at zero.
"""

from datetime import datetime, timezone

import db

# Calculation constants (SCAFFOLD 1.3).
ABUSE_FLOOR_CENTS = 1500000          # PRD 3.2: abuse floor = $15,000
COMMITMENT_PROJECTION_MONTHS = 60    # PRD 3.2: 60-month projection horizon
ROOM_BUFFER_MINUTES = 30             # PRD 3.5 / SCAFFOLD 1.3: room cleanup gap

# Class rank for the Chapter 13 waterfall (PRD 3.8 / SCAFFOLD 1.3):
# PRIORITY first, then SECURED, then UNSECURED.
CLASS_RANK = {"PRIORITY": 0, "SECURED": 1, "UNSECURED": 2}


# ---------------------------------------------------------------------------
# Means test (PRD 3.2 / SCAFFOLD 1.3 means_test_evaluation)
# ---------------------------------------------------------------------------

def compute_means_test(cmi_monthly_cents, monthly_expenses_cents, median_annual_income_cents):
    annualized_cmi_cents = cmi_monthly_cents * 12
    disposable_monthly_cents = max(0, cmi_monthly_cents - monthly_expenses_cents)

    # Step 1 — income screen against state+household median (<= passes).
    if annualized_cmi_cents <= median_annual_income_cents:
        result = "PRESUMPTION_OK"
    else:
        # Step 2 — disposable-income screen: 60-month projection vs abuse floor.
        projected_disposable_cents = disposable_monthly_cents * COMMITMENT_PROJECTION_MONTHS
        if projected_disposable_cents >= ABUSE_FLOOR_CENTS:
            result = "PRESUMPTION_ABUSE"
        else:
            result = "PRESUMPTION_OK"

    return {
        "annualized_cmi_cents": annualized_cmi_cents,
        "disposable_monthly_cents": disposable_monthly_cents,
        "result": result,
    }


# ---------------------------------------------------------------------------
# Derived case fields from Schedules (PRD 3.3 / 3.10)
# ---------------------------------------------------------------------------

def case_schedule_rows(case_id):
    return [s for s in db.schedules.values() if s["case_id"] == case_id]


def gross_asset_cents(case_id):
    """Sum of asset_value_cents over Schedule A and B rows (PRD 3.3)."""
    return sum(
        s.get("asset_value_cents", 0)
        for s in case_schedule_rows(case_id)
        if s["schedule_letter"] in ("A", "B")
    )


def total_exempt_cents(case_id):
    """Sum of claimed_exempt_value_cents over Schedule C rows (PRD 3.3)."""
    return sum(
        s.get("claimed_exempt_value_cents", 0)
        for s in case_schedule_rows(case_id)
        if s["schedule_letter"] == "C"
    )


def recompute_estate_fields(case):
    """Reconcile total_exempt_value_cents and nonexempt_estate_cents (PRD 3.3).

    nonexempt = gross(A+B) - total_exempt, floored at 0.
    """
    case_id = case["id"]
    total_exempt = total_exempt_cents(case_id)
    gross = gross_asset_cents(case_id)
    case["total_exempt_value_cents"] = total_exempt
    case["nonexempt_estate_cents"] = max(0, gross - total_exempt)


# ---------------------------------------------------------------------------
# Meeting slot conflict detection (PRD 3.5 / SCAFFOLD 1.3)
# ---------------------------------------------------------------------------

def parse_dt(value):
    """Parse an ISO 8601 UTC timestamp into a tz-aware datetime."""
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def trustee_conflict(trustee_id, new_start, new_end, exclude_id=None):
    """Half-open overlap on the same trustee_id among SCHEDULED meetings.

    Conflict iff new.start < existing.end AND existing.start < new.end.
    Back-to-back (shared endpoint) does NOT conflict.
    """
    for m in db.meetings.values():
        if m["id"] == exclude_id:
            continue
        if m["trustee_id"] != trustee_id or m["status"] != "SCHEDULED":
            continue
        m_start = parse_dt(m["scheduled_start"])
        m_end = parse_dt(m["scheduled_end"])
        if new_start < m_end and m_start < new_end:
            return True
    return False


def room_conflict(room_code, new_start, new_end, exclude_id=None):
    """Padded (30-min buffer) overlap on the same room_code among SCHEDULED.

    The room is busy over [m.start - BUFFER, m.end + BUFFER); conflict iff the
    new raw interval intersects that padded window. Adjacency is NOT allowed.
    """
    from datetime import timedelta

    buffer = timedelta(minutes=ROOM_BUFFER_MINUTES)
    for m in db.meetings.values():
        if m["id"] == exclude_id:
            continue
        if m["room_code"] != room_code or m["status"] != "SCHEDULED":
            continue
        busy_start = parse_dt(m["scheduled_start"]) - buffer
        busy_end = parse_dt(m["scheduled_end"]) + buffer
        if new_start < busy_end and busy_start < new_end:
            return True
    return False


# ---------------------------------------------------------------------------
# Plan feasibility (PRD 3.7 / SCAFFOLD 1.3 plan_feasibility_check)
# ---------------------------------------------------------------------------

def priority_floor_cents(case_id):
    """Sum of allowed_amount_cents over PRIORITY debts on the case (PRD 3.7)."""
    return sum(
        d["allowed_amount_cents"]
        for d in db.debts.values()
        if d["case_id"] == case_id and d["debt_class"] == "PRIORITY"
    )


# ---------------------------------------------------------------------------
# Chapter 13 waterfall distribution (PRD 3.8 / SCAFFOLD 1.3)
# ---------------------------------------------------------------------------

def waterfall_distribution(plan):
    """Distribute paid_to_date_cents across the case's debts in priority order.

    Order: class_rank ASC (PRIORITY, SECURED, UNSECURED), then created_at ASC,
    then id ASC. Only debts with allowed_amount_cents > 0 participate.
    Fill-in-full (not pro-rata): each debt receives min(remaining_fund, owed).
    """
    case_id = plan["case_id"]
    fund = plan["paid_to_date_cents"]

    participating = [
        d for d in db.debts.values()
        if d["case_id"] == case_id and d["allowed_amount_cents"] > 0
    ]
    ordered = sorted(
        participating,
        key=lambda d: (CLASS_RANK.get(d["debt_class"], 99), d["created_at"], d["id"]),
    )

    distribution = {}
    for debt in ordered:
        owed = debt["allowed_amount_cents"]
        pay = min(fund, owed)
        distribution[debt["id"]] = pay
        fund -= pay

    surplus_cents = fund
    return {
        "plan_id": plan["id"],
        "paid_to_date_cents": plan["paid_to_date_cents"],
        "distribution": distribution,
        "surplus_cents": surplus_cents,
    }


# ---------------------------------------------------------------------------
# Plan activity helper (PRD 3.7)
# ---------------------------------------------------------------------------

def active_plan(case_id):
    """The case's latest-by-created_at non-DENIED plan, or None.

    PRD 3.7: is_active is true only for the case's latest-by-created_at plan
    that has not been denied.
    """
    candidates = [
        p for p in db.plans.values()
        if p["case_id"] == case_id and p["status"] != "DENIED"
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: (p["created_at"], p["id"]))
