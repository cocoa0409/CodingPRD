"""Entity serializers (public wire shapes) and project cost rollups."""
from datetime import timedelta

import db

MIN_CURE_DAYS = 7


def rollup_labor_cents(project_id):
    return sum(e["total_cost_cents"] for e in db.labor_entries.values()
               if e["project_id"] == project_id and e["status"] in ("APPROVED", "INVOICED"))


def rollup_equipment_cents(project_id):
    return sum((l["equipment_charge_cents"] or 0) for l in db.lift_permits.values()
               if l["project_id"] == project_id and l["status"] == "EXECUTED")


def rollup_invoiced_cents(project_id):
    return sum(i["amount_cents"] for i in db.invoices.values()
               if i["project_id"] == project_id)


def project_json(p):
    pid = p["id"]
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "name": p["name"],
        "customer_name": p["customer_name"],
        "site_address": p["site_address"],
        "billing_mode": p["billing_mode"],
        "contract_amount_cents": p["contract_amount_cents"],
        "equipment_hourly_rate_cents": p["equipment_hourly_rate_cents"],
        "retainage_pct": p["retainage_pct"],
        "ot_basis": p["ot_basis"],
        "work_status": p["work_status"],
        "hold_status": p["hold_status"],
        "approved_rigging_plan_id": p["approved_rigging_plan_id"],
        "approved_rigging_plan_revision": p["approved_rigging_plan_revision"],
        "approved_labor_cents": rollup_labor_cents(pid),
        "approved_equipment_cents": rollup_equipment_cents(pid),
        "invoiced_cents": rollup_invoiced_cents(pid),
    }


def foundation_cured(s):
    """Evaluated continuously against the logical clock (PRD 3.2)."""
    return db.clock_now() >= s["_pour_dt"] + timedelta(days=MIN_CURE_DAYS)


def survey_json(s):
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
        "project_id": s["project_id"],
        "survey_date": s["survey_date"],
        "anchor_bolt_count": s["anchor_bolt_count"],
        "anchor_tolerance_mm": s["anchor_tolerance_mm"],
        "anchor_measured_max_deviation_mm": s["anchor_measured_max_deviation_mm"],
        "overhead_clearance_mm": s["overhead_clearance_mm"],
        "foundation_pour_date": s["foundation_pour_date"],
        "anchor_check_passed": s["anchor_check_passed"],
        "foundation_cured": foundation_cured(s),
        "status": s["status"],
        "reviewer_note": s["reviewer_note"],
    }


def safety_plan_json(sp):
    return {
        "id": sp["id"],
        "created_at": sp["created_at"],
        "updated_at": sp["updated_at"],
        "version": sp["version"],
        "project_id": sp["project_id"],
        "plan_document_ref": sp["plan_document_ref"],
        "loto_procedure_ref": sp["loto_procedure_ref"],
        "status": sp["status"],
    }


def lockout_json(w):
    return {
        "id": w["id"],
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
        "project_id": w["project_id"],
        "feeder_id": w["feeder_id"],
        "starts_at": w["starts_at"],
        "ends_at": w["ends_at"],
        "status": w["status"],
    }


def rigging_json(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "project_id": r["project_id"],
        "revision": r["revision"],
        "lift_weight_tons": r["lift_weight_tons"],
        "crane_model": r["crane_model"],
        "planned_crane_capacity_tons": r["planned_crane_capacity_tons"],
        "rigging_config": r["rigging_config"],
        "weight_check_passed": r["weight_check_passed"],
        "status": r["status"],
        "reviewer_note": r["reviewer_note"],
    }


def lift_json(l):
    return {
        "id": l["id"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
        "project_id": l["project_id"],
        "crane_ref": l["crane_ref"],
        "lift_starts_at": l["lift_starts_at"],
        "lift_ends_at": l["lift_ends_at"],
        "road_permit_required": l["road_permit_required"],
        "road_permit_number": l["road_permit_number"],
        "duration_hours": l["duration_hours"],
        "equipment_charge_cents": l["equipment_charge_cents"],
        "status": l["status"],
    }


def alignment_json(a):
    return {
        "id": a["id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
        "project_id": a["project_id"],
        "measurement_point": a["measurement_point"],
        "tolerance_class": a["tolerance_class"],
        "measured_offset_mils": a["measured_offset_mils"],
        "measured_angular_mils_per_in": a["measured_angular_mils_per_in"],
        "offset_passed": a["offset_passed"],
        "angular_passed": a["angular_passed"],
        "verdict": a["verdict"],
        "status": a["status"],
        "reviewer_note": a["reviewer_note"],
    }


def checklist_json(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "project_id": c["project_id"],
        "items": c["items"],
        "required_count": c["required_count"],
        "checked_required_count": c["checked_required_count"],
        "status": c["status"],
        "signed_off_by_user_id": c["signed_off_by_user_id"],
    }


def labor_json(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
        "project_id": e["project_id"],
        "worker_ref": e["worker_ref"],
        "classification": e["classification"],
        "work_date": e["work_date"],
        "hours_worked": e["hours_worked"],
        "shift": e["shift"],
        "regular_hours": e["regular_hours"],
        "overtime_hours": e["overtime_hours"],
        "base_rate_cents": e["base_rate_cents"],
        "total_cost_cents": e["total_cost_cents"],
        "status": e["status"],
        "submitted_by_user_id": e["submitted_by_user_id"],
        "approved_by_user_id": e["approved_by_user_id"],
        "rejection_reason": e["rejection_reason"],
    }


def invoice_json(i):
    """Invoices are append-only: id + created_at only, no updated_at/version."""
    return {
        "id": i["id"],
        "created_at": i["created_at"],
        "project_id": i["project_id"],
        "kind": i["kind"],
        "period_start": i["period_start"],
        "period_end": i["period_end"],
        "progress_pct": i["progress_pct"],
        "billing_mode_snapshot": i["billing_mode_snapshot"],
        "gross_cents": i["gross_cents"],
        "retainage_cents": i["retainage_cents"],
        "retainage_released_cents": i["retainage_released_cents"],
        "amount_cents": i["amount_cents"],
        "labor_entry_ids": i["labor_entry_ids"],
        "lift_permit_ids": i["lift_permit_ids"],
    }
