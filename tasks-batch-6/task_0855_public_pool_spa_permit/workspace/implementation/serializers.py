"""Resource serialisation.  Every datetime goes through the one shared renderer."""

from clock import render_date, render_datetime
import domain
from store import DB


def _common(rec, versioned=True):
    out = {"id": rec["id"], "created_at": render_datetime(rec["created_at"])}
    if versioned:
        out["updated_at"] = render_datetime(rec["updated_at"])
        out["version"] = rec["version"]
    return out


def operator_json(rec):
    out = {
        "legal_name": rec["legal_name"],
        "contact_email": rec["contact_email"],
        "phone": rec["phone"],
        "fee_balance_cents": domain.fee_balance_cents(rec["id"]),
    }
    out.update(_common(rec))
    return out


def facility_json(rec):
    posture, reason = domain.operating_posture(rec)
    out = {
        "operator_id": rec["operator_id"],
        "name": rec["name"],
        "facility_class": rec["facility_class"],
        "water_type": domain.water_type_of(rec),
        "surface_area_sqft": rec["surface_area_sqft"],
        "water_volume_gallons": rec["water_volume_gallons"],
        "max_depth_feet": rec["max_depth_feet"],
        "features": list(rec["features"]),
        "drain_count": rec["drain_count"],
        "is_seasonal": rec["is_seasonal"],
        "season_start_date": render_date(rec["season_start_date"]),
        "season_end_date": render_date(rec["season_end_date"]),
        "requires_plan_review": rec["requires_plan_review"],
        "max_bather_load": domain.max_bather_load_of(rec),
        "lifeguard_required": domain.lifeguard_required_of(rec),
        "required_signage_types": domain.required_signage_types_of(rec),
        "vgb_compliance_status": domain.vgb_compliance_status(rec),
        "open_demerit_points": domain.open_demerit_points(rec["id"]),
        "operating_posture": posture,
        "posture_reason": reason,
        "active_permit_id": domain.active_permit_id(rec["id"]),
    }
    out.update(_common(rec))
    return out


def plan_review_json(rec):
    out = {
        "facility_id": rec["facility_id"],
        "supersedes_plan_review_id": rec["supersedes_plan_review_id"],
        "project_type": rec["project_type"],
        "drawing_reference": rec["drawing_reference"],
        "revision_round": rec["revision_round"],
        "status": rec["status"],
        "submitted_on": render_date(rec["submitted_on"]),
        "reviewer_user_id": rec["reviewer_user_id"],
        "decided_at": render_datetime(rec["decided_at"]),
        "decided_by_user_id": rec["decided_by_user_id"],
        "correction_notes": rec["correction_notes"],
    }
    out.update(_common(rec))
    return out


def permit_json(rec):
    out = {
        "facility_id": rec["facility_id"],
        "plan_review_id": rec["plan_review_id"],
        "permit_type": rec["permit_type"],
        "term_start_date": render_date(rec["term_start_date"]),
        "term_end_date": render_date(rec["term_end_date"]),
        "term_days": rec["term_days"],
        "applied_on": render_date(rec["applied_on"]),
        "is_late_application": rec["is_late_application"],
        "assessed_fee_cents": rec["assessed_fee_cents"],
        "fee_variant": rec["fee_variant"],
        "classification_at_issue": rec["classification_at_issue"],
        "status": rec["status"],
        "issued_at": render_datetime(rec["issued_at"]),
        "issued_by_user_id": rec["issued_by_user_id"],
        "suspension_reason": rec["suspension_reason"],
        "refunded": rec["refunded"],
    }
    out.update(_common(rec))
    return out


def inspection_json(rec):
    out = {
        "facility_id": rec["facility_id"],
        "prior_inspection_id": rec["prior_inspection_id"],
        "inspection_type": rec["inspection_type"],
        "inspector_user_id": rec["inspector_user_id"],
        "scheduled_start_at": render_datetime(rec["scheduled_start_at"]),
        "scheduled_end_at": render_datetime(rec["scheduled_end_at"]),
        "workflow_status": rec["workflow_status"],
        "enforcement_status": rec["enforcement_status"],
        "started_at": render_datetime(rec["started_at"]),
        "submitted_at": render_datetime(rec["submitted_at"]),
        "finalized_at": render_datetime(rec["finalized_at"]),
        "critical_demerits": rec["critical_demerits"],
        "noncritical_demerits": rec["noncritical_demerits"],
        "score": rec["score"],
        "result": rec["result"],
        "reinspection_due_on": render_date(rec["reinspection_due_on"]),
        "voided_at": render_datetime(rec["voided_at"]),
    }
    out.update(_common(rec))
    return out


def violation_json(rec):
    out = {
        "inspection_id": rec["inspection_id"],
        "code": rec["code"],
        "severity": rec["severity"],
        "description": rec["description"],
        "corrected_on_site": rec["corrected_on_site"],
        "points_assessed": rec["points_assessed"],
        "status": rec["status"],
        "corrected_at": render_datetime(rec["corrected_at"]),
        "verified_at": render_datetime(rec["verified_at"]),
        "rejection_count": rec["rejection_count"],
    }
    out.update(_common(rec))
    return out


def water_reading_json(rec):
    out = {
        "facility_id": rec["facility_id"],
        "sampled_at": render_datetime(rec["sampled_at"]),
        "source": rec["source"],
        "free_chlorine_ppm": rec["free_chlorine_ppm"],
        "combined_chloramine_ppm": rec["combined_chloramine_ppm"],
        "ph": rec["ph"],
        "cyanuric_acid_ppm": rec["cyanuric_acid_ppm"],
        "water_temp_f": rec["water_temp_f"],
        "compliance_status": rec["compliance_status"],
        "out_of_range_parameters": list(rec["out_of_range_parameters"]),
        "triggered_closure_order_id": rec["triggered_closure_order_id"],
    }
    out.update(_common(rec, versioned=False))
    return out


def closure_order_json(rec):
    out = {
        "facility_id": rec["facility_id"],
        "triggering_reading_id": rec["triggering_reading_id"],
        "closure_reason": rec["closure_reason"],
        "note": rec["note"],
        "ordered_by_user_id": rec["ordered_by_user_id"],
        "ordered_by_role": rec["ordered_by_role"],
        "ordered_at": render_datetime(rec["ordered_at"]),
        "status": rec["status"],
        "remediation_variant": rec["remediation_variant"],
        "required_remediation_minutes": rec["required_remediation_minutes"],
        "earliest_reopen_at": render_datetime(rec["earliest_reopen_at"]),
        "treatment_free_chlorine_ppm": rec["treatment_free_chlorine_ppm"],
        "treatment_ph": rec["treatment_ph"],
        "verification_reading_id": rec["verification_reading_id"],
        "reopen_requested_at": render_datetime(rec["reopen_requested_at"]),
        "reopen_decided_at": render_datetime(rec["reopen_decided_at"]),
        "reopen_decided_by_user_id": rec["reopen_decided_by_user_id"],
        "reopen_denial_reason": rec["reopen_denial_reason"],
        "denial_count": rec["denial_count"],
        "cleared_at": render_datetime(rec["cleared_at"]),
    }
    out.update(_common(rec))
    return out


def staff_assignment_json(rec):
    out = {
        "facility_id": rec["facility_id"],
        "staff_ref": rec["staff_ref"],
        "staff_name": rec["staff_name"],
        "role_type": rec["role_type"],
        "certification_expires_on": render_date(rec["certification_expires_on"]),
        "shift_start_at": render_datetime(rec["shift_start_at"]),
        "shift_end_at": render_datetime(rec["shift_end_at"]),
        "status": rec["status"],
        "cancel_reason": rec["cancel_reason"],
        "cancelled_at": render_datetime(rec["cancelled_at"]),
    }
    out.update(_common(rec))
    return out


def compliance_artifact_json(rec):
    out = {
        "facility_id": rec["facility_id"],
        "artifact_type": rec["artifact_type"],
        "signage_type": rec["signage_type"],
        "drain_cover_model": rec["drain_cover_model"],
        "sva_system_type": rec["sva_system_type"],
        "effective_on": render_date(rec["effective_on"]),
        "expires_on": render_date(rec["expires_on"]),
        "status": domain.artifact_status(rec),
    }
    out.update(_common(rec))
    return out


def complaint_json(rec):
    out = {
        "facility_id": rec["facility_id"],
        "linked_inspection_id": rec["linked_inspection_id"],
        "complaint_type": rec["complaint_type"],
        "reporter_contact": rec["reporter_contact"],
        "narrative": rec["narrative"],
        "symptom_onset_date": render_date(rec["symptom_onset_date"]),
        "illness_case_count": rec["illness_case_count"],
        "pathogen_suspected": rec["pathogen_suspected"],
        "reported_at": render_datetime(rec["reported_at"]),
        "risk_variant": rec["risk_variant"],
        "cluster_case_count": rec["cluster_case_count"],
        "risk_score": rec["risk_score"],
        "escalated": rec["escalated"],
        "status": rec["status"],
        "finding": rec["finding"],
    }
    out.update(_common(rec))
    return out


def ledger_entry_json(rec):
    out = {
        "operator_id": rec["operator_id"],
        "permit_id": rec["permit_id"],
        "entry_type": rec["entry_type"],
        "amount_cents": rec["amount_cents"],
        "posted_at": render_datetime(rec["posted_at"]),
        "reference_note": rec["reference_note"],
    }
    out.update(_common(rec, versioned=False))
    return out


def facility_of(rec_with_facility_id):
    return DB.facilities.get(rec_with_facility_id["facility_id"])
