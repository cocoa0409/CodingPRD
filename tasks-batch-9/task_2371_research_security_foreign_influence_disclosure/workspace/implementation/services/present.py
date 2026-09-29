"""Serializers. Derived fields are refreshed on every read."""

import util
from services import derive


def _common(record, payload):
    payload["id"] = record["id"]
    payload["created_at"] = record["created_at"]
    payload["updated_at"] = record["updated_at"]
    payload["version"] = record["version"]
    return payload


def investigator(record):
    derive.compute_investigator(record)
    return _common(record, {
        "full_name": record["full_name"],
        "email": record["email"],
        "appointment_type": record["appointment_type"],
        "home_department": record["home_department"],
        "institutional_base_effort_pct":
            util.num(record["institutional_base_effort_pct"]),
        "committed_effort_pct": util.num(record["committed_effort_pct"]),
        "outside_effort_pct": util.num(record["outside_effort_pct"]),
        "total_commitment_pct": util.num(record["total_commitment_pct"]),
        "overcommitment_pct": util.num(record["overcommitment_pct"]),
        "risk_score": record["risk_score"],
        "substantiated_incident_count": record["substantiated_incident_count"],
        "material_discrepancy_count": record["material_discrepancy_count"],
        "training_compliant": record["training_compliant"],
        "disclosure_posture": record["disclosure_posture"],
    })


def organization(record):
    designation, depth = derive.effective_designation(record)
    record["effective_designation"] = designation
    record["effective_designation_depth"] = depth
    return _common(record, {
        "legal_name": record["legal_name"],
        "country_code": record["country_code"],
        "org_type": record["org_type"],
        "parent_organization_id": record["parent_organization_id"],
        "parent_ownership_pct": util.num(record["parent_ownership_pct"]),
        "own_designation": record["own_designation"],
        "designated_on": record["designated_on"],
        "effective_designation": designation,
        "effective_designation_depth": depth,
    })


def project(record):
    derive.compute_project(record)
    return _common(record, {
        "title": record["title"],
        "agency_code": record["agency_code"],
        "sensitivity_level": record["sensitivity_level"],
        "award_amount_cents": record["award_amount_cents"],
        "period_start": record["period_start"],
        "period_end": record["period_end"],
        "controlled_area_capacity": record["controlled_area_capacity"],
        "award_status": record["award_status"],
        "security_status": record["security_status"],
        "security_status_reason": record["security_status_reason"],
        "activation_blockers": list(record["activation_blockers"]),
        "active_grant_count": record["active_grant_count"],
        "controlled_area_posture": record["controlled_area_posture"],
        "open_incident_count": record["open_incident_count"],
    })


def personnel(record):
    return _common(record, {
        "project_id": record["project_id"],
        "investigator_id": record["investigator_id"],
        "role_on_project": record["role_on_project"],
        "committed_person_months": util.num(record["committed_person_months"]),
        "status": record["status"],
    })


def disclosure(record):
    derive.compute_disclosure(record)
    return _common(record, {
        "investigator_id": record["investigator_id"],
        "cycle_label": record["cycle_label"],
        "disclosure_type": record["disclosure_type"],
        "review_status": record["review_status"],
        "plan_status": record["plan_status"],
        "revision_round": record["revision_round"],
        "item_count": record["item_count"],
        "late_item_count": record["late_item_count"],
        "undisclosed_item_count": record["undisclosed_item_count"],
        "completeness_score": record["completeness_score"],
        "completeness_tier": record["completeness_tier"],
        "submitted_at": record["submitted_at"],
        "certified_at": record["certified_at"],
        "reviewer_user_id": record["reviewer_user_id"],
        "plan_effort_cap_pct": util.num(record["plan_effort_cap_pct"]),
        "plan_required_actions": list(record["plan_required_actions"]),
        "plan_effective_from": record["plan_effective_from"],
        "plan_expires_on": record["plan_expires_on"],
        "plan_approver_user_id": record["plan_approver_user_id"],
        "plan_acknowledged_at": record["plan_acknowledged_at"],
    })


def item(record):
    derive.compute_item(record)
    return _common(record, {
        "disclosure_id": record["disclosure_id"],
        "item_type": record["item_type"],
        "foreign_organization_id": record["foreign_organization_id"],
        "annual_effort_hours": util.num(record["annual_effort_hours"]),
        "compensation_usd_cents": record["compensation_usd_cents"],
        "in_kind_value_cents": record["in_kind_value_cents"],
        "start_date": record["start_date"],
        "end_date": record["end_date"],
        "is_paid": record["is_paid"],
        "item_risk_points": record["item_risk_points"],
        "status": record["status"],
        "source": record["source"],
    })


def statement(record):
    return _common(record, {
        "investigator_id": record["investigator_id"],
        "project_id": record["project_id"],
        "agency_code": record["agency_code"],
        "document_type": record["document_type"],
        "declared_person_months": util.num(record["declared_person_months"]),
        "declared_appointment_count": record["declared_appointment_count"],
        "declared_support_count": record["declared_support_count"],
        "status": record["status"],
        "applied_variant": record["applied_variant"],
        "institutional_person_months": util.num(record["institutional_person_months"]),
        "variance_person_months": util.num(record["variance_person_months"]),
        "omission_count": record["omission_count"],
        "verdict": record["verdict"],
    })


def travel(record):
    return _common(record, {
        "investigator_id": record["investigator_id"],
        "project_id": record["project_id"],
        "host_organization_id": record["host_organization_id"],
        "destination_country_code": record["destination_country_code"],
        "depart_on": record["depart_on"],
        "return_on": record["return_on"],
        "purpose": record["purpose"],
        "carries_institutional_device": record["carries_institutional_device"],
        "risk_flag_count": record["risk_flag_count"],
        "device_requirement_tier": record["device_requirement_tier"],
        "briefing_required": record["briefing_required"],
        "status": record["status"],
        "device_decision_recorded_at": record["device_decision_recorded_at"],
    })


def grant(record):
    return _common(record, {
        "project_id": record["project_id"],
        "investigator_id": record["investigator_id"],
        "valid_from": record["valid_from"],
        "valid_until": record["valid_until"],
        "peak_concurrency_at_request": record["peak_concurrency_at_request"],
        "status": record["status"],
        "status_reason": record["status_reason"],
        "activated_at": record["activated_at"],
        "revoked_at": record["revoked_at"],
    })


def incident(record):
    return _common(record, {
        "investigator_id": record["investigator_id"],
        "disclosure_id": record["disclosure_id"],
        "project_id": record["project_id"],
        "incident_type": record["incident_type"],
        "discovered_on": record["discovered_on"],
        "summary": record["summary"],
        "status": record["status"],
        "finding": record["finding"],
        "severity_points": record["severity_points"],
        "severity": record["severity"],
        "lead_investigator_user_id": record["lead_investigator_user_id"],
        "substantiated_at": record["substantiated_at"],
        "notification_due_on": record["notification_due_on"],
        "agency_notified_on": record["agency_notified_on"],
        "notification_reference": record["notification_reference"],
        "notified_late": record["notified_late"],
        "closed_at": record["closed_at"],
    })


def training(record):
    return _common(record, {
        "investigator_id": record["investigator_id"],
        "required_for_project_id": record["required_for_project_id"],
        "course_code": record["course_code"],
        "assigned_on": record["assigned_on"],
        "due_on": record["due_on"],
        "completed_on": record["completed_on"],
        "waived_on": record["waived_on"],
        "status": derive.training_status(record),
    })


def subaward(record):
    return _common(record, {
        "project_id": record["project_id"],
        "organization_id": record["organization_id"],
        "scope": record["scope"],
        "amount_cents": record["amount_cents"],
        "status": record["status"],
        "applied_screening_variant": record["applied_screening_variant"],
        "screening_designation": record["screening_designation"],
        "screening_matched_organization_id": record["screening_matched_organization_id"],
        "screening_match_depth": record["screening_match_depth"],
        "screening_risk_points": record["screening_risk_points"],
        "mitigation_justification": record["mitigation_justification"],
        "executed_at": record["executed_at"],
        "terminated_at": record["terminated_at"],
    })
