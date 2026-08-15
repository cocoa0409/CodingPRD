"""Entity -> JSON-serializable dict converters (PRD 2.4/2.5 field formats).

Datetimes render as ISO 8601 UTC with three fractional digits; Decimal
fields render as JSON numbers; internal `_`-prefixed keys never leak.
RuntimeReading omits updated_at and version entirely (PRD 2.4 exception).
"""
import db
import services
from db import fmt_dt
from helpers import num


def ser_station(s):
    return {
        "id": s["id"],
        "station_code": s["station_code"],
        "service_zone": s["service_zone"],
        "design_capacity_gpm": s["design_capacity_gpm"],
        "pump_count": s["pump_count"],
        "has_backup_generator": s["has_backup_generator"],
        "wet_well_volume_gal": s["wet_well_volume_gal"],
        "operational_posture": s["operational_posture"],
        "firm_capacity_available_gpm": s["firm_capacity_available_gpm"],
        "last_sso_occurred_at": fmt_dt(s["last_sso_occurred_at"]),
        "created_at": fmt_dt(s["created_at"]),
        "updated_at": fmt_dt(s["updated_at"]),
        "version": s["version"],
    }


def ser_pump(p):
    return {
        "id": p["id"],
        "station_id": p["station_id"],
        "position_index": p["position_index"],
        "rated_gpm": p["rated_gpm"],
        "status": p["status"],
        "cumulative_runtime_hours": num(p["cumulative_runtime_hours"]),
        "runtime_since_rebuild_hours": num(p["runtime_since_rebuild_hours"]),
        "last_alternation_at": fmt_dt(p["last_alternation_at"]),
        "rebuild_count": p["rebuild_count"],
        "created_at": fmt_dt(p["created_at"]),
        "updated_at": fmt_dt(p["updated_at"]),
        "version": p["version"],
    }


def ser_reading(r):
    return {
        "id": r["id"],
        "pump_id": r["pump_id"],
        "recorded_at": fmt_dt(r["recorded_at"]),
        "run_hours_delta": num(r["run_hours_delta"]),
        "starts_count": r["starts_count"],
        "source": r["source"],
        "created_at": fmt_dt(r["created_at"]),
    }


def ser_alarm_ticket(t):
    return {
        "id": t["id"],
        "station_id": t["station_id"],
        "alarm_class": t["alarm_class"],
        "alarm_code": t["alarm_code"],
        "raised_at": fmt_dt(t["raised_at"]),
        "status": t["status"],
        "assigned_operator_id": t["assigned_operator_id"],
        "acked_at": fmt_dt(t["acked_at"]),
        "dispatched_at": fmt_dt(t["dispatched_at"]),
        "cleared_at": fmt_dt(t["cleared_at"]),
        "response_minutes": t["response_minutes"],
        "is_sso_related": t["is_sso_related"],
        "created_at": fmt_dt(t["created_at"]),
        "updated_at": fmt_dt(t["updated_at"]),
        "version": t["version"],
    }


def ser_operator(o):
    return {
        "id": o["id"],
        "employee_code": o["employee_code"],
        "full_name": o["full_name"],
        "certifications": list(o["certifications"]),
        "home_zone": o["home_zone"],
        "is_active": o["is_active"],
        "active_ticket_count": services.operator_active_ticket_count(o["id"]),
        "consecutive_callouts_24h": services.operator_callouts_24h(o),
        "created_at": fmt_dt(o["created_at"]),
        "updated_at": fmt_dt(o["updated_at"]),
        "version": o["version"],
    }


def ser_rebuild(r):
    return {
        "id": r["id"],
        "pump_id": r["pump_id"],
        "work_order_ref": r["work_order_ref"],
        "started_at": fmt_dt(r["started_at"]),
        "completed_at": fmt_dt(r["completed_at"]),
        "status": r["status"],
        "cost_usd": num(r["cost_usd"]),
        "pre_rebuild_runtime_hours": num(r["pre_rebuild_runtime_hours"]),
        "created_at": fmt_dt(r["created_at"]),
        "updated_at": fmt_dt(r["updated_at"]),
        "version": r["version"],
    }


def ser_cleaning(c):
    return {
        "id": c["id"],
        "station_id": c["station_id"],
        "scheduled_for": fmt_dt(c["scheduled_for"]),
        "status": c["status"],
        "completed_at": fmt_dt(c["completed_at"]),
        "grease_depth_inches_pre": num(c["grease_depth_inches_pre"]),
        "grease_depth_inches_post": num(c["grease_depth_inches_post"]),
        "crew_lead_operator_id": c["crew_lead_operator_id"],
        "requires_confined_space_entry": c["requires_confined_space_entry"],
        "created_at": fmt_dt(c["created_at"]),
        "updated_at": fmt_dt(c["updated_at"]),
        "version": c["version"],
    }


def ser_generator_test(t):
    return {
        "id": t["id"],
        "station_id": t["station_id"],
        "scheduled_for": fmt_dt(t["scheduled_for"]),
        "test_kind": t["test_kind"],
        "status": t["status"],
        "started_at": fmt_dt(t["started_at"]),
        "duration_minutes": t["duration_minutes"],
        "load_percent": t["load_percent"],
        "outcome_notes": t["outcome_notes"],
        "created_at": fmt_dt(t["created_at"]),
        "updated_at": fmt_dt(t["updated_at"]),
        "version": t["version"],
    }


def ser_sso_event(e):
    return {
        "id": e["id"],
        "station_id": e["station_id"],
        "started_at": fmt_dt(e["started_at"]),
        "stopped_at": fmt_dt(e["stopped_at"]),
        "estimated_volume_gal": e["estimated_volume_gal"],
        "cause_code": e["cause_code"],
        "status": e["status"],
        "regulator_deadline_at": fmt_dt(e["regulator_deadline_at"]),
        "report_submitted_at": fmt_dt(e["report_submitted_at"]),
        "report_accepted_at": fmt_dt(e["report_accepted_at"]),
        "reached_surface_water": e["reached_surface_water"],
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def ser_permit(p):
    return {
        "id": p["id"],
        "station_id": p["station_id"],
        "work_description": p["work_description"],
        "authorized_entrant_id": p["authorized_entrant_id"],
        "attendant_operator_id": p["attendant_operator_id"],
        "entry_supervisor_id": p["entry_supervisor_id"],
        "status": p["status"],
        "issued_at": fmt_dt(p["issued_at"]),
        "valid_until": fmt_dt(p["valid_until"]),
        "closed_at": fmt_dt(p["closed_at"]),
        "gas_test_passed": p["gas_test_passed"],
        "created_at": fmt_dt(p["created_at"]),
        "updated_at": fmt_dt(p["updated_at"]),
        "version": p["version"],
    }


def ser_plan(plan):
    remaining = plan["budget_total_usd"] - plan["budget_allocated_usd"]
    if remaining < 0:
        remaining = remaining.__class__("0.00")
    return {
        "id": plan["id"],
        "plan_year": plan["plan_year"],
        "status": plan["status"],
        "budget_total_usd": num(plan["budget_total_usd"]),
        "budget_allocated_usd": num(plan["budget_allocated_usd"]),
        "budget_remaining_usd": num(remaining),
        "approved_at": fmt_dt(plan["approved_at"]),
        "created_at": fmt_dt(plan["created_at"]),
        "updated_at": fmt_dt(plan["updated_at"]),
        "version": plan["version"],
    }


def ser_project(p):
    return {
        "id": p["id"],
        "plan_id": p["plan_id"],
        "station_id": p["station_id"],
        "project_name": p["project_name"],
        "estimated_cost_usd": num(p["estimated_cost_usd"]),
        "risk_score": num(p["risk_score"]),
        "priority_rank": p["priority_rank"],
        "status": p["status"],
        "consequence_of_failure": p["consequence_of_failure"],
        "likelihood_of_failure": p["likelihood_of_failure"],
        "created_at": fmt_dt(p["created_at"]),
        "updated_at": fmt_dt(p["updated_at"]),
        "version": p["version"],
    }


def ser_spare(s):
    return {
        "id": s["id"],
        "asset_tag": s["asset_tag"],
        "rated_gpm": s["rated_gpm"],
        "compatible_zone": s["compatible_zone"],
        "status": s["status"],
        "reserved_for_station_id": s["reserved_for_station_id"],
        "deployed_at_station_id": s["deployed_at_station_id"],
        "created_at": fmt_dt(s["created_at"]),
        "updated_at": fmt_dt(s["updated_at"]),
        "version": s["version"],
    }
