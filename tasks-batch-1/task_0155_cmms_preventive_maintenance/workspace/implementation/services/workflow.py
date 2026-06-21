"""State transitions and cross-aggregate cascades (SCAFFOLD §1.2 / PRD §3).

All mutations here assume the caller holds db.LOCK so multi-step cascades are
atomic (PRD §2.5: no request leaves the data set partially reconciled).
"""
import db
from services import calc


# ---------------------------------------------------------------------------
# Work-order construction (PM-generated and corrective). PRD §3.4.
# ---------------------------------------------------------------------------
def build_work_order(asset, wo_type, severity, estimated_labor_hours,
                     pm_schedule=None):
    rec = db.new_record()
    rec.update({
        "asset_id": asset["id"],
        "pm_schedule_id": pm_schedule["id"] if pm_schedule else None,
        "assigned_technician_id": None,
        "wo_type": wo_type,
        "severity": severity,
        "execution_status": "DRAFT",
        "parts_status": "NONE",
        "estimated_labor_hours": estimated_labor_hours,
        "actual_cost_cents": 0,
        "warranty_claim_id": None,
        "opened_at": None,
        "closed_at": None,
        "scheduled_start": None,
        "scheduled_end": None,
    })
    # priority_score frozen at creation from the asset/schedule as observed now.
    rec["priority_score"] = calc.priority_score(asset, rec, pm_schedule)
    db.work_orders[rec["id"]] = rec
    return rec


def generate_due_for_schedule(schedule, asset):
    """Create a PREVENTIVE work order for a due schedule (PRD §3.3/§3.4).

    severity and estimated_labor_hours are copied from the schedule.
    Returns the new work order.
    """
    return build_work_order(
        asset=asset,
        wo_type="PREVENTIVE",
        severity=schedule["severity"],
        estimated_labor_hours=schedule["estimated_labor_hours"],
        pm_schedule=schedule,
    )


# ---------------------------------------------------------------------------
# Asset operational-status derivation (PRD §2.5/§3.8).
# ---------------------------------------------------------------------------
def asset_has_open_downtime(asset_id):
    return any(
        d["asset_id"] == asset_id and d["status"] == "OPEN"
        for d in db.downtime_events.values()
    )


def refresh_asset_status_for_downtime(asset, opening):
    """Move OPERATIONAL->DOWN on open, DOWN->OPERATIONAL when the last open
    downtime resolves. RETIRED is terminal and never auto-changed."""
    if asset["status"] == "RETIRED":
        return
    if opening:
        if asset["status"] == "OPERATIONAL":
            asset["status"] = "DOWN"
            db.touch(asset)
    else:
        if asset["status"] == "DOWN" and not asset_has_open_downtime(asset["id"]):
            asset["status"] = "OPERATIONAL"
            db.touch(asset)


# ---------------------------------------------------------------------------
# Close cascade (PRD §3.6).
# ---------------------------------------------------------------------------
def close_cascade(wo):
    asset = db.assets[wo["asset_id"]]

    # CASCADE 1: committed parts -> debit on_hand_qty, release, recompute.
    if wo["parts_status"] == "COMMITTED":
        affected_parts = set()
        for r in db.part_reservations.values():
            if r["work_order_id"] == wo["id"] and r["status"] == "COMMITTED":
                part = db.spare_parts[r["spare_part_id"]]
                part["on_hand_qty"] -= r["qty"]
                r["status"] = "RELEASED"
                db.touch(r)
                affected_parts.add(part["id"])
        for pid in affected_parts:
            calc.recompute_reserved_qty(db.spare_parts[pid])
        wo["parts_status"] = "RELEASED"

    # CASCADE 2: PREVENTIVE with a schedule -> rebase anchors and next-due.
    if wo["wo_type"] == "PREVENTIVE" and wo.get("pm_schedule_id"):
        sched = db.pm_schedules.get(wo["pm_schedule_id"])
        if sched is not None:
            sched["anchor_meter"] = asset["meter_reading"]
            sched["anchor_date"] = wo["closed_at"]
            calc.compute_next_due(sched)
            db.touch(sched)

    # CASCADE 3: budget charge if not warranty-covered. Recompute keeps the
    # site total consistent with the source rows (PRD §3.1).
    site = db.sites.get(asset["site_id"])
    if site is not None:
        calc.recompute_site_budget(site)


# ---------------------------------------------------------------------------
# Cancel cascade (PRD §3.5).
# ---------------------------------------------------------------------------
def cancel_cascade(wo):
    was_assigned = wo["execution_status"] == "ASSIGNED"
    tech_id = wo.get("assigned_technician_id")

    # Release every RESERVED reservation on this WO. No COMMITTED can exist
    # pre-IN_PROGRESS, so no stock is debited.
    affected_parts = set()
    any_released = False
    for r in db.part_reservations.values():
        if r["work_order_id"] == wo["id"] and r["status"] == "RESERVED":
            r["status"] = "RELEASED"
            db.touch(r)
            affected_parts.add(r["spare_part_id"])
            any_released = True
    for pid in affected_parts:
        calc.recompute_reserved_qty(db.spare_parts[pid])
    if any_released and _all_reservations_released(wo):
        wo["parts_status"] = "RELEASED"

    if was_assigned and tech_id:
        wo["assigned_technician_id"] = None
        tech = db.technicians.get(tech_id)
        if tech is not None:
            # recompute after clearing assignment (PRD §3.1)
            calc.recompute_backlog(tech)


def _all_reservations_released(wo):
    res = [r for r in db.part_reservations.values() if r["work_order_id"] == wo["id"]]
    return bool(res) and all(r["status"] == "RELEASED" for r in res)
