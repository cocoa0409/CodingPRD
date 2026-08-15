"""Serializers: entity dict -> public JSON shape (internal _keys stripped)."""
from db import now
from .core import age_months, warranty_active
from . import compliance as comp

CONDITION_FACTORS = {1: (60, 100), 2: (80, 100), 3: (100, 100), 4: (115, 100), 5: (130, 100)}


def property_view(p):
    return {
        "id": p["id"],
        "property_code": p["property_code"],
        "display_name": p["display_name"],
        "notice_lead_hours": p["notice_lead_hours"],
        "default_labor_rate_cents_per_hour": p["default_labor_rate_cents_per_hour"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def building_view(b):
    return {
        "id": b["id"],
        "property_id": b["property_id"],
        "building_label": b["building_label"],
        "floors": b["floors"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def unit_view(u):
    return {
        "id": u["id"],
        "building_id": u["building_id"],
        "unit_number": u["unit_number"],
        "occupancy_status": u["occupancy_status"],
        "created_at": u["created_at"],
        "updated_at": u["updated_at"],
        "version": u["version"],
    }


def asset_view(a):
    clock = now()
    inst = a["_installed_dt"]
    months = age_months(inst, clock)
    return {
        "id": a["id"],
        "unit_id": a["unit_id"],
        "component_type": a["component_type"],
        "installed_on": a["installed_on"],
        "warranty_months": a["warranty_months"],
        "expected_life_months": a["expected_life_months"],
        "replacement_cost_cents": a["replacement_cost_cents"],
        "condition_score": a["condition_score"],
        "age_months": months,
        "warranty_active": months < a["warranty_months"],
        "operational_status": a["operational_status"],
        "compliance_status": a["compliance_status"],
        "superseded_by_asset_id": a["superseded_by_asset_id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def template_view(t):
    return {
        "id": t["id"],
        "property_id": t["property_id"],
        "component_type": t["component_type"],
        "task_name": t["task_name"],
        "frequency_days": t["frequency_days"],
        "estimated_labor_minutes": t["estimated_labor_minutes"],
        "requires_evidence": t["requires_evidence"],
        "effective_from": t["effective_from"],
        "retired_at": t["retired_at"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def plan_view(p):
    agg = comp.plan_aggregates(p["id"])
    return {
        "id": p["id"],
        "property_id": p["property_id"],
        "plan_year": p["plan_year"],
        "budget_cents": p["budget_cents"],
        "planned_labor_hours": agg["planned_labor_hours"],
        "actual_labor_minutes": agg["actual_labor_minutes"],
        "committed_cents": agg["committed_cents"],
        "spent_cents": agg["spent_cents"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def batch_view(b):
    return {
        "id": b["id"],
        "property_id": b["property_id"],
        "batch_label": b["batch_label"],
        "window_start": b["window_start"],
        "window_end": b["window_end"],
        "status": b["status"],
        "notice_sent_at": b["notice_sent_at"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def visit_view(v):
    return {
        "id": v["id"],
        "batch_id": v["batch_id"],
        "unit_id": v["unit_id"],
        "template_id": v["template_id"],
        "asset_id": v["asset_id"],
        "plan_id": v["plan_id"],
        "scheduled_start": v["scheduled_start"],
        "technician_id": v["technician_id"],
        "actual_minutes": v["actual_minutes"],
        "condition_score_recorded": v["condition_score_recorded"],
        "visit_status": v["visit_status"],
        "visit_cost_cents": v["visit_cost_cents"],
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
    }


def evidence_view(e):
    return {
        "id": e["id"],
        "visit_id": e["visit_id"],
        "evidence_type": e["evidence_type"],
        "serial_or_lot": e["serial_or_lot"],
        "notes": e["notes"],
        "recorded_by": e["recorded_by"],
        "created_at": e["created_at"],
    }


def deficiency_view(d):
    return {
        "id": d["id"],
        "visit_id": d["visit_id"],
        "asset_id": d["asset_id"],
        "severity": d["severity"],
        "description": d["description"],
        "status": d["status"],
        "work_order_id": d["work_order_id"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def work_order_view(w):
    return {
        "id": w["id"],
        "property_id": w["property_id"],
        "deficiency_id": w["deficiency_id"],
        "plan_id": w["plan_id"],
        "asset_id": w["asset_id"],
        "estimated_cost_cents": w["estimated_cost_cents"],
        "actual_cost_cents": w["actual_cost_cents"],
        "assigned_technician_id": w["assigned_technician_id"],
        "replace_asset": w["replace_asset"],
        "status": w["status"],
        "revision_count": w["revision_count"],
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


def ledger_view(e):
    return {
        "id": e["id"],
        "plan_id": e["plan_id"],
        "entry_kind": e["entry_kind"],
        "amount_cents": e["amount_cents"],
        "source_visit_id": e["source_visit_id"],
        "source_work_order_id": e["source_work_order_id"],
        "memo": e["memo"],
        "created_at": e["created_at"],
    }


def forecast_view(s):
    return {
        "id": s["id"],
        "property_id": s["property_id"],
        "horizon_years": s["horizon_years"],
        "variant": s["variant"],
        "total_projected_cents": s["total_projected_cents"],
        "per_year_cents": s["per_year_cents"],
        "asset_count_projected": s["asset_count_projected"],
        "computed_at": s["computed_at"],
        "created_at": s["created_at"],
    }


def audit_view(a):
    return {
        "id": a["id"],
        "visit_id": a["visit_id"],
        "auditor_id": a["auditor_id"],
        "outcome": a["outcome"],
        "fail_reason": a["fail_reason"],
        "audited_at": a["audited_at"],
        "created_at": a["created_at"],
    }
