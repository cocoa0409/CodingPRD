"""Per-entity output shaping. Derived fields are computed at read time so
they can never drift from the underlying state."""

import db
from services import derive
from util import fmt_dt, fmt_ts, out_num


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": fmt_ts(rec["created_at"]),
        "updated_at": fmt_ts(rec["updated_at"]),
        "version": rec["version"],
    }


def customer(c):
    out = {
        "company_name": c["company_name"],
        "credit_limit_cents": c["credit_limit_cents"],
        "credit_hold": c["credit_hold"],
        "credit_used_cents": derive.credit_used_cents(c["id"]),
        "storage_free_days": c["storage_free_days"],
        "storage_daily_fee_cents": c["storage_daily_fee_cents"],
        "storage_fee_cap_cents": c["storage_fee_cap_cents"],
        "max_drops_per_day": c["max_drops_per_day"],
        "delivery_terms": c["delivery_terms"],
    }
    out.update(_common(c))
    return out


def engineer(e):
    out = {
        "full_name": e["full_name"],
        "license_number": e["license_number"],
        "license_state": e["license_state"],
        "license_expiry": fmt_dt(e["license_expiry"]),
        "seal_authority": e["seal_authority"],
    }
    out.update(_common(e))
    return out


def job(j):
    out = {
        "customer_id": j["customer_id"],
        "job_name": j["job_name"],
        "jobsite_address": j["jobsite_address"],
        "jobsite_state": j["jobsite_state"],
        "delivery_window_start": fmt_dt(j["delivery_window_start"]),
        "delivery_window_end": fmt_dt(j["delivery_window_end"]),
        "crane_required_at_jobsite": j["crane_required_at_jobsite"],
        "contracted_value_cents": j["contracted_value_cents"],
        "invoiced_cents": j["invoiced_cents"],
        "credit_issued_cents": derive.job_credit_issued_cents(j),
        "posture": derive.job_posture(j),
        "status": j["status"],
    }
    out.update(_common(j))
    return out


def design(d):
    out = {
        "job_id": d["job_id"],
        "component_ref": d["component_ref"],
        "revision_no": d["revision_no"],
        "supersedes_design_id": d["supersedes_design_id"],
        "component_type": d["component_type"],
        "span_ft": out_num(d["span_ft"]),
        "pitch_degrees": out_num(d["pitch_degrees"]),
        "design_load_psf": out_num(d["design_load_psf"]),
        "lumber_grade": d["lumber_grade"],
        "plating": d["plating"],
        "quantity_required": d["quantity_required"],
        "est_board_feet_per_unit": out_num(d["est_board_feet_per_unit"]),
        "status": d["status"],
        "submitted_by_engineer_id": d["submitted_by_engineer_id"],
        "sealed_by_engineer_id": d["sealed_by_engineer_id"],
        "sealed_at": fmt_dt(d["sealed_at"]),
    }
    out.update(_common(d))
    return out


def cut_list(cl):
    out = {
        "design_id": cl["design_id"],
        "job_id": cl["job_id"],
        "jig_setup_id": cl["jig_setup_id"],
        "rebuild_for_claim_id": cl["rebuild_for_claim_id"],
        "total_board_feet": out_num(cl["total_board_feet"]),
        "total_pieces": cl["total_pieces"],
        "total_plates": cl["total_plates"],
        "status": cl["status"],
    }
    out.update(_common(cl))
    return out


def cut_list_line(ln):
    out = {
        "cut_list_id": ln["cut_list_id"],
        "member_label": ln["member_label"],
        "dimension": ln["dimension"],
        "length_ft": out_num(ln["length_ft"]),
        "qty": ln["qty"],
        "line_board_feet": out_num(ln["line_board_feet"]),
        "waste_pct": out_num(ln["waste_pct"]),
        "required_board_feet": out_num(ln["required_board_feet"]),
        "status": ln["status"],
    }
    out.update(_common(ln))
    return out


def jig_setup(j):
    # JigSetup is the common-fields exception: id and created_at only.
    return {
        "id": j["id"],
        "setup_code": j["setup_code"],
        "component_type_supported": j["component_type_supported"],
        "plate_class": j["plate_class"],
        "changeover_minutes_from": j["changeover_minutes_from"],
        "created_at": fmt_ts(j["created_at"]),
    }


def inventory_lot(l):
    out = {
        "lot_kind": l["lot_kind"],
        "lumber_dimension": l["lumber_dimension"],
        "lumber_grade": l["lumber_grade"],
        "plate_class": l["plate_class"],
        "received_board_feet": out_num(l["received_board_feet"]),
        "received_plates": l["received_plates"],
        "unit_cost_cents_per_bf": l["unit_cost_cents_per_bf"],
        "unit_cost_cents_per_plate": l["unit_cost_cents_per_plate"],
        "available_bf": out_num(l["available_bf"]),
        "reserved_bf": out_num(l["reserved_bf"]),
        "consumed_bf": out_num(l["consumed_bf"]),
        "scrapped_bf": out_num(l["scrapped_bf"]),
        "available_plates": l["available_plates"],
        "reserved_plates": l["reserved_plates"],
        "consumed_plates": l["consumed_plates"],
        "scrapped_plates": l["scrapped_plates"],
        "status": l["status"],
    }
    out.update(_common(l))
    return out


def material_reservation(r):
    out = {
        "lot_id": r["lot_id"],
        "cut_list_line_id": r["cut_list_line_id"],
        "cut_list_id": r["cut_list_id"],
        "reserved_bf": out_num(r["reserved_bf"]),
        "reserved_plates": r["reserved_plates"],
        "status": r["status"],
    }
    out.update(_common(r))
    return out


def crane(c):
    out = {
        "crane_code": c["crane_code"],
        "capacity_lbs": c["capacity_lbs"],
        "crane_class": c["crane_class"],
        "hourly_rate_cents": c["hourly_rate_cents"],
        "status": c["status"],
    }
    out.update(_common(c))
    return out


def crane_slot(s):
    out = {
        "crane_id": s["crane_id"],
        "purpose": s["purpose"],
        "production_batch_id": s["production_batch_id"],
        "delivery_load_id": s["delivery_load_id"],
        "start_at": fmt_dt(s["start_at"]),
        "end_at": fmt_dt(s["end_at"]),
        "status": s["status"],
    }
    out.update(_common(s))
    return out


def production_batch(b):
    out = {
        "job_id": b["job_id"],
        "cut_list_id": b["cut_list_id"],
        "jig_setup_id": b["jig_setup_id"],
        "requested_completion_at": fmt_dt(b["requested_completion_at"]),
        "build_sequence_no": b["build_sequence_no"],
        "is_rebuild": b["is_rebuild"],
        "source_claim_id": b["source_claim_id"],
        "status": b["status"],
    }
    out.update(_common(b))
    return out


def delivery_load(l):
    out = {
        "job_id": l["job_id"],
        "scheduled_date": fmt_dt(l["scheduled_date"]),
        "planned_weight_est_lbs": out_num(l["planned_weight_est_lbs"]),
        "provisional_freight_cents": l["provisional_freight_cents"],
        "final_freight_cents": l["final_freight_cents"],
        "actual_total_weight_lbs": out_num(derive.load_actual_weight(l)),
        "crane_hours_actual": out_num(l["crane_hours_actual"]),
        "staged_at": fmt_dt(l["staged_at"]),
        "last_dispatched_at": fmt_dt(l["last_dispatched_at"]),
        "storage_fee_cents": l["storage_fee_cents"],
        "status": l["status"],
    }
    out.update(_common(l))
    return out


def bundle(b):
    out = {
        "delivery_load_id": b["delivery_load_id"],
        "production_batch_id": b["production_batch_id"],
        "stack_position": b["stack_position"],
        "weight_lbs": out_num(b["weight_lbs"]),
        "split_from_bundle_id": b["split_from_bundle_id"],
        "status": b["status"],
    }
    out.update(_common(b))
    return out


def damage_claim(c):
    out = {
        "delivery_load_id": c["delivery_load_id"],
        "bundle_id": c["bundle_id"],
        "filed_by_customer_id": c["filed_by_customer_id"],
        "claim_type": c["claim_type"],
        "description": c["description"],
        "claimed_amount_cents": c["claimed_amount_cents"],
        "damage_pct": out_num(c["damage_pct"]),
        "approved_cap_cents": c["approved_cap_cents"],
        "rebuild_material_cents": c["rebuild_material_cents"],
        "rebuild_labor_cents": c["rebuild_labor_cents"],
        "redelivery_cents": c["redelivery_cents"],
        "residual_credit_cents": c["residual_credit_cents"],
        "triaged_by": c["triaged_by"],
        "decided_by": c["decided_by"],
        "status": c["status"],
    }
    out.update(_common(c))
    return out


def design_change_order(co):
    out = {
        "job_id": co["job_id"],
        "supersedes_design_id": co["supersedes_design_id"],
        "new_design_id": co["new_design_id"],
        "reason": co["reason"],
        "requested_by": co["requested_by"],
        "impact_lines_scrapped": co["impact_lines_scrapped"],
        "impact_open_reservations": co["impact_open_reservations"],
        "status": co["status"],
    }
    out.update(_common(co))
    return out
