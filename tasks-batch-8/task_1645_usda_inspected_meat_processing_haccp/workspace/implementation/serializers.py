"""Serializers: convert internal records to API response dicts."""

from db import iso_format


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def _common_event(rec):
    """Append-only records: only id and created_at."""
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
    }


def plant_out(p):
    d = _common(p)
    d.update({
        "establishment_number": p["establishment_number"],
        "name": p["name"],
        "district_code": p["district_code"],
        "cooler_capacity_lbs": p["cooler_capacity_lbs"],
        "cooler_occupied_lbs": p["cooler_occupied_lbs"],
        "provisional_compliance_score": p["provisional_compliance_score"],
        "official_compliance_score": p["official_compliance_score"],
        "operating_status": p["operating_status"],
    })
    return d


def haccp_plan_out(p):
    d = _common(p)
    d.update({
        "plant_id": p["plant_id"],
        "process_type": p["process_type"],
        "status": p["status"],
        "revision_number": p["revision_number"],
        "rejection_reason": p["rejection_reason"],
        "approved_by": p["approved_by"],
        "submitted_at": p["submitted_at"],
        "approved_at": p["approved_at"],
    })
    return d


def ccp_out(c):
    d = _common(c)
    d.update({
        "haccp_plan_id": c["haccp_plan_id"],
        "ccp_code": c["ccp_code"],
        "hazard_category": c["hazard_category"],
        "description": c["description"],
        "critical_limit_min_f": c["critical_limit_min_f"],
        "critical_limit_max_f": c["critical_limit_max_f"],
        "monitoring_frequency_minutes": c["monitoring_frequency_minutes"],
        "deviation_severity": c["deviation_severity"],
    })
    return d


def observation_out(o):
    d = _common_event(o)
    d.update({
        "ccp_id": o["ccp_id"],
        "production_day_id": o["production_day_id"],
        "monitor_user_id": o["monitor_user_id"],
        "observed_value_f": o["observed_value_f"],
        "within_limit": o["within_limit"],
        "deviation_id": o["deviation_id"],
    })
    return d


def deviation_out(dv):
    d = _common(dv)
    d.update({
        "ccp_id": dv["ccp_id"],
        "production_day_id": dv["production_day_id"],
        "observation_id": dv["observation_id"],
        "severity": dv["severity"],
        "corrective_action_note": dv["corrective_action_note"],
        "action_logged_by": dv["action_logged_by"],
        "verified_by": dv["verified_by"],
        "status": dv["status"],
    })
    return d


def shift_out(s):
    d = _common(s)
    d.update({
        "plant_id": s["plant_id"],
        "inspector_user_id": s["inspector_user_id"],
        "scheduled_start": iso_format(s["scheduled_start"]),
        "scheduled_end": iso_format(s["scheduled_end"]),
        "status": s["status"],
        "checked_in_at": s["checked_in_at"],
        "checked_out_at": s["checked_out_at"],
    })
    return d


def day_out(dy):
    d = _common(dy)
    d.update({
        "plant_id": dy["plant_id"],
        "production_date": dy["production_date"],
        "process_type": dy["process_type"],
        "status": dy["status"],
        "posture": dy["posture"],
        "total_cut_weight_lbs": dy["total_cut_weight_lbs"],
        "total_cold_weight_lbs": dy["total_cold_weight_lbs"],
        "day_yield_pct": dy["day_yield_pct"],
    })
    return d


def lot_out(l):
    d = _common(l)
    d.update({
        "production_day_id": l["production_day_id"],
        "species": l["species"],
        "supplier_name": l["supplier_name"],
        "head_count": l["head_count"],
        "live_weight_lbs": l["live_weight_lbs"],
        "hot_carcass_weight_lbs": l["hot_carcass_weight_lbs"],
        "cold_carcass_weight_lbs": l["cold_carcass_weight_lbs"],
        "drip_loss_pct": l["drip_loss_pct"],
        "total_cut_weight_lbs": l["total_cut_weight_lbs"],
        "trim_waste_lbs": l["trim_waste_lbs"],
        "fabrication_yield_pct": l["fabrication_yield_pct"],
        "packer_yield_pct": l["packer_yield_pct"],
        "yield_grade": l["yield_grade"],
        "status": l["status"],
    })
    return d


def cut_record_out(cr):
    d = _common_event(cr)
    d.update({
        "lot_id": cr["lot_id"],
        "primal_type": cr["primal_type"],
        "weight_lbs": cr["weight_lbs"],
        "pct_of_cold_weight": cr["pct_of_cold_weight"],
    })
    return d


def sample_out(s):
    d = _common(s)
    d.update({
        "lot_id": s["lot_id"],
        "organism": s["organism"],
        "sample_type": s["sample_type"],
        "collected_by": s["collected_by"],
        "result": s["result"],
        "is_confirmation": s["is_confirmation"],
        "reported_at": s["reported_at"],
    })
    return d


def label_out(la):
    d = _common(la)
    d.update({
        "plant_id": la["plant_id"],
        "product_name": la["product_name"],
        "claims": la["claims"],
        "substantiation_doc_refs": la["substantiation_doc_refs"],
        "formulation_version": la["formulation_version"],
        "approved_formulation_version": la["approved_formulation_version"],
        "status": la["status"],
        "rejection_reason": la["rejection_reason"],
        "approved_by": la["approved_by"],
    })
    return d


def finished_lot_out(fl):
    d = _common(fl)
    d.update({
        "production_day_id": fl["production_day_id"],
        "source_lot_id": fl["source_lot_id"],
        "label_approval_id": fl["label_approval_id"],
        "units_produced": fl["units_produced"],
        "unit_weight_lbs": fl["unit_weight_lbs"],
        "total_weight_lbs": fl["total_weight_lbs"],
        "production_date": fl["production_date"],
        "shelf_life_days": fl["shelf_life_days"],
        "base_use_by_at": fl["base_use_by_at"],
        "penalty_hours": fl["penalty_hours"],
        "use_by_at": fl["use_by_at"],
        "temperature_logs": fl["temperature_logs"],
        "status": fl["status"],
        "shipped_at": fl["shipped_at"],
    })
    return d


def audit_out(a):
    d = _common_event(a)
    d.update({
        "plant_id": a["plant_id"],
        "production_day_id": a["production_day_id"],
        "auditor_user_id": a["auditor_user_id"],
        "stunning_efficacy_pct": a["stunning_efficacy_pct"],
        "slips_falls_pct": a["slips_falls_pct"],
        "vocalization_pct": a["vocalization_pct"],
        "outcome": a["outcome"],
        "noncompliance_record_id": a["noncompliance_record_id"],
    })
    return d


def nr_out(nr):
    d = _common(nr)
    d.update({
        "plant_id": nr["plant_id"],
        "production_day_id": nr["production_day_id"],
        "category": nr["category"],
        "regulation_cite": nr["regulation_cite"],
        "description": nr["description"],
        "severity": nr["severity"],
        "created_by": nr["created_by"],
        "status": nr["status"],
        "appeal_note": nr["appeal_note"],
        "resolved_by": nr["resolved_by"],
        "resolution_note": nr["resolution_note"],
    })
    return d


def recall_out(re):
    d = _common(re)
    d.update({
        "plant_id": re["plant_id"],
        "target_finished_lot_id": re["target_finished_lot_id"],
        "scope": re["scope"],
        "initiated_at": re["initiated_at"],
        "deadline_at": re["deadline_at"],
        "basis_weight_lbs": re["basis_weight_lbs"],
        "recovery_pct": re["recovery_pct"],
        "status": re["status"],
        "completed_at": re["completed_at"],
    })
    return d
