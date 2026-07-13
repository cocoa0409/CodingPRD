"""Resource serialisers.  Derived read-time figures are computed live off the clock."""

from decimal import Decimal

import calc
import domain
from calc import D
from envelope import iso
from store import db


def _num(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def _common(row):
    return {
        "id": row["id"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def building(row):
    out = _common(row)
    out.update(
        {
            "name": row["name"],
            "code": row["code"],
            "gross_area_sqm": _num(row["gross_area_sqm"]),
            "region": row["region"],
            "operating_posture": row["operating_posture"],
            "oos_critical_asset_count": row["oos_critical_asset_count"],
            "open_p1_work_order_count": row["open_p1_work_order_count"],
        }
    )
    return out


def space(row):
    allocated, free, status = domain.space_derived(row)
    out = _common(row)
    out.update(
        {
            "building_id": row["building_id"],
            "space_code": row["space_code"],
            "floor": row["floor"],
            "area_sqm": _num(row["area_sqm"]),
            "space_type": row["space_type"],
            "cost_center": row["cost_center"],
            "allocated_share_pct": float(allocated),
            "free_share_pct": float(free),
            "occupancy_status": status,
        }
    )
    return out


def asset(row):
    out = _common(row)
    out.update(
        {
            "building_id": row["building_id"],
            "asset_tag": row["asset_tag"],
            "category": row["category"],
            "criticality": row["criticality"],
            "status": row["status"],
            "runtime_hours": _num(row["runtime_hours"]),
            "failure_count": row["failure_count"],
            "condition_score": float(row["condition_score"]),
            "last_pm_at": iso(row["last_pm_at"]),
        }
    )
    return out


def pm_plan(row):
    out = _common(row)
    out.update(
        {
            "asset_id": row["asset_id"],
            "interval_days": row["interval_days"],
            "grace_days": row["grace_days"],
            "next_due_at": iso(row["next_due_at"]),
            "status": row["status"],
            "compliance_state": plan_compliance(row),
        }
    )
    return out


def plan_compliance(row):
    """RETIRED plans keep their last computed value; everything else is live."""
    if row["status"] == "RETIRED":
        return row["compliance_state"]
    state = calc.compliance_state(row["next_due_at"], row["grace_days"], db.clock)
    row["compliance_state"] = state
    return state


def vendor(row):
    out = _common(row)
    out.update(
        {
            "name": row["name"],
            "trade": row["trade"],
            "hourly_rate": _num(row["hourly_rate"]),
            "sla_response_minutes": row["sla_response_minutes"],
            "sla_resolve_minutes": row["sla_resolve_minutes"],
            "status": row["status"],
            "strike_count": row["strike_count"],
            "performance_score": float(row["performance_score"]),
            "lifetime_performance_score": float(row["lifetime_performance_score"]),
            "completed_dispatch_count": row["completed_dispatch_count"],
        }
    )
    return out


def work_order(row):
    out = _common(row)
    out.update(
        {
            "building_id": row["building_id"],
            "asset_id": row["asset_id"],
            "pm_plan_id": row["pm_plan_id"],
            "funding_project_id": row["funding_project_id"],
            "statement_id": row["statement_id"],
            "wo_type": row["wo_type"],
            "priority": row["priority"],
            "chargeable": row["chargeable"],
            "estimated_labor_hours": _num(row["estimated_labor_hours"]),
            "estimated_parts_cost": _num(row["estimated_parts_cost"]),
            "actual_labor_hours": _num(row["actual_labor_hours"]),
            "actual_parts_cost": _num(row["actual_parts_cost"]),
            "estimated_amount": _num(row["estimated_amount"]),
            "billable_amount": _num(row["billable_amount"]),
            "status": row["status"],
            "billing_status": row["billing_status"],
            "failed_qa_count": row["failed_qa_count"],
            "dispatched_at": iso(row["dispatched_at"]),
            "sla_response_due_at": iso(row["sla_response_due_at"]),
            "sla_resolve_due_at": iso(row["sla_resolve_due_at"]),
            "sla_state": row["sla_state"],
            "closed_at": iso(row["closed_at"]),
        }
    )
    return out


def dispatch(row):
    out = _common(row)
    out.update(
        {
            "work_order_id": row["work_order_id"],
            "vendor_id": row["vendor_id"],
            "status": row["status"],
            "dispatched_at": iso(row["dispatched_at"]),
            "accepted_at": iso(row["accepted_at"]),
            "completed_at": iso(row["completed_at"]),
            "response_minutes": row["response_minutes"],
            "resolve_minutes": row["resolve_minutes"],
            "sla_response_met": row["sla_response_met"],
            "sla_resolve_met": row["sla_resolve_met"],
            "penalty_pct": float(D(row["penalty_pct"])),
            "actual_labor_hours": _num(row["actual_labor_hours"]),
            "actual_parts_cost": _num(row["actual_parts_cost"]),
        }
    )
    return out


def shift(row):
    out = _common(row)
    out.update(
        {
            "building_id": row["building_id"],
            "vendor_id": row["vendor_id"],
            "zone_space_id": row["zone_space_id"],
            "service_type": row["service_type"],
            "start_at": iso(row["start_at"]),
            "end_at": iso(row["end_at"]),
            "planned_headcount": row["planned_headcount"],
            "actual_headcount": row["actual_headcount"],
            "status": row["status"],
        }
    )
    return out


def utility_reading(row):
    # Append-only: no updated_at, no version (PRD 2.4).
    return {
        "id": row["id"],
        "created_at": iso(row["created_at"]),
        "building_id": row["building_id"],
        "meter_type": row["meter_type"],
        "period_start": iso(row["period_start"]),
        "period_end": iso(row["period_end"]),
        "consumption_kwh": _num(row["consumption_kwh"]),
        "cost": _num(row["cost"]),
    }


def lease(row):
    out = _common(row)
    out.update(
        {
            "building_id": row["building_id"],
            "tenant_name": row["tenant_name"],
            "base_rate_per_sqm_month": _num(row["base_rate_per_sqm_month"]),
            "start_date": iso(row["start_date"]),
            "end_date": iso(row["end_date"]),
            "status": row["status"],
            "allocated_area_sqm": float(domain.lease_allocated_area(row["id"])),
        }
    )
    return out


def allocation(row):
    out = _common(row)
    out.update(
        {
            "lease_id": row["lease_id"],
            "space_id": row["space_id"],
            "share_pct": _num(row["share_pct"]),
            "effective_from": iso(row["effective_from"]),
            "effective_to": iso(row["effective_to"]),
            "status": row["status"],
        }
    )
    return out


def statement(row):
    out = _common(row)
    out.update(
        {
            "lease_id": row["lease_id"],
            "period_start": iso(row["period_start"]),
            "period_end": iso(row["period_end"]),
            "base_rent": float(D(row["base_rent"])),
            "utility_share": float(D(row["utility_share"])),
            "om_share": float(D(row["om_share"])),
            "total_amount": float(D(row["total_amount"])),
            "status": row["status"],
            "dispute_reason": row["dispute_reason"],
            "issued_at": iso(row["issued_at"]),
            "settled_at": iso(row["settled_at"]),
        }
    )
    return out


def project(row):
    out = _common(row)
    out.update(
        {
            "building_id": row["building_id"],
            "title": row["title"],
            "base_cost": _num(row["base_cost"]),
            "contingency_pct": float(D(row["contingency_pct"])),
            "contingency_amount": float(D(row["contingency_amount"])),
            "budget_amount": float(D(row["budget_amount"])),
            "committed_amount": float(D(row["committed_amount"])),
            "spent_amount": float(D(row["spent_amount"])),
            "remaining_amount": float(D(row["remaining_amount"])),
            "status": row["status"],
            "proposed_by_user_id": row["proposed_by_user_id"],
            "approved_by_user_id": row["approved_by_user_id"],
        }
    )
    return out
