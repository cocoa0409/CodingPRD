"""Response payload builders. Computed fields are derived at read time."""
import calculations as calc
from timeutil import iso


def _num(value):
    return None if value is None else float(value)


def service_out(service):
    service_id = service["id"]
    share = calc.audience_child_share(service_id)
    sh_status, sh_expires = calc.safe_harbor_state(service_id)
    return {
        "id": service_id,
        "name": service["name"],
        "operator_organization": service["operator_organization"],
        "service_category": service["service_category"],
        "subject_matter_code": service["subject_matter_code"],
        "determination_status": service["determination_status"],
        "determination_variant_applied": service["determination_variant_applied"],
        "design_score": _num(calc.design_score(service_id)),
        "audience_child_share": _num(share),
        "determination_evaluated_at": iso(service["determination_evaluated_at"]),
        "compliance_posture": calc.compliance_posture(service),
        "posture_override": service["posture_override"],
        "active_consent_count": calc.active_consent_count(service_id),
        "granted_disclosure_consent_count": calc.granted_disclosure_consent_count(service_id),
        "live_child_data_element_count": calc.live_child_data_element_count(service_id),
        "lifetime_collected_element_count": calc.lifetime_collected_element_count(service_id),
        "third_party_exposure_points": calc.third_party_exposure_points(service_id),
        "open_audit_count": calc.open_audit_count(service_id),
        "audit_decision_count": service["audit_decision_count"],
        "safe_harbor_status": sh_status,
        "safe_harbor_expires_at": iso(sh_expires),
        "evidence_sequence_counter": service["evidence_sequence_counter"],
        "compliance_run_sequence": service["compliance_run_sequence"],
        "created_at": iso(service["created_at"]),
        "updated_at": iso(service["updated_at"]),
        "version": service["version"],
    }


def evidence_out(row):
    # Evidence is append-only: no updated_at and no version field, deliberately.
    return {
        "id": row["id"],
        "service_id": row["service_id"],
        "evidence_kind": row["evidence_kind"],
        "evidence_sequence": row["evidence_sequence"],
        "measurement_method": row["measurement_method"],
        "period_start": iso(row["period_start"]),
        "period_end": iso(row["period_end"]),
        "total_users": row["total_users"],
        "users_under_13": row["users_under_13"],
        "sample_verified": row["sample_verified"],
        "factor_code": row["factor_code"],
        "rating": row["rating"],
        "evidence_note": row["evidence_note"],
        "created_at": iso(row["created_at"]),
    }


def age_screen_out(screen):
    return {
        "id": screen["id"],
        "service_id": screen["service_id"],
        "mechanism": screen["mechanism"],
        "default_prefilled_age": screen["default_prefilled_age"],
        "retry_allowed_on_fail": screen["retry_allowed_on_fail"],
        "outcome_session_persisted": screen["outcome_session_persisted"],
        "inherited_from_verified_account": screen["inherited_from_verified_account"],
        "status": screen["status"],
        "neutrality_violation_codes": calc.age_screen_neutrality(screen),
        "revision_round": screen["revision_round"],
        "activated_at": iso(screen["activated_at"]),
        "review_note": screen.get("review_note"),
        "created_at": iso(screen["created_at"]),
        "updated_at": iso(screen["updated_at"]),
        "version": screen["version"],
    }


def notice_out(notice):
    return {
        "id": notice["id"],
        "service_id": notice["service_id"],
        "notice_label": notice["notice_label"],
        "delivery_channel": notice["delivery_channel"],
        "content_keys": notice["content_keys"],
        "disclosed_integration_vendors": notice["disclosed_integration_vendors"],
        "missing_content_keys": calc.missing_content_keys(notice["content_keys"]),
        "status": notice["status"],
        "published_at": iso(notice["published_at"]),
        "created_at": iso(notice["created_at"]),
        "updated_at": iso(notice["updated_at"]),
        "version": notice["version"],
    }


def activity_out(activity):
    return {
        "id": activity["id"],
        "service_id": activity["service_id"],
        "activity_code": activity["activity_code"],
        "participation_required_elements": activity["participation_required_elements"],
        "created_at": iso(activity["created_at"]),
        "updated_at": iso(activity["updated_at"]),
        "version": activity["version"],
    }


def consent_out(consent):
    return {
        "id": consent["id"],
        "service_id": consent["service_id"],
        "notice_id": consent["notice_id"],
        "parent_email": consent["parent_email"],
        "child_pseudonym": consent["child_pseudonym"],
        "intended_uses": consent["intended_uses"],
        "consent_method": consent["consent_method"],
        "method_assurance_tier": consent["method_assurance_tier"],
        "required_tier_at_creation": consent["required_tier_at_creation"],
        "status": consent["status"],
        "notice_delivered_at": iso(consent["notice_delivered_at"]),
        "verification_deadline_at": iso(consent["verification_deadline_at"]),
        "secondary_confirmation_received": consent["secondary_confirmation_received"],
        "verification_evidence_code": consent["verification_evidence_code"],
        "granted_at": iso(consent["granted_at"]),
        "revoked_at": iso(consent["revoked_at"]),
        "revocation_reason": consent["revocation_reason"],
        "denial_reason": consent.get("denial_reason"),
        "created_at": iso(consent["created_at"]),
        "updated_at": iso(consent["updated_at"]),
        "version": consent["version"],
    }


def record_out(record):
    return {
        "id": record["id"],
        "service_id": record["service_id"],
        "consent_request_id": record["consent_request_id"],
        "activity_id": record["activity_id"],
        "child_pseudonym": record["child_pseudonym"],
        "data_element_code": record["data_element_code"],
        "purpose_code": record["purpose_code"],
        "age_screen_outcome": record["age_screen_outcome"],
        "collected_at": iso(record["collected_at"]),
        "retention_days_applied": record["retention_days_applied"],
        "disposal_method_applied": record["disposal_method_applied"],
        "disposal_due_at": iso(record["disposal_due_at"]),
        "scheduled_run_sequence": record["scheduled_run_sequence"],
        "disposed_at": iso(record["disposed_at"]),
        "status": record["status"],
        "created_at": iso(record["created_at"]),
        "updated_at": iso(record["updated_at"]),
        "version": record["version"],
    }


def rights_out(request_row):
    return {
        "id": request_row["id"],
        "service_id": request_row["service_id"],
        "consent_request_id": request_row["consent_request_id"],
        "right_type": request_row["right_type"],
        "requester_email": request_row["requester_email"],
        "verification_method": request_row["verification_method"],
        "verification_attempt_count": request_row["verification_attempt_count"],
        "scope_mode": request_row["scope_mode"],
        "in_scope_record_count": request_row["in_scope_record_count"],
        "status": request_row["status"],
        "fulfilled_at": iso(request_row["fulfilled_at"]),
        "rejection_reason": request_row.get("rejection_reason"),
        "created_at": iso(request_row["created_at"]),
        "updated_at": iso(request_row["updated_at"]),
        "version": request_row["version"],
    }


def integration_out(integration):
    return {
        "id": integration["id"],
        "service_id": integration["service_id"],
        "vendor_name": integration["vendor_name"],
        "integration_type": integration["integration_type"],
        "collects_persistent_identifier": integration["collects_persistent_identifier"],
        "placement_area": integration["placement_area"],
        "status": integration["status"],
        "exposure_points": calc.integration_exposure_points(integration),
        "disclosed_in_notice": calc.disclosed_in_notice(integration),
        "last_audit_decision_at": iso(integration["last_audit_decision_at"]),
        "audit_note": integration["audit_note"],
        "created_at": iso(integration["created_at"]),
        "updated_at": iso(integration["updated_at"]),
        "version": integration["version"],
    }


def schedule_out(schedule):
    return {
        "id": schedule["id"],
        "service_id": schedule["service_id"],
        "data_element_code": schedule["data_element_code"],
        "purpose_code": schedule["purpose_code"],
        "retention_days": schedule["retention_days"],
        "disposal_method": schedule["disposal_method"],
        "effective_from": iso(schedule["effective_from"]),
        "effective_to": iso(schedule["effective_to"]),
        "defined_purpose_statement": schedule["defined_purpose_statement"],
        "created_at": iso(schedule["created_at"]),
        "updated_at": iso(schedule["updated_at"]),
        "version": schedule["version"],
    }


def program_out(program):
    return {
        "id": program["id"],
        "program_name": program["program_name"],
        "regulator_approved": program["regulator_approved"],
        "annual_assessment_required": program["annual_assessment_required"],
        "assessment_validity_days": program["assessment_validity_days"],
        "assessment_grace_days": program["assessment_grace_days"],
        "created_at": iso(program["created_at"]),
        "updated_at": iso(program["updated_at"]),
        "version": program["version"],
    }


def assessment_out(assessment):
    return {
        "id": assessment["id"],
        "service_id": assessment["service_id"],
        "program_id": assessment["program_id"],
        "assessment_year": assessment["assessment_year"],
        "preparer_user_id": assessment["preparer_user_id"],
        "certifier_user_id": assessment["certifier_user_id"],
        "findings_open_count": assessment["findings_open_count"],
        "remediation_round": assessment["remediation_round"],
        "status": assessment["status"],
        "certified_at": iso(assessment["certified_at"]),
        "expires_at": iso(assessment["expires_at"]),
        "remediation_note": assessment.get("remediation_note"),
        "created_at": iso(assessment["created_at"]),
        "updated_at": iso(assessment["updated_at"]),
        "version": assessment["version"],
    }
