"""Derived aggregates, budget posture, cascades, and computed-read panels.

All aggregates derive from the spend ledger (POSTED lines only) and from
OUTSTANDING accruals, per PRD section 2.8. A recomputation that changes a
parent resource is a mutation: updated_at refreshes and version increments.
"""
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

from db import store, touch

OPEN_WRITE_STATES = ("OPEN", "REOPENED")


# ---------------------------------------------------------------- thresholds
def department_thresholds():
    """The benchmark runs a single department; fall back to documented defaults."""
    depts = sorted(store.departments.values(), key=lambda d: d["_seq"])
    if depts:
        d = depts[0]
        return d["budget_warning_pct"], d["budget_critical_pct"]
    return 0.8, 0.95


def active_fiscal_period_id():
    opens = [p for p in store.fiscal_periods.values() if p["status"] == "OPEN"]
    if len(opens) == 1:
        return opens[0]["id"]
    return None


def derive_posture(consumed, allocated, warning, critical):
    """Exact-rational comparison, inclusive boundaries (PRD section 2.7)."""
    if allocated > 0:
        ratio = Fraction(consumed, allocated)
    elif consumed > 0:
        return "EXCEEDED"
    else:
        ratio = Fraction(0)
    if ratio >= 1:
        return "EXCEEDED"
    if ratio >= Fraction(str(critical)):
        return "CRITICAL"
    if ratio >= Fraction(str(warning)):
        return "WARNING"
    return "OK"


# ------------------------------------------------------------ raw aggregates
def posted_spend_for_matter(matter_id):
    return sum(
        l["amount_cents"] for l in store.spend_lines.values()
        if l["matter_id"] == matter_id and l["source_status"] == "POSTED"
    )


def outstanding_accruals_for_matter(matter_id):
    return sum(
        a["amount_cents"] for a in store.accruals.values()
        if a["matter_id"] == matter_id and a["status"] == "OUTSTANDING"
    )


def period_spend(period):
    """POSTED lines whose posting_date falls inside the period's inclusive range."""
    return sum(
        l["amount_cents"] for l in store.spend_lines.values()
        if l["source_status"] == "POSTED"
        and period["start_date"] <= l["posting_date"] <= period["end_date"]
    )


def period_accruals(period_id):
    return sum(
        a["amount_cents"] for a in store.accruals.values()
        if a["fiscal_period_id"] == period_id and a["status"] == "OUTSTANDING"
    )


def budget_consumed(budget):
    total = 0
    for l in store.spend_lines.values():
        if l["source_status"] != "POSTED":
            continue
        if l["fiscal_period_id"] != budget["fiscal_period_id"]:
            continue
        m = store.matters.get(l["matter_id"])
        if m is None:
            continue
        if m["practice_area_id"] != budget["practice_area_id"]:
            continue
        if budget["matter_type_id"] is not None and m["matter_type_id"] != budget["matter_type_id"]:
            continue
        total += l["amount_cents"]
    return total


def matching_budgets(period_id, practice_area_id, matter_type_id):
    return [
        b for b in store.budgets.values()
        if b["fiscal_period_id"] == period_id
        and b["practice_area_id"] == practice_area_id
        and (b["matter_type_id"] is None or b["matter_type_id"] == matter_type_id)
    ]


# ------------------------------------------------------------ recomputations
def recompute_matter(matter):
    new_actual = posted_spend_for_matter(matter["id"])
    new_accrual = outstanding_accruals_for_matter(matter["id"])
    if new_actual != matter["actual_spend_cents"] or new_accrual != matter["accrual_outstanding_cents"]:
        matter["actual_spend_cents"] = new_actual
        matter["accrual_outstanding_cents"] = new_accrual
        touch(matter)


def recompute_period(period):
    new_spend = period_spend(period)
    new_accrual = period_accruals(period["id"])
    if new_spend != period["total_actual_spend_cents"] or new_accrual != period["total_accrual_cents"]:
        period["total_actual_spend_cents"] = new_spend
        period["total_accrual_cents"] = new_accrual
        touch(period)


def recompute_budget(budget):
    consumed = budget_consumed(budget)
    warning, critical = department_thresholds()
    posture = derive_posture(consumed, budget["allocated_cents"], warning, critical)
    if consumed != budget["consumed_cents"] or posture != budget["posture"]:
        budget["consumed_cents"] = consumed
        budget["posture"] = posture
        touch(budget)


def rederive_all_budget_postures():
    warning, critical = department_thresholds()
    for b in store.budgets.values():
        posture = derive_posture(b["consumed_cents"], b["allocated_cents"], warning, critical)
        if posture != b["posture"]:
            b["posture"] = posture
            touch(b)


# ------------------------------------------------------------- computed reads
def _pct(num, den):
    """Fraction -> *100 -> round half-up 2dp -> /100 (PRD section 2.9)."""
    if den == 0:
        return None
    v = (Decimal(num) / Decimal(den) * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(v / 100)


def counsel_utilization(c):
    alloc = 0
    for a in store.assignments.values():
        if a["counsel_id"] != c["id"] or a["status"] != "ACTIVE":
            continue
        m = store.matters.get(a["matter_id"])
        if m is not None and m["status"] in ("ACTIVE", "ON_HOLD"):
            alloc += a["allocated_hours"]
    cap = c["annual_capacity_hours"]
    return {
        "counsel_id": c["id"],
        "total_allocated_hours": alloc,
        "annual_capacity_hours": cap,
        "utilization_pct": _pct(alloc, cap),
        "over_capacity": alloc > cap,
    }


def matter_cost_model(matter):
    assignments = [a for a in store.assignments.values() if a["matter_id"] == matter["id"]]
    insource = 0
    total_hours = 0
    for a in assignments:
        c = store.counsel.get(a["counsel_id"])
        rate = c["loaded_hourly_cost_cents"] if c else 0
        insource += a["allocated_hours"] * rate
        total_hours += a["allocated_hours"]
    firm = store.firms.get(matter["primary_firm_id"]) if matter["primary_firm_id"] else None
    modeled = None if firm is None else total_hours * firm["blended_hourly_rate_cents"]
    if matter["status"] in ("ACTIVE", "ON_HOLD", "INTAKE"):
        outsource = matter["actual_spend_cents"] + matter["accrual_outstanding_cents"]
    else:  # CLOSED, REOPENED, ARCHIVED — final view ignores accruals
        outsource = matter["actual_spend_cents"]
    if modeled is None:
        savings = None
        decision = None
    else:
        savings = modeled - insource
        if savings > 0:
            decision = "INSOURCE_CHEAPER"
        elif savings < 0:
            decision = "OUTSOURCE_CHEAPER"
        else:
            decision = "BREAK_EVEN"
    return {
        "matter_id": matter["id"],
        "insource_cost_cents": insource,
        "outsource_cost_cents": outsource,
        "modeled_outsource_cost_cents": modeled,
        "savings_cents": savings,
        "decision": decision,
    }


def compute_dashboard_panel(period_id):
    matters = [m for m in store.matters.values() if m["fiscal_period_id"] == period_id]
    opened = [m for m in matters if m["status"] in ("ACTIVE", "ON_HOLD", "CLOSED", "REOPENED")]
    closed = [m for m in matters if m["status"] == "CLOSED"]
    total_opened = len(opened)
    total_closed = len(closed)
    cycles = [m["cycle_days"] for m in closed if m["cycle_days"] is not None]
    if cycles:
        mean_cycle = float(
            (Decimal(sum(cycles)) / Decimal(len(cycles))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        )
    else:
        mean_cycle = None
    period = store.fiscal_periods.get(period_id)
    total_spend = period["total_actual_spend_cents"] if period else 0
    total_accrual = period["total_accrual_cents"] if period else 0
    alloc = sum(b["allocated_cents"] for b in store.budgets.values() if b["fiscal_period_id"] == period_id)
    if alloc == 0:
        accuracy = None
    else:
        delta = abs(alloc - total_spend)
        accuracy = float(
            ((Decimal(1) - Decimal(delta) / Decimal(alloc)) * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) / 100
        )
    deflected = [
        m for m in matters
        if m["primary_firm_id"] is None and m["status"] in ("ACTIVE", "CLOSED")
    ]
    deflection = None if total_opened == 0 else _pct(len(deflected), total_opened)
    return {
        "total_matters_opened": total_opened,
        "total_matters_closed": total_closed,
        "mean_cycle_days": mean_cycle,
        "total_actual_spend_cents": total_spend,
        "total_accrual_outstanding_cents": total_accrual,
        "budget_accuracy_pct": accuracy,
        "deflection_rate_pct": deflection,
    }
