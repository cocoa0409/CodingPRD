"""Calculation rules (SCAFFOLD Table 3, PRD §2.7, §2.8, §2.9).

All money is integer cents; multiplications round half-up to whole cents
PER POSITION before any aggregation (PRD §2.7). FTE totals sum raw values then
round half-up to two decimals (PRD §2.7).
"""
from decimal import Decimal, ROUND_HALF_UP

from db import db

MAX_SPAN_OF_CONTROL = 8


# ---------------------------------------------------------------------------
# Per-position cost
# ---------------------------------------------------------------------------
def _round_cents(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _round_2dp(value):
    return float(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _fte_decimal(fte):
    # fte comes in as a float; use its exact string form so e.g. 0.1 stays 0.1.
    return Decimal(str(fte))


def planned_cost_cents(position):
    """planned_cost_cents = round_half_up(grade.band_mid_cents * fte) (calc planned_cost_cents)."""
    grade = db.grades.get(position["grade_id"])
    if grade is None:
        return 0
    return _round_cents(Decimal(grade["band_mid_cents"]) * _fte_decimal(position["fte"]))


def actual_cost_cents(position):
    """round_half_up(active_incumbent.employee.annual_salary_cents * fte) when FILLED,
    else 0 (calc actual_cost_cents)."""
    if position["occupancy_status"] != "FILLED":
        return 0
    inc = _active_incumbent(position["id"])
    if inc is None:
        return 0
    emp = db.employees.get(inc["employee_id"])
    if emp is None:
        return 0
    return _round_cents(Decimal(emp["annual_salary_cents"]) * _fte_decimal(position["fte"]))


def _active_incumbent(position_id):
    for inc in db.incumbents.values():
        if inc["position_id"] == position_id and inc["status"] == "ACTIVE":
            return inc
    return None


# ---------------------------------------------------------------------------
# Cost-center aggregates
# ---------------------------------------------------------------------------
def _positions_of(cost_center_id):
    return [p for p in db.positions.values() if p["cost_center_id"] == cost_center_id]


def committed_cost_cents(cost_center_id):
    """Sum of per-position contributions for positions with lifecycle_status in
    {FUNDED, FROZEN}: actual basis if FILLED else planned basis. Each contribution
    is already rounded to whole cents; the sum is exact integer addition
    (calc committed_cost_cents — mode b of Rule 2)."""
    total = 0
    for p in _positions_of(cost_center_id):
        if p["lifecycle_status"] in ("FUNDED", "FROZEN"):
            if p["occupancy_status"] == "FILLED":
                total += actual_cost_cents(p)
            else:
                total += planned_cost_cents(p)
    return total


def committed_fte(cost_center_id):
    """Sum of fte over positions with lifecycle_status in {FUNDED, FROZEN};
    sum raw then round half-up to 2 decimals (calc committed_fte)."""
    total = Decimal("0")
    for p in _positions_of(cost_center_id):
        if p["lifecycle_status"] in ("FUNDED", "FROZEN"):
            total += _fte_decimal(p["fte"])
    return float(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def filled_fte(cost_center_id):
    """Sum of fte over positions with occupancy_status == FILLED;
    sum raw then round half-up to 2 decimals (calc filled_fte)."""
    total = Decimal("0")
    for p in _positions_of(cost_center_id):
        if p["occupancy_status"] == "FILLED":
            total += _fte_decimal(p["fte"])
    return float(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def adjusted_budget_cents(cost_center):
    """annual_budget_cents + sum(amount_cents) over APPLIED BudgetAdjustments
    (calc adjusted_budget_cents)."""
    total = cost_center["annual_budget_cents"]
    for b in db.budget_adjustments.values():
        if b["cost_center_id"] == cost_center["id"] and b["status"] == "APPLIED":
            total += b["amount_cents"]
    return total


def available_budget_cents(cost_center):
    """adjusted_budget_cents - committed_cost_cents (calc available_budget_cents)."""
    return adjusted_budget_cents(cost_center) - committed_cost_cents(cost_center["id"])


# ---------------------------------------------------------------------------
# Org chart
# ---------------------------------------------------------------------------
def span_of_control(position_id):
    """Count of positions whose manager_position_id == position_id and
    lifecycle_status != ABOLISHED (calc span_of_control)."""
    count = 0
    for p in db.positions.values():
        if p["manager_position_id"] == position_id and p["lifecycle_status"] != "ABOLISHED":
            count += 1
    return count


# ---------------------------------------------------------------------------
# Posture
# ---------------------------------------------------------------------------
def cost_center_posture(cost_center_id):
    """FROZEN if an ACTIVE FreezeOrder covers the current clock instant with
    half-open [from, to) semantics, else OPEN (calc cost_center_posture)."""
    now = db.current_utc
    for f in db.freeze_orders.values():
        if f["cost_center_id"] != cost_center_id:
            continue
        if f["status"] != "ACTIVE":
            continue
        if f["_from_dt"] <= now < f["_to_dt"]:
            return "FROZEN"
    return "OPEN"


# ---------------------------------------------------------------------------
# Reclass direction
# ---------------------------------------------------------------------------
def reclass_direction(from_rank, target_rank):
    if target_rank > from_rank:
        return "UPGRADE"
    if target_rank < from_rank:
        return "DOWNGRADE"
    return "LATERAL"
