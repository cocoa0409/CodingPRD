"""Derived-state recomputation, roll-ups, scoring and cascades.

Roll-up fields are always recomputed from their sources rather than
incrementally patched (PRD section 2.9).  Recomputing a derived field never
advances a row's `version`; only a transition that advances the row does.
"""

from fractions import Fraction

import calc
import repo
from calc import (
    ACTIVE_BUDGET_STATUSES,
    CATEGORY_RANK,
    EXCLUDED_ITEM_STATUSES,
    NON_OVERDUE_ITEM_STATUSES,
    OPEN_DEFECT_STATUSES,
    OPEN_PLAN_STATUSES,
    add_days,
    frac,
    fmt_date,
    parse_date,
)
from db import clock_date, clock_iso, db
from repo import touch


# --------------------------------------------------------------------------
# Traversal helpers
# --------------------------------------------------------------------------
def ordered(values):
    return sorted(values, key=lambda r: (r["created_at"], r["_seq"]))


def plan_items(plan_id):
    return ordered([i for i in db.items.values() if i["plan_id"] == plan_id])


def included_items(plan_id):
    return [i for i in plan_items(plan_id) if i["status"] not in EXCLUDED_ITEM_STATUSES]


def plan_of_item(item):
    return db.plans[item["plan_id"]]


def property_of_plan(plan):
    return db.properties[plan["property_id"]]


def property_of_item(item):
    return property_of_plan(plan_of_item(item))


def plans_of_property(property_id):
    return ordered([p for p in db.plans.values() if p["property_id"] == property_id])


def properties_of_franchisee(franchisee_id):
    return ordered(
        [p for p in db.properties.values() if p["franchisee_id"] == franchisee_id]
    )


def budgets_of_plan(plan_id):
    return ordered([b for b in db.budgets.values() if b["plan_id"] == plan_id])


def active_budget(plan_id):
    for budget in budgets_of_plan(plan_id):
        if budget["status"] in ACTIVE_BUDGET_STATUSES:
            return budget
    return None


def draws_of_property(property_id):
    return ordered([d for d in db.draws.values() if d["property_id"] == property_id])


def draws_of_budget(budget_id):
    return ordered([d for d in db.draws.values() if d["capital_budget_id"] == budget_id])


def phases_of_plan(plan_id):
    return ordered([p for p in db.phases.values() if p["plan_id"] == plan_id])


def phases_of_property(property_id):
    plan_ids = {p["id"] for p in db.plans.values() if p["property_id"] == property_id}
    return ordered([p for p in db.phases.values() if p["plan_id"] in plan_ids])


def bookings_of_phase(phase_id):
    return ordered([b for b in db.bookings.values() if b["phase_id"] == phase_id])


def bookings_of_contractor(contractor_id):
    return ordered(
        [b for b in db.bookings.values() if b["contractor_id"] == contractor_id]
    )


def inspections_of_plan(plan_id):
    return ordered([i for i in db.inspections.values() if i["plan_id"] == plan_id])


def punch_items_of_inspection(inspection_id):
    return ordered(
        [p for p in db.punch_items.values() if p["inspection_id"] == inspection_id]
    )


def punch_items_of_item(item_id):
    return ordered([p for p in db.punch_items.values() if p["pip_item_id"] == item_id])


def disputes_of_plan(plan_id):
    return ordered([d for d in db.disputes.values() if d["plan_id"] == plan_id])


def disputes_of_item(item_id):
    return ordered([d for d in db.disputes.values() if d["item_id"] == item_id])


def notices_of_plan(plan_id):
    return ordered([n for n in db.notices.values() if n["plan_id"] == plan_id])


def notices_of_property(property_id):
    plan_ids = {p["id"] for p in db.plans.values() if p["property_id"] == property_id}
    return ordered([n for n in db.notices.values() if n["plan_id"] in plan_ids])


def extension_requests_of_item(item_id):
    return ordered(
        [e for e in db.extension_requests.values() if e["item_id"] == item_id]
    )


# --------------------------------------------------------------------------
# Ledger
# --------------------------------------------------------------------------
def append_ledger(plan_id, item_id, entry_type, delta_cents, memo):
    entry = repo.new_row(
        {
            "plan_id": plan_id,
            "item_id": item_id,
            "entry_type": entry_type,
            "delta_cents": int(delta_cents),
            "memo": memo,
            "recorded_at_clock": clock_iso(),
        },
        versioned=False,
    )
    return repo.insert("ledger", entry)


# --------------------------------------------------------------------------
# Item derived state
# --------------------------------------------------------------------------
def recompute_item_approved_cost(item):
    if not item.get("_cost_revised"):
        item["approved_cost_cents"] = item["brand_estimated_cost_cents"]


def recompute_item_deadline(item, plan):
    """deadline_date = category base from date(issued_at) + extension_days_granted."""
    issued_at = plan.get("issued_at")
    if not issued_at:
        item["deadline_date"] = None
        return
    issued_date = parse_date(issued_at[:10])
    base = calc.base_deadline(issued_date, item["category"])
    item["deadline_date"] = fmt_date(add_days(base, item["extension_days_granted"]))


def recompute_item_overdue(item):
    deadline = parse_date(item["deadline_date"]) if item["deadline_date"] else None
    item["is_overdue"] = bool(
        deadline is not None
        and clock_date() > deadline
        and item["status"] not in NON_OVERDUE_ITEM_STATUSES
    )


# --------------------------------------------------------------------------
# Plan roll-ups
# --------------------------------------------------------------------------
def recompute_plan_costs(plan):
    items = included_items(plan["id"])
    plan["scope_item_count"] = len(items)
    brand_total = 0
    owner_total = 0
    for item in items:
        brand_total += item["brand_estimated_cost_cents"]
        claimed = item["owner_claimed_cost_cents"]
        owner_total += (
            claimed if claimed is not None else item["brand_estimated_cost_cents"]
        )
    plan["brand_scoped_total_cents"] = brand_total
    plan["owner_claimed_total_cents"] = owner_total


def contingency_for_plan(plan):
    budget = active_budget(plan["id"])
    if budget is not None:
        return frac(budget["contingency_pct"])
    return calc.DEFAULT_CONTINGENCY_PCT


def recompute_plan_funding(plan):
    contingency = contingency_for_plan(plan)
    total = 0
    for item in included_items(plan["id"]):
        item["item_funding_cents"] = calc.item_funding_cents(
            item["approved_cost_cents"], item["category"], contingency
        )
        total += item["item_funding_cents"]
    plan["funding_requirement_cents"] = total

    budget = active_budget(plan["id"])
    if budget is None:
        plan["funding_gap_cents"] = 0
    else:
        plan["funding_gap_cents"] = max(0, total - budget["total_authorized_cents"])
        if budget["status"] == "LOCKED" and plan["funding_gap_cents"] > 0:
            budget["status"] = "UNDERFUNDED"
            touch(budget)


def recompute_plan_overdue(plan):
    plan["overdue_item_count"] = sum(
        1 for i in plan_items(plan["id"]) if i.get("is_overdue")
    )


def assign_priority_ranks(plan):
    """Contiguous 1..N ranks, recomputed from scratch.

    Ranks are only written once the plan has been issued.  Items outside the
    candidate set keep whatever rank they last held (PRD section 3.2).
    """
    if not plan.get("issued_at"):
        return
    candidates = [
        i for i in plan_items(plan["id"]) if i["status"] not in EXCLUDED_ITEM_STATUSES
    ]
    candidates.sort(
        key=lambda i: (
            CATEGORY_RANK[i["category"]],
            -i["approved_cost_cents"],
            i["created_at"],
            i["_seq"],
        )
    )
    for index, item in enumerate(candidates, start=1):
        item["priority_rank"] = index


def plan_deadline_horizon(plan):
    """The plan's back-of-house deadline date, or None while unissued."""
    if not plan.get("issued_at"):
        return None
    issued_date = parse_date(plan["issued_at"][:10])
    return calc.base_deadline(issued_date, "BACK_OF_HOUSE")


def reevaluate_plan_readiness(plan):
    """Compound readiness derived from the aggregate item states (bidirectional)."""
    items = included_items(plan["id"])
    ready = bool(items) and all(
        i["status"] in ("WORK_COMPLETE", "ACCEPTED") for i in items
    )
    if plan["status"] == "IN_EXECUTION" and ready:
        plan["status"] = "READY_FOR_COMPLETION_INSPECTION"
        touch(plan)
    elif plan["status"] == "READY_FOR_COMPLETION_INSPECTION" and not ready:
        plan["status"] = "IN_EXECUTION"
        touch(plan)


def recompute_inspection_punch_count(inspection):
    inspection["punch_open_count"] = sum(
        1
        for p in punch_items_of_inspection(inspection["id"])
        if p["status"] in OPEN_DEFECT_STATUSES
    )


# --------------------------------------------------------------------------
# compliance_risk_score
# --------------------------------------------------------------------------
def funding_gap_penalty(total_gap, total_requirement):
    if total_gap == 0:
        return 0
    ratio = (
        Fraction(0)
        if total_requirement == 0
        else Fraction(total_gap, total_requirement)
    )
    if ratio > calc.FUNDING_GAP_MINOR_RATIO:
        return calc.FUNDING_GAP_MAJOR_PENALTY
    return calc.FUNDING_GAP_MINOR_PENALTY


def risk_breakdown(prop):
    open_plans = [
        p for p in plans_of_property(prop["id"]) if p["status"] in OPEN_PLAN_STATUSES
    ]
    open_plan_ids = {p["id"] for p in open_plans}
    scored_items = [
        i
        for i in ordered(db.items.values())
        if i["plan_id"] in open_plan_ids and i["status"] not in EXCLUDED_ITEM_STATUSES
    ]
    scored_item_ids = {i["id"] for i in scored_items}
    open_defects = [
        d
        for d in ordered(db.punch_items.values())
        if d["pip_item_id"] in scored_item_ids and d["status"] in OPEN_DEFECT_STATUSES
    ]
    total_gap = sum(p["funding_gap_cents"] for p in open_plans)
    total_requirement = sum(p["funding_requirement_cents"] for p in open_plans)
    penalty = funding_gap_penalty(total_gap, total_requirement)
    horizon = add_days(clock_date(), calc.PROJECTION_HORIZON_DAYS)

    snapshot = {"LIFE_SAFETY": 0, "GUEST_FACING": 0, "BACK_OF_HOUSE": 0}
    projected = {"LIFE_SAFETY": 0, "GUEST_FACING": 0, "BACK_OF_HOUSE": 0}
    for item in scored_items:
        overdue = bool(item.get("is_overdue"))
        if overdue:
            snapshot[item["category"]] += 1
            projected[item["category"]] += 1
            continue
        deadline = parse_date(item["deadline_date"]) if item["deadline_date"] else None
        if (
            item["status"] in ("SCOPED", "DEFERRED_PENDING_EXTENSION")
            and deadline is not None
            and deadline <= horizon
        ):
            projected[item["category"]] += 1

    major = sum(1 for d in open_defects if d["severity"] == "MAJOR")
    critical = sum(1 for d in open_defects if d["severity"] == "CRITICAL")

    return {
        "open_plans": open_plans,
        "open_plan_count": len(open_plans),
        "snapshot_counts": snapshot,
        "projected_counts": projected,
        "open_major_defect_count": major,
        "open_critical_defect_count": critical,
        "funding_gap_cents": total_gap,
        "funding_requirement_cents": total_requirement,
        "funding_gap_penalty": penalty,
        "snapshot_score": _score(snapshot, penalty, major, critical),
        "projected_score": _score(projected, penalty, major, critical),
    }


def _score(counts, penalty, major, critical):
    raw = (
        100
        - min(
            calc.LS_OVERDUE_PENALTY_CAP,
            calc.LS_OVERDUE_PENALTY * counts["LIFE_SAFETY"],
        )
        - calc.GF_OVERDUE_PENALTY * counts["GUEST_FACING"]
        - calc.BOH_OVERDUE_PENALTY * counts["BACK_OF_HOUSE"]
        - penalty
        - calc.MAJOR_DEFECT_PENALTY * major
        - calc.CRITICAL_DEFECT_PENALTY * critical
    )
    return max(0, min(100, raw))


# --------------------------------------------------------------------------
# Posture / standing derivation
# --------------------------------------------------------------------------
def recompute_franchise_agreement_status(prop):
    if prop.get("_terminated"):
        prop["franchise_agreement_status"] = "TERMINATED"
        return
    for notice in notices_of_property(prop["id"]):
        if notice["status"] == "ISSUED":
            prop["franchise_agreement_status"] = "DEFAULT_NOTICED"
            return
    prop["franchise_agreement_status"] = "ACTIVE"


def derive_posture(prop, score):
    if prop["franchise_agreement_status"] == "TERMINATED":
        return "TERMINATED"
    for notice in notices_of_property(prop["id"]):
        if notice["status"] == "ISSUED":
            return "IN_DEFAULT"
    if score < calc.COMPLIANT_MIN_SCORE:
        return "AT_RISK"
    return "COMPLIANT"


def recompute_property(prop):
    prop["open_plan_count"] = sum(
        1 for p in plans_of_property(prop["id"]) if p["status"] in OPEN_PLAN_STATUSES
    )
    prop["rooms_out_of_service_current"] = sum(
        ph["rooms_out_of_service"]
        for ph in phases_of_property(prop["id"])
        if ph["status"] == "ACTIVE"
    )
    recompute_franchise_agreement_status(prop)
    breakdown = risk_breakdown(prop)
    prop["compliance_risk_score"] = breakdown["snapshot_score"]
    prop["compliance_posture"] = derive_posture(prop, breakdown["snapshot_score"])
    recompute_franchisee(prop["franchisee_id"])


def recompute_franchisee(franchisee_id):
    franchisee = db.franchisees.get(franchisee_id)
    if franchisee is None:
        return
    props = properties_of_franchisee(franchisee_id)
    franchisee["portfolio_property_count"] = len(props)
    postures = [p["compliance_posture"] for p in props]
    if any(p == "TERMINATED" for p in postures):
        franchisee["standing"] = "TERMINATED_PORTFOLIO"
    elif any(p == "IN_DEFAULT" for p in postures):
        franchisee["standing"] = "DEFAULT"
    elif any(p == "AT_RISK" for p in postures):
        franchisee["standing"] = "WATCH"
    else:
        franchisee["standing"] = "GOOD"


def recompute_property_of_plan(plan):
    recompute_property(property_of_plan(plan))


# --------------------------------------------------------------------------
# Reserve / budget availability
# --------------------------------------------------------------------------
def reserve_encumbered_cents(property_id, exclude_draw_id=None):
    total = 0
    for draw in draws_of_property(property_id):
        if draw["id"] == exclude_draw_id:
            continue
        if draw["status"] in calc.ENCUMBERING_DRAW_STATUSES:
            total += draw["amount_cents"]
    return total


def reserve_available_cents(prop, exclude_draw_id=None):
    encumbered = reserve_encumbered_cents(prop["id"], exclude_draw_id)
    return max(
        0,
        prop["reserve_balance_cents"] - prop["minimum_retention_cents"] - encumbered,
    )


def recompute_budget_committed(budget):
    """Roll-up recomputed from its sources: the budget's DISBURSED draws."""
    budget["committed_cents"] = sum(
        d["amount_cents"]
        for d in draws_of_budget(budget["id"])
        if d["status"] == "DISBURSED"
    )


def budget_headroom_cents(budget, exclude_draw_id=None):
    other = 0
    for draw in draws_of_budget(budget["id"]):
        if draw["id"] == exclude_draw_id:
            continue
        if draw["status"] in calc.ENCUMBERING_DRAW_STATUSES:
            other += draw["amount_cents"]
    return budget["total_authorized_cents"] - budget["committed_cents"] - other


# --------------------------------------------------------------------------
# Cascades
# --------------------------------------------------------------------------
def complete_plan_cascade(plan, inspection):
    """Completion sign-off cascade (PRD section 2.9 / 3.8)."""
    plan["status"] = "COMPLETED"
    touch(plan)

    for item in plan_items(plan["id"]):
        if item["status"] == "WORK_COMPLETE":
            item["status"] = "ACCEPTED"
            recompute_item_overdue(item)
            touch(item)

    prop = property_of_plan(plan)
    for phase in phases_of_plan(plan["id"]):
        if phase["status"] == "ACTIVE":
            phase["status"] = "CLOSED_OUT"
            touch(phase)
            for booking in bookings_of_phase(phase["id"]):
                if booking["status"] == "BOOKED":
                    booking["status"] = "COMPLETED"
                    touch(booking)

    budget = active_budget(plan["id"])
    if budget is not None:
        budget["status"] = "CLOSED"
        touch(budget)

    recompute_plan_costs(plan)
    recompute_plan_funding(plan)
    recompute_plan_overdue(plan)
    recompute_property(prop)

    append_ledger(
        plan["id"],
        None,
        "PLAN_COMPLETED",
        0,
        "completion inspection %s signed off" % inspection["id"],
    )


def terminate_plan_cascade(plan, notice):
    """Termination cascade — five ordered links (PRD section 2.9 / 3.9)."""
    # 1. the plan itself
    plan["status"] = "TERMINATED"
    touch(plan)

    prop = property_of_plan(plan)

    # 2. live children of the plan
    for item in plan_items(plan["id"]):
        if item["status"] in (
            "SCOPED",
            "DEFERRED_PENDING_EXTENSION",
            "IN_PROGRESS",
            "WORK_COMPLETE",
            "PUNCH_FAIL",
        ):
            item["status"] = "VOIDED"
            recompute_item_overdue(item)
            touch(item)

    cancelled_phases = []
    for phase in phases_of_plan(plan["id"]):
        if phase["status"] in ("PLANNED", "ACTIVE"):
            cancelled_phases.append(phase)
            phase["status"] = "CANCELLED"
            touch(phase)

    budget = active_budget(plan["id"])
    if budget is not None:
        budget["status"] = "CLOSED"
        touch(budget)

    # 3. bookings of the cancelled phases; released rooms
    for phase in cancelled_phases:
        for booking in bookings_of_phase(phase["id"]):
            if booking["status"] == "BOOKED":
                booking["status"] = "CANCELLED"
                touch(booking)

    # 4./5. property + franchisee
    prop["_terminated"] = True

    recompute_plan_costs(plan)
    recompute_plan_funding(plan)
    recompute_plan_overdue(plan)
    assign_priority_ranks(plan)
    recompute_property(prop)

    append_ledger(
        plan["id"],
        None,
        "PLAN_TERMINATED",
        0,
        "default notice %s escalated to termination" % notice["id"],
    )
