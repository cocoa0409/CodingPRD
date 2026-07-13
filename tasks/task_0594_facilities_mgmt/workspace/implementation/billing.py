"""chargeback_statement_total (PRD 3.9) and building_kpi_dashboard."""

from decimal import Decimal

import calc
import domain
import serializers
from calc import D, round2, round3
from store import db, ordered, touch


def _relevant_allocations(lease, period_start, period_end):
    rows = [
        a
        for a in db.allocations.values()
        if a["lease_id"] == lease["id"]
        and a["status"] == "ACTIVE"
        and a["effective_from"] <= period_end
        and a["effective_to"] >= period_start
    ]
    return ordered(rows)


def _contained_readings(building_id, window_start, window_end):
    return [
        r
        for r in db.readings.values()
        if r["building_id"] == building_id
        and r["period_start"] >= window_start
        and r["period_end"] <= window_end
    ]


def collectable_work_orders(building_id, period_start, period_end):
    rows = [
        w
        for w in db.work_orders.values()
        if w["building_id"] == building_id
        and w["status"] == "CLOSED"
        and w["billing_status"] == "PENDING"
        and w["chargeable"] is True
        and w["closed_at"] is not None
        and period_start <= w["closed_at"] <= period_end
    ]
    return ordered(rows)


def compute_and_collect(statement):
    """Recompute the four money fields and collect the outstanding work orders.

    Rounding is applied PER LINE and the already-rounded lines are then summed.
    """
    lease = db.leases[statement["lease_id"]]
    building = db.buildings[lease["building_id"]]
    period_start = statement["period_start"]
    period_end = statement["period_end"]

    allocations = _relevant_allocations(lease, period_start, period_end)

    # (1) base rent -- round per line, then sum
    base_rent = Decimal("0")
    for alloc in allocations:
        space = db.spaces.get(alloc["space_id"])
        if space is None:
            continue
        line = (
            D(space["area_sqm"])
            * D(alloc["share_pct"])
            / Decimal("100")
            * D(lease["base_rate_per_sqm_month"])
        )
        base_rent += round2(line)

    # (2) utility share -- round per line, then sum
    readings = _contained_readings(building["id"], period_start, period_end)
    utility_total = sum((D(r["cost"]) for r in readings), Decimal("0"))
    gross_area = D(building["gross_area_sqm"])
    utility_share = Decimal("0")
    for alloc in allocations:
        space = db.spaces.get(alloc["space_id"])
        if space is None:
            continue
        allocated_area = D(space["area_sqm"]) * D(alloc["share_pct"]) / Decimal("100")
        line = utility_total * allocated_area / gross_area
        utility_share += round2(line)

    # (3) O&M share -- round per work order, then sum
    lease_area = domain.lease_allocated_area(lease["id"])
    lease_share = lease_area / gross_area
    collected = collectable_work_orders(building["id"], period_start, period_end)
    om_share = Decimal("0")
    for wo in collected:
        om_share += round2(D(wo["billable_amount"]) * lease_share)

    total = round2(base_rent + utility_share + om_share)

    statement["base_rent"] = round2(base_rent)
    statement["utility_share"] = round2(utility_share)
    statement["om_share"] = round2(om_share)
    statement["total_amount"] = total

    for wo in collected:
        wo["billing_status"] = "INVOICED"
        wo["statement_id"] = statement["id"]
        touch(wo)


def void_statement(statement):
    """DRAFT -> VOID: hand its work orders back so a superseding statement can collect."""
    statement["status"] = "VOID"
    touch(statement)
    for wo in db.work_orders.values():
        if wo["statement_id"] == statement["id"]:
            if wo["billing_status"] == "INVOICED":
                wo["billing_status"] = "PENDING"
            wo["statement_id"] = None
            touch(wo)


# ---------------------------------------------------------------------------
# KPI dashboard
# ---------------------------------------------------------------------------
def kpi(building, window_start, window_end):
    bid = building["id"]
    gross_area = D(building["gross_area_sqm"])

    readings = _contained_readings(bid, window_start, window_end)
    energy_kwh = sum(
        (D(r["consumption_kwh"]) for r in readings if r["meter_type"] in ("ELECTRIC", "GAS")),
        Decimal("0"),
    )
    total_cost = sum((D(r["cost"]) for r in readings), Decimal("0"))
    energy_intensity = round3(energy_kwh / gross_area)
    total_utility_cost = round2(total_cost)

    open_wo = sum(
        1
        for w in domain.building_work_orders(bid)
        if w["status"] in calc.OPEN_WO_STATUSES
    )

    wo_ids = {w["id"] for w in domain.building_work_orders(bid)}
    completed = [
        d
        for d in db.dispatches.values()
        if d["work_order_id"] in wo_ids and d["status"] == "COMPLETED"
    ]
    if not completed:
        sla_pct = round2(Decimal("100"))
    else:
        hits = sum(
            1
            for d in completed
            if d["sla_response_met"] is True and d["sla_resolve_met"] is True
        )
        sla_pct = round2(Decimal("100") * Decimal(hits) / Decimal(len(completed)))

    active_plans = [p for p in domain.building_pm_plans(bid) if p["status"] == "ACTIVE"]
    if not active_plans:
        pm_pct = round2(Decimal("100"))
    else:
        compliant = sum(
            1 for p in active_plans if serializers.plan_compliance(p) != "OVERDUE"
        )
        pm_pct = round2(
            Decimal("100") * Decimal(compliant) / Decimal(len(active_plans))
        )

    occupied_area = Decimal("0")
    for space in db.spaces.values():
        if space["building_id"] != bid:
            continue
        _allocated, _free, status = domain.space_derived(space)
        if status == "OCCUPIED":
            occupied_area += D(space["area_sqm"])
    occupancy_pct = round2(Decimal("100") * occupied_area / gross_area)

    return {
        "posture": building["operating_posture"],
        "energy_intensity_kwh_per_sqm": float(energy_intensity),
        "total_utility_cost": float(total_utility_cost),
        "open_work_order_count": open_wo,
        "sla_compliance_pct": float(sla_pct),
        "pm_compliance_pct": float(pm_pct),
        "occupancy_pct": float(occupancy_pct),
    }
