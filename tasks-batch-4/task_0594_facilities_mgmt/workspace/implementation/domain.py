"""Derived state, cascades and conserved quantities."""

from decimal import Decimal

import calc
from calc import D, round2
from store import db, ordered, touch


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def building_assets(building_id):
    return [a for a in db.assets.values() if a["building_id"] == building_id]


def building_work_orders(building_id):
    return [w for w in db.work_orders.values() if w["building_id"] == building_id]


def asset_pm_plans(asset_id):
    return [p for p in db.pm_plans.values() if p["asset_id"] == asset_id]


def building_pm_plans(building_id):
    asset_ids = {a["id"] for a in building_assets(building_id)}
    return [p for p in db.pm_plans.values() if p["asset_id"] in asset_ids]


def building_shifts(building_id):
    return [s for s in db.shifts.values() if s["building_id"] == building_id]


def wo_dispatches(work_order_id):
    return [d for d in db.dispatches.values() if d["work_order_id"] == work_order_id]


def vendor_dispatches(vendor_id):
    return [d for d in db.dispatches.values() if d["vendor_id"] == vendor_id]


# ---------------------------------------------------------------------------
# building_operating_posture (PRD 2.8) + the FROZEN cascade
# ---------------------------------------------------------------------------
def recompute_building(building):
    bid = building["id"]
    oos = sum(
        1
        for a in building_assets(bid)
        if a["criticality"] == "CRITICAL" and a["status"] == "OUT_OF_SERVICE"
    )
    open_p1 = sum(
        1
        for w in building_work_orders(bid)
        if w["priority"] == "P1" and w["status"] in calc.OPEN_WO_STATUSES
    )

    if oos >= calc.FROZEN_OOS_CRITICAL_THRESHOLD:
        posture = "FROZEN"
    elif open_p1 >= calc.RESTRICTED_OPEN_P1_THRESHOLD:
        posture = "RESTRICTED"
    else:
        posture = "OPEN"

    previous = building["operating_posture"]
    changed = (
        building["oos_critical_asset_count"] != oos
        or building["open_p1_work_order_count"] != open_p1
        or previous != posture
    )
    building["oos_critical_asset_count"] = oos
    building["open_p1_work_order_count"] = open_p1
    building["operating_posture"] = posture
    if changed:
        touch(building)

    if posture == "FROZEN" and previous != "FROZEN":
        _freeze_cascade(building)
    elif previous == "FROZEN" and posture != "FROZEN":
        _thaw_cascade(building)


def _freeze_cascade(building):
    # Every ACTIVE PMPlan of the building's assets -> SUSPENDED.
    for plan in building_pm_plans(building["id"]):
        if plan["status"] == "ACTIVE":
            plan["status"] = "SUSPENDED"
            touch(plan)
    # Every SCHEDULED SoftServiceShift of the building -> CANCELLED (no vendor strike).
    for shift in building_shifts(building["id"]):
        if shift["status"] == "SCHEDULED":
            shift["status"] = "CANCELLED"
            touch(shift)


def _thaw_cascade(building):
    # Leaving FROZEN reactivates SUSPENDED plans; cancelled shifts are NOT restored.
    for plan in building_pm_plans(building["id"]):
        if plan["status"] == "SUSPENDED":
            plan["status"] = "ACTIVE"
            touch(plan)


# ---------------------------------------------------------------------------
# vendor standing ladder + performance scores
# ---------------------------------------------------------------------------
def recompute_vendor_scores(vendor):
    completed = [
        d for d in vendor_dispatches(vendor["id"]) if d["status"] == "COMPLETED"
    ]
    completed.sort(key=lambda d: (d["completed_at"], d["created_at"], d["_seq"]))
    failed_qa = {w["id"]: w["failed_qa_count"] for w in db.work_orders.values()}

    rolling = completed[-calc.ROLLING_WINDOW_N:] if completed else []
    new_rolling = calc.performance_score(rolling, failed_qa)
    new_lifetime = calc.performance_score(completed, failed_qa)

    if (
        vendor["performance_score"] != new_rolling
        or vendor["lifetime_performance_score"] != new_lifetime
    ):
        vendor["performance_score"] = new_rolling
        vendor["lifetime_performance_score"] = new_lifetime
        touch(vendor)


def apply_strike(vendor):
    """One strike, then the standing ladder and the suspension cascade."""
    vendor["strike_count"] += 1
    previous = vendor["status"]
    if vendor["strike_count"] >= calc.SUSPENSION_STRIKES:
        vendor["status"] = "SUSPENDED"
    elif vendor["strike_count"] == calc.PROBATION_STRIKES:
        vendor["status"] = "PROBATION"
    touch(vendor)

    if vendor["status"] == "SUSPENDED" and previous != "SUSPENDED":
        _suspension_cascade(vendor)


def _suspension_cascade(vendor):
    for dispatch in ordered(vendor_dispatches(vendor["id"])):
        if dispatch["status"] != "OFFERED":
            continue
        dispatch["status"] = "CANCELLED"
        touch(dispatch)
        wo = db.work_orders.get(dispatch["work_order_id"])
        if wo is not None and wo["status"] == "DISPATCHED":
            wo["status"] = "NEW"
            wo["dispatched_at"] = None
            wo["sla_response_due_at"] = None
            wo["sla_resolve_due_at"] = None
            touch(wo)


# ---------------------------------------------------------------------------
# capital funding ledger (conserved quantity)
# ---------------------------------------------------------------------------
def recompute_project(project):
    funded = [
        w for w in db.work_orders.values() if w["funding_project_id"] == project["id"]
    ]
    committed = sum(
        (D(w["estimated_amount"]) for w in funded if w["status"] in calc.OPEN_WO_STATUSES),
        Decimal("0"),
    )
    spent = sum(
        (
            D(w["billable_amount"])
            for w in funded
            if w["status"] == "CLOSED" and w["billable_amount"] is not None
        ),
        Decimal("0"),
    )
    committed = round2(committed)
    spent = round2(spent)
    remaining = round2(D(project["budget_amount"]) - committed - spent)

    if (
        project["committed_amount"] != committed
        or project["spent_amount"] != spent
        or project["remaining_amount"] != remaining
    ):
        project["committed_amount"] = committed
        project["spent_amount"] = spent
        project["remaining_amount"] = remaining
        touch(project)


# ---------------------------------------------------------------------------
# space / lease occupancy shares (conserved quantity)
# ---------------------------------------------------------------------------
def space_allocated_share(space_id, at_instant):
    total = Decimal("0")
    for a in db.allocations.values():
        if a["space_id"] != space_id or a["status"] != "ACTIVE":
            continue
        if a["effective_from"] <= at_instant <= a["effective_to"]:
            total += D(a["share_pct"])
    return round2(total)


def space_derived(space):
    allocated = space_allocated_share(space["id"], db.clock)
    free = round2(Decimal("100") - allocated)
    status = "OCCUPIED" if allocated > 0 else "VACANT"
    return allocated, free, status


def refresh_space(space):
    allocated, free, status = space_derived(space)
    if (
        space["allocated_share_pct"] != allocated
        or space["free_share_pct"] != free
        or space["occupancy_status"] != status
    ):
        space["allocated_share_pct"] = allocated
        space["free_share_pct"] = free
        space["occupancy_status"] = status
        touch(space)


def lease_allocated_area(lease_id):
    total = Decimal("0")
    for a in db.allocations.values():
        if a["lease_id"] != lease_id or a["status"] != "ACTIVE":
            continue
        space = db.spaces.get(a["space_id"])
        if space is None:
            continue
        total += D(space["area_sqm"]) * D(a["share_pct"]) / Decimal("100")
    return round2(total)


def refresh_lease_area(lease):
    area = lease_allocated_area(lease["id"])
    if lease["allocated_area_sqm"] != area:
        lease["allocated_area_sqm"] = area
        touch(lease)
