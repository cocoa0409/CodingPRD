"""Serializers: shape stored entities into API response objects.

Derived fields are refreshed on read so responses always reflect the logical
clock and the current source records.
"""
from db import DB
from services import refresh_employee_derived, refresh_license_derived


def license_type_view(lt):
    return {
        "id": lt["id"],
        "code": lt["code"],
        "name": lt["name"],
        "ce_hours_required_per_cycle": lt["ce_hours_required_per_cycle"],
        "cycle_length_months": lt["cycle_length_months"],
        "verification_frequency_days": lt["verification_frequency_days"],
        "grace_period_days": lt["grace_period_days"],
        "requires_exclusion_screening": lt["requires_exclusion_screening"],
        "reimbursement_mode": lt["reimbursement_mode"],
        "reimburse_full_up_to_cents": lt["reimburse_full_up_to_cents"],
        "reimburse_half_up_to_cents": lt["reimburse_half_up_to_cents"],
        "flat_schedule_amount_cents": lt["flat_schedule_amount_cents"],
        "hard_claim_cap_cents": lt["hard_claim_cap_cents"],
        "created_at": lt["created_at"],
        "updated_at": lt["updated_at"],
        "version": lt["version"],
    }


def role_requirement_view(rr):
    return {
        "id": rr["id"],
        "role_code": rr["role_code"],
        "license_type_id": rr["license_type_id"],
        "state_code": rr["state_code"],
        "is_required": rr["is_required"],
        "created_at": rr["created_at"],
        "updated_at": rr["updated_at"],
        "version": rr["version"],
    }


def employee_view(emp):
    refresh_employee_derived(emp)
    return {
        "id": emp["id"],
        "full_name": emp["full_name"],
        "work_email": emp["work_email"],
        "role_code": emp["role_code"],
        "work_authorization": emp["work_authorization"],
        "restriction_reason": emp["restriction_reason"],
        "screening_posture": emp["screening_posture"],
        "reimbursement_committed_cents": emp["reimbursement_committed_cents"],
        "reimbursement_paid_cents": emp["reimbursement_paid_cents"],
        "created_at": emp["created_at"],
        "updated_at": emp["updated_at"],
        "version": emp["version"],
    }


def license_view(lic):
    refresh_license_derived(lic)
    return {
        "id": lic["id"],
        "employee_id": lic["employee_id"],
        "license_type_id": lic["license_type_id"],
        "state_code": lic["state_code"],
        "license_number": lic["license_number"],
        "issued_on": lic["issued_on"],
        "expires_on": lic["expires_on"],
        "status": lic["status"],
        "last_verified_on": lic["last_verified_on"],
        "next_verification_due_on": lic["next_verification_due_on"],
        "verification_posture": lic["verification_posture"],
        "alert_tier": lic["alert_tier"],
        "ce_cycle_anchor_on": lic["ce_cycle_anchor_on"],
        "cycle_ce_hours_validated": lic["cycle_ce_hours_validated"],
        "rolling_ce_hours_validated": lic["rolling_ce_hours_validated"],
        "ce_progress_reported_pct": lic["ce_progress_reported_pct"],
        "ce_progress_required_pct": lic["ce_progress_required_pct"],
        "created_at": lic["created_at"],
        "updated_at": lic["updated_at"],
        "version": lic["version"],
    }


def verification_event_view(ev):
    # Append-only log: no updated_at, no version (PRD 2.4).
    return {
        "id": ev["id"],
        "license_id": ev["license_id"],
        "verified_on": ev["verified_on"],
        "source": ev["source"],
        "outcome": ev["outcome"],
        "verifier_user_id": ev["verifier_user_id"],
        "next_verification_due_on": ev["next_verification_due_on"],
        "created_at": ev["created_at"],
    }


def ce_activity_view(act):
    return {
        "id": act["id"],
        "license_id": act["license_id"],
        "provider_name": act["provider_name"],
        "activity_title": act["activity_title"],
        "hours": act["hours"],
        "rounded_hours": act["rounded_hours"],
        "completed_on": act["completed_on"],
        "status": act["status"],
        "adjudicated_by_user_id": act["adjudicated_by_user_id"],
        "created_at": act["created_at"],
        "updated_at": act["updated_at"],
        "version": act["version"],
    }


def renewal_request_view(req):
    return {
        "id": req["id"],
        "license_id": req["license_id"],
        "claimed_amount_cents": req["claimed_amount_cents"],
        "estimated_reimbursable_cents": req["estimated_reimbursable_cents"],
        "expires_on_at_create": req["expires_on_at_create"],
        "approved_amount_cents": req["approved_amount_cents"],
        "status": req["status"],
        "submitted_by_user_id": req["submitted_by_user_id"],
        "decided_by_user_id": req["decided_by_user_id"],
        "paid_by_user_id": req["paid_by_user_id"],
        "paid_on": req["paid_on"],
        "info_note": req["info_note"],
        "decision_note": req["decision_note"],
        "payment_ref": req["payment_ref"],
        "void_reason": req["void_reason"],
        "created_at": req["created_at"],
        "updated_at": req["updated_at"],
        "version": req["version"],
    }


def disciplinary_event_view(ev):
    return {
        "id": ev["id"],
        "license_id": ev["license_id"],
        "board_case_number": ev["board_case_number"],
        "event_type": ev["event_type"],
        "effective_on": ev["effective_on"],
        "received_via": ev["received_via"],
        "confirm_at_creation": ev["confirm_at_creation"],
        "applied_at_creation": ev["applied_at_creation"],
        "created_by_user_id": ev["created_by_user_id"],
        "adjudicated_by_user_id": ev["adjudicated_by_user_id"],
        "resolution_note": ev["resolution_note"],
        "status": ev["status"],
        "created_at": ev["created_at"],
        "updated_at": ev["updated_at"],
        "version": ev["version"],
    }


def exclusion_screening_view(scr):
    return {
        "id": scr["id"],
        "employee_id": scr["employee_id"],
        "list_source": scr["list_source"],
        "screened_on": scr["screened_on"],
        "outcome": scr["outcome"],
        "status": scr["status"],
        "valid_until": scr["valid_until"],
        "created_by_user_id": scr["created_by_user_id"],
        "resolved_by_user_id": scr["resolved_by_user_id"],
        "resolution_note": scr["resolution_note"],
        "created_at": scr["created_at"],
        "updated_at": scr["updated_at"],
        "version": scr["version"],
    }


def audit_package_view(pkg):
    return {
        "id": pkg["id"],
        "employee_id": pkg["employee_id"],
        "period_start": pkg["period_start"],
        "period_end": pkg["period_end"],
        "status": pkg["status"],
        "sealed_at": pkg["sealed_at"],
        "evidence_snapshot": pkg["evidence_snapshot"],
        "evidence_item_count": pkg["evidence_item_count"],
        "created_at": pkg["created_at"],
        "updated_at": pkg["updated_at"],
        "version": pkg["version"],
    }
