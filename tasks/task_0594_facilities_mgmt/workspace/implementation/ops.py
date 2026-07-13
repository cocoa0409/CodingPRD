"""The operational epoch (PRD 3.8): six sweeps, in a fixed order."""

from decimal import Decimal

import calc
import domain
import serializers
from calc import D, round2
from store import base_fields, db, ordered, touch


def _create_preventive_work_order(building, plan):
    reference = db.clock
    row = base_fields()
    row.update(
        {
            "building_id": building["id"],
            "asset_id": plan["asset_id"],
            "pm_plan_id": plan["id"],
            "funding_project_id": None,
            "statement_id": None,
            "wo_type": "PREVENTIVE",
            "priority": "P2",
            "chargeable": True,
            "estimated_labor_hours": calc.PM_DEFAULT_HOURS,
            "estimated_parts_cost": calc.PM_DEFAULT_PARTS,
            "actual_labor_hours": None,
            "actual_parts_cost": None,
            "estimated_amount": calc.provisional_estimate(
                calc.PM_DEFAULT_HOURS,
                calc.PM_DEFAULT_PARTS,
                calc.STANDARD_LABOR_RATE,
                "P2",
                reference,
            ),
            "billable_amount": None,
            "status": "NEW",
            "billing_status": "PENDING",
            "failed_qa_count": 0,
            "dispatched_at": None,
            "sla_response_due_at": None,
            "sla_resolve_due_at": None,
            "sla_state": "WITHIN",
            "closed_at": None,
        }
    )
    db.work_orders[row["id"]] = row
    return row


def run(building):
    clock = db.clock
    bid = building["id"]

    created_work_order_ids = []
    in_progress_shift_ids = []
    missed_shift_ids = []
    retired_asset_ids = []
    expired_lease_ids = []
    closed_project_ids = []

    # --- 1. preventive-maintenance promotion -------------------------------
    blocked_plan_ids = {
        w["pm_plan_id"]
        for w in db.work_orders.values()
        if w["pm_plan_id"] and w["status"] not in ("CLOSED", "CANCELLED")
    }
    candidates = []
    for plan in domain.building_pm_plans(bid):
        if plan["status"] != "ACTIVE":
            continue
        if serializers.plan_compliance(plan) != "OVERDUE":
            continue
        if plan["id"] in blocked_plan_ids:
            continue
        candidates.append(plan)
    candidates.sort(key=lambda p: (p["next_due_at"], p["created_at"], p["_seq"]))
    for plan in candidates:
        wo = _create_preventive_work_order(building, plan)
        created_work_order_ids.append(wo["id"])

    # --- 2. shift sweep ----------------------------------------------------
    for shift in ordered(domain.building_shifts(bid)):
        if shift["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        if shift["end_at"] <= clock:
            shift["status"] = "MISSED"
            touch(shift)
            missed_shift_ids.append(shift["id"])
            vendor = db.vendors.get(shift["vendor_id"])
            if vendor is not None:
                domain.apply_strike(vendor)
        elif shift["status"] == "SCHEDULED" and shift["start_at"] <= clock:
            shift["status"] = "IN_PROGRESS"
            touch(shift)
            in_progress_shift_ids.append(shift["id"])

    # --- 3. asset retirement ----------------------------------------------
    for asset in ordered(domain.building_assets(bid)):
        if asset["status"] != "OUT_OF_SERVICE":
            continue
        if D(asset["condition_score"]) >= calc.RETIREMENT_SCORE_THRESHOLD:
            continue
        asset["status"] = "RETIRED"
        touch(asset)
        retired_asset_ids.append(asset["id"])
        for plan in domain.asset_pm_plans(asset["id"]):
            if plan["status"] in ("ACTIVE", "SUSPENDED"):
                plan["status"] = "RETIRED"
                touch(plan)

    # --- 4. lease expiry ---------------------------------------------------
    leases = [l for l in db.leases.values() if l["building_id"] == bid]
    for lease in ordered(leases):
        if lease["status"] != "ACTIVE":
            continue
        if not clock > lease["end_date"]:
            continue
        lease["status"] = "EXPIRED"
        touch(lease)
        expired_lease_ids.append(lease["id"])
        touched_spaces = set()
        for alloc in ordered(
            [a for a in db.allocations.values() if a["lease_id"] == lease["id"]]
        ):
            if alloc["status"] != "ACTIVE":
                continue
            alloc["status"] = "RELEASED"
            touch(alloc)
            touched_spaces.add(alloc["space_id"])
        for space_id in touched_spaces:
            space = db.spaces.get(space_id)
            if space is not None:
                domain.refresh_space(space)
        domain.refresh_lease_area(lease)

    # --- 5. capital-project closure ---------------------------------------
    projects = [p for p in db.projects.values() if p["building_id"] == bid]
    for project in ordered(projects):
        if project["status"] != "IN_FLIGHT":
            continue
        domain.recompute_project(project)
        if round2(D(project["committed_amount"])) != Decimal("0.00"):
            continue
        funded_closed = any(
            w["funding_project_id"] == project["id"] and w["status"] == "CLOSED"
            for w in db.work_orders.values()
        )
        if not funded_closed:
            continue
        project["status"] = "CLOSED"
        touch(project)
        closed_project_ids.append(project["id"])

    # --- 6. posture recompute ---------------------------------------------
    domain.recompute_building(building)

    return {
        "posture": building["operating_posture"],
        "created_work_order_ids": created_work_order_ids,
        "in_progress_shift_ids": in_progress_shift_ids,
        "missed_shift_ids": missed_shift_ids,
        "retired_asset_ids": retired_asset_ids,
        "expired_lease_ids": expired_lease_ids,
        "closed_project_ids": closed_project_ids,
    }
