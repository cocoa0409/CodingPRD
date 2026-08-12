"""Computed aggregates (SCAFFOLD 1.3 eac_cost_forecast, laydown_occupancy,
fatigue_eligibility; PRD 2.10). Every aggregate is recomputed from its input
set at read time — never adjusted by deltas that could drift.
"""
import math

import db

# eac_cost_forecast constants
HOURS_PER_SLIP_DAY = 8
DAILY_OVERHEAD_CENTS = 50000

COMMITTED_STATUSES = ("FROZEN", "SCHEDULED", "IN_PROGRESS", "ON_HOLD", "REOPENED")
PENDING_DISCOVERY_STATUSES = ("REPORTED", "TRIAGED")

# fatigue_eligibility constants
MIN_REST_HOURS = 10
RECOVERY_REST_HOURS = 14
REST_PENALTY = 10
NIGHT_PENALTY = 5
FATIGUE_SCORE_LIMIT = 20
FATIGUE_HOURS_LIMIT = 60
KEPT_ASSIGNMENT_STATUSES = ("ASSIGNED", "COMPLETED")


def turnaround_of_work_item(wi):
    return db.turnarounds.get(wi["turnaround_id"])


# --------------------------------------------------------------- work items
def remaining_hours(wi):
    actual = wi.get("actual_hours")
    if actual is None:
        actual = 0
    return max(0, wi["estimated_hours"] - actual)


def work_items_of(tid):
    return [w for w in db.work_items.values() if w["turnaround_id"] == tid]


def committed_cost_cents(tid):
    return sum(w["estimated_cost_cents"] for w in work_items_of(tid)
               if w["status"] in COMMITTED_STATUSES)


def critical_path_slip_hours(tid):
    total = 0
    for w in work_items_of(tid):
        if w["is_critical_path"] and w["status"] == "ON_HOLD":
            total += remaining_hours(w)
    return total


# -------------------------------------------------------------- discoveries
def discoveries_of(tid):
    return [d for d in db.discoveries.values() if d["turnaround_id"] == tid]


def pending_quote_cents(tid):
    return sum(d["quoted_cost_cents"] for d in discoveries_of(tid)
               if d["status"] in PENDING_DISCOVERY_STATUSES)


def contingency_remaining_cents(t):
    used = sum(d["authorized_cost_cents"] or 0 for d in discoveries_of(t["id"])
               if d["status"] == "AUTHORIZED")
    return t["contingency_budget_cents"] - used


# ------------------------------------------------------------------ reports
def reports_of(tid):
    return [r for r in db.daily_reports.values() if r["turnaround_id"] == tid]


def reported_cost_cents(tid):
    return sum(r["total_cost_cents"] or 0 for r in reports_of(tid)
               if r["status"] == "APPROVED")


# ------------------------------------------------------------------ forecast
def forecast(t):
    """Returns (committed, provisional, posture) per eac_cost_forecast.

    Pinned evaluation order: committed first, then provisional, then posture.
    """
    tid = t["id"]
    committed = committed_cost_cents(tid)
    slip = critical_path_slip_hours(tid)
    overrun = math.floor(slip / HOURS_PER_SLIP_DAY) * DAILY_OVERHEAD_CENTS
    provisional = committed + pending_quote_cents(tid) + overrun
    if committed > t["authorized_budget_cents"]:
        posture = "OVERRUN"
    elif provisional > t["authorized_budget_cents"]:
        posture = "AT_RISK"
    else:
        posture = "WITHIN_BUDGET"
    return committed, provisional, posture


def cost_posture(t):
    return forecast(t)[2]


# --------------------------------------------------------------- contractors
def badged_headcount(contractor_id):
    return sum(1 for w in db.workers.values()
               if w["contractor_id"] == contractor_id
               and w["badge_status"] in ("BADGED", "SUSPENDED"))


# ---------------------------------------------------------------- lay-down
def occupied_sqm(area_id):
    return sum(r["area_sqm"] for r in db.reservations.values()
               if r["laydown_area_id"] == area_id
               and r["status"] in ("RESERVED", "STAGED"))


# ------------------------------------------------------------------ fatigue
def _kept_assignment_rows(worker_id):
    """(shift.starts_at, seq, assignment, shift) for the fatigue input set,
    ordered by shift.starts_at ASC, tie-break assignment creation ASC."""
    rows = []
    for a in db.assignments.values():
        if a["worker_id"] != worker_id or a["status"] not in KEPT_ASSIGNMENT_STATUSES:
            continue
        shift = db.shifts.get(a["shift_id"])
        if shift is None:
            continue
        rows.append((shift["_starts_at"], a["_seq"], a, shift))
    rows.sort(key=lambda r: (r[0], r[1]))
    return rows


def _gap_hours(prev_shift, shift):
    return (shift["_starts_at"] - prev_shift["_ends_at"]).total_seconds() / 3600.0


def _penalty_walk(rows):
    score = 0
    prev_shift = None
    for _, _, _, shift in rows:
        if shift["shift_type"] == "NIGHT":
            score += NIGHT_PENALTY
        if prev_shift is not None:
            gap = _gap_hours(prev_shift, shift)
            if MIN_REST_HOURS <= gap < RECOVERY_REST_HOURS:
                score += REST_PENALTY
        prev_shift = shift
    return score


def fatigue_penalty_score(worker_id):
    return _penalty_walk(_kept_assignment_rows(worker_id))


def ledger_hours(worker_id):
    return sum(a["planned_hours"] for a in db.assignments.values()
               if a["worker_id"] == worker_id
               and a["status"] in KEPT_ASSIGNMENT_STATUSES)


def total_shift_hours(worker_id):
    return sum(a["actual_hours"] or 0 for a in db.assignments.values()
               if a["worker_id"] == worker_id and a["status"] == "COMPLETED")


def projected_fatigue_score(worker_id, candidate_shift):
    """PENALTY_WEIGHTED gate: insert the candidate's shift into the worker's
    ordering (candidate is newest, so it ties last on starts_at) and compute
    the projected penalty score."""
    rows = _kept_assignment_rows(worker_id)
    rows.append((candidate_shift["_starts_at"], float("inf"), None, candidate_shift))
    rows.sort(key=lambda r: (r[0], r[1]))
    return _penalty_walk(rows)
