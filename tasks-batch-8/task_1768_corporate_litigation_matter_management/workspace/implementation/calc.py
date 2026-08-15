"""Calculations, derived-field recomputation, cascades and system sweeps.

Implements SCAFFOLD calculations: exposure_tier_classification,
reserve_recognition, matter_accrual_rollup, budget_utilization,
matter_posture, vendor_capacity_rollup, work_order_cost,
settlement_authority_routing, portfolio_outcome_analytics.
"""
from datetime import timedelta

from db import store, touch

TIER1_MAX = 25000000
TIER2_MAX = 100000000
TIER3_MAX = 500000000

RESERVE_BASE = {
    "TIER_1": 500000,
    "TIER_2": 2500000,
    "TIER_3": 10000000,
    "TIER_4": 50000000,
}

UTILIZATION_RESTRICT_THRESHOLD = 90
UTILIZATION_FROZEN_THRESHOLD = 100

TIER_A_GB = 100
TIER_B_GB = 500
DISCOUNT_B_PCT = 80
DISCOUNT_C_PCT = 60

ROLE_RANK = {
    "LitigationCounsel": 0,
    "DeputyGeneralCounsel": 1,
    "GeneralCounsel": 2,
    "ChiefFinancialOfficer": 3,
    "BoardCommittee": 4,
}

CONSERVATIVE_TYPES = ("CLASS_ACTION", "REGULATORY")


# ---------------------------------------------------------------- exposures
def compute_tier(matter):
    low = matter.get("exposure_low_cents")
    high = matter.get("exposure_high_cents")
    prob = matter.get("probability_of_loss_pct")
    if low is None or high is None or prob is None:
        return None
    if matter.get("matter_type") in CONSERVATIVE_TYPES:
        expected_loss = (high * prob) // 100
    else:
        expected_loss = ((low + high) * prob) // 200
    if expected_loss < TIER1_MAX:
        return "TIER_1"
    if expected_loss < TIER2_MAX:
        return "TIER_2"
    if expected_loss < TIER3_MAX:
        return "TIER_3"
    return "TIER_4"


def approved_budget_of(matter_id):
    for b in store.budgets.values():
        if b["matter_id"] == matter_id and b["status"] == "APPROVED":
            return b
    return None


def rollup_accrued(matter_id):
    total = 0
    for a in store.accruals.values():
        if a["matter_id"] == matter_id and a["status"] == "POSTED":
            total += a["amount_cents"]
    for p in store.payments.values():
        if (
            p["matter_id"] == matter_id
            and p["status"] == "DISBURSED"
            and p["payment_status"] in ("SENT", "CONFIRMED")
        ):
            total += p["amount_cents"]
    return total


def compute_reserve(matter):
    if matter["status"] == "RESOLVED":
        staged = 0
        for p in store.payments.values():
            if p["matter_id"] == matter["id"] and p["status"] == "FINANCE_APPROVED":
                staged += p["amount_cents"]
        return max(0, staged - matter["accrued_to_date_cents"])
    tier = matter.get("exposure_tier")
    if tier is None:
        return None
    prob = matter.get("probability_of_loss_pct")
    if prob is None:
        return None
    scaled = (RESERVE_BASE[tier] * prob) // 100
    if matter["status"] == "REOPENED":
        return scaled
    return max(0, scaled - matter["accrued_to_date_cents"])


def compute_utilization_pct(accrued_to_date_cents, fy_budget_cents):
    return (accrued_to_date_cents * 100) // fy_budget_cents


def compute_posture(matter):
    for d in store.deadlines.values():
        if (
            d["matter_id"] == matter["id"]
            and d.get("is_jurisdictional")
            and d["status"] == "MISSED"
        ):
            return "FROZEN"
    if matter["status"] in ("RESOLVED", "CLOSED"):
        return "FROZEN"
    if matter["status"] in ("INTAKE", "ASSESSMENT", "SETTLEMENT_PENDING"):
        return "RESTRICTED"
    budget = approved_budget_of(matter["id"])
    if budget is not None:
        util = compute_utilization_pct(matter["accrued_to_date_cents"], budget["fy_budget_cents"])
        if util >= UTILIZATION_FROZEN_THRESHOLD:
            return "FROZEN"
        if util >= UTILIZATION_RESTRICT_THRESHOLD:
            return "RESTRICTED"
    return "OPEN"


def work_order_cost(volume_gb, rate_cents):
    """Marginal per-tier pricing; floor division per tier before summing."""
    a = min(volume_gb, TIER_A_GB)
    cost = a * rate_cents
    b = min(max(volume_gb - TIER_A_GB, 0), TIER_B_GB - TIER_A_GB)
    cost += (b * rate_cents * DISCOUNT_B_PCT) // 100
    c = max(volume_gb - TIER_B_GB, 0)
    cost += (c * rate_cents * DISCOUNT_C_PCT) // 100
    return cost


# ------------------------------------------------------------- recomputes
def recompute_matter_derived(matter, tier_changed=False):
    """Recompute tier/reserve/posture in place (no version bump; the caller's
    transition bump carries the derived changes)."""
    if tier_changed:
        matter["exposure_tier"] = compute_tier(matter)
    reserve = compute_reserve(matter)
    if reserve is not None or matter.get("reserve_amount_cents") is not None:
        matter["reserve_amount_cents"] = reserve
    matter["posture"] = compute_posture(matter)


def ledger_sync(matter):
    """Recompute accrued rollup, reserve, approved-budget utilization and
    posture after a ledger-affecting event. Bumps versions only on change."""
    changed = False
    accrued = rollup_accrued(matter["id"])
    if accrued != matter["accrued_to_date_cents"]:
        matter["accrued_to_date_cents"] = accrued
        changed = True
    reserve = compute_reserve(matter)
    if reserve != matter.get("reserve_amount_cents"):
        matter["reserve_amount_cents"] = reserve
        changed = True
    budget = approved_budget_of(matter["id"])
    if budget is not None:
        util = compute_utilization_pct(accrued, budget["fy_budget_cents"])
        if util != budget["utilization_pct"]:
            budget["utilization_pct"] = util
            touch(budget)
    posture = compute_posture(matter)
    if posture != matter["posture"]:
        matter["posture"] = posture
        changed = True
    if changed:
        touch(matter)


def vendor_recompute(vendor):
    committed = 0
    for wo in store.work_orders.values():
        if wo["vendor_id"] == vendor["id"] and wo["status"] in ("AUTHORIZED", "IN_PROGRESS"):
            committed += wo["estimated_gb"]
    if committed != vendor["committed_gb"]:
        vendor["committed_gb"] = committed
        touch(vendor)


def bubble_up_hold(hold):
    """ISSUED -> ACKNOWLEDGED when no custodian is pending and >=1 acknowledged."""
    if hold["status"] != "ISSUED":
        return
    pending = 0
    acknowledged = 0
    for c in store.custodians.values():
        if c["hold_id"] != hold["id"]:
            continue
        if c["status"] in ("NOTICED", "ESCALATED"):
            pending += 1
        elif c["status"] == "ACKNOWLEDGED":
            acknowledged += 1
    if pending == 0 and acknowledged >= 1:
        hold["status"] = "ACKNOWLEDGED"
        touch(hold)


def recompute_posture_bump(matter):
    """Posture recompute as a standalone side effect (bumps version on change)."""
    posture = compute_posture(matter)
    if posture != matter["posture"]:
        matter["posture"] = posture
        touch(matter)


# --------------------------------------------------------------- cascades
def cancel_work_order(wo):
    was_committed = wo["status"] in ("AUTHORIZED", "IN_PROGRESS")
    wo["status"] = "CANCELLED"
    touch(wo)
    if was_committed:
        vendor = store.vendors.get(wo["vendor_id"])
        if vendor is not None:
            vendor_recompute(vendor)


def release_hold(hold, reason, cascade_custodians=True):
    hold["status"] = "RELEASED"
    hold["released_at"] = store.clock
    hold["release_reason"] = reason
    touch(hold)
    if cascade_custodians:
        for c in store.custodians.values():
            if c["hold_id"] == hold["id"] and c["status"] in (
                "NOTICED",
                "ACKNOWLEDGED",
                "ESCALATED",
            ):
                c["status"] = "RELEASED"
                touch(c)


def matter_to_settlement_pending(matter):
    """System auto-transition ACTIVE/REOPENED -> SETTLEMENT_PENDING with the
    engagement-suspension cascade."""
    if matter["status"] not in ("ACTIVE", "REOPENED"):
        return
    for e in store.engagements.values():
        if e["matter_id"] == matter["id"] and e["status"] == "ACTIVE":
            e["status"] = "SUSPENDED"
            touch(e)
    matter["status"] = "SETTLEMENT_PENDING"
    matter["posture"] = compute_posture(matter)
    touch(matter)


def matter_resolution_cascade(matter, resolution_type, vacate_deadlines):
    """Pinned cascade order: work orders cancel first (releasing hold pins and
    vendor capacity), holds release second, custodians third, then (direct
    resolve only) SCHEDULED deadlines vacate."""
    for wo in sorted(store.work_orders.values(), key=lambda r: r["_seq"]):
        if wo["matter_id"] == matter["id"] and wo["status"] in (
            "DRAFT",
            "AUTHORIZED",
            "IN_PROGRESS",
        ):
            cancel_work_order(wo)
    for hold in sorted(store.holds.values(), key=lambda r: r["_seq"]):
        if hold["matter_id"] == matter["id"] and hold["status"] in (
            "DRAFT",
            "ISSUED",
            "ACKNOWLEDGED",
        ):
            release_hold(hold, "MATTER_RESOLVED", cascade_custodians=True)
    if vacate_deadlines:
        for d in sorted(store.deadlines.values(), key=lambda r: r["_seq"]):
            if d["matter_id"] == matter["id"] and d["status"] == "SCHEDULED":
                d["status"] = "VACATED"
                touch(d)
    matter["status"] = "RESOLVED"
    matter["resolution_type"] = resolution_type
    matter["resolved_at"] = store.clock
    matter["reserve_amount_cents"] = compute_reserve(matter)
    matter["posture"] = compute_posture(matter)
    touch(matter)


def active_policy_for_tier(tier):
    for p in store.policies.values():
        if p["tier"] == tier and p.get("is_active", True):
            return p
    return None


# ----------------------------------------------------------------- sweeps
def run_sweeps():
    """Clock-advance sweeps in pinned order: deadline miss, deadline expire,
    settlement expiry."""
    clock = store.clock
    for d in sorted(store.deadlines.values(), key=lambda r: r["_seq"]):
        if d["status"] == "SCHEDULED" and d["due_at"] < clock:
            d["status"] = "MISSED"
            touch(d)
            if d.get("is_jurisdictional"):
                matter = store.matters.get(d["matter_id"])
                if matter is not None:
                    recompute_posture_bump(matter)
    for d in sorted(store.deadlines.values(), key=lambda r: r["_seq"]):
        if d["status"] == "MISSED" and d["due_at"] + timedelta(days=30) < clock:
            d["status"] = "EXPIRED"
            touch(d)
    for s in sorted(store.settlements.values(), key=lambda r: r["_seq"]):
        if s["status"] in ("SUBMITTED", "UNDER_REVIEW", "COUNTERED") and s["expires_at"] < clock:
            s["status"] = "EXPIRED"
            s["approved_by_user_ids"] = []
            s["_approved_roles"] = []
            s["counter_amount_cents"] = None
            touch(s)
