"""Payload serializers: exactly the fields each entity publishes."""

from services import calc, derive


def _common(row, out, versioned=True):
    out["id"] = row["id"]
    out["created_at"] = row.get("created_at")
    if versioned:
        out["updated_at"] = row.get("updated_at")
        out["version"] = row.get("version")
    return out


def assessor(row):
    out = {
        "full_name": row.get("full_name"),
        "email": row.get("email"),
        "certification_expires_at": row.get("certification_expires_at"),
        "qa_qualified": row.get("qa_qualified"),
        "status": row.get("status"),
        "certification_status": derive.certification_status(row),
        "lead_engagement_count": derive.lead_engagement_count(row["id"]),
    }
    return _common(row, out)


def asv_vendor(row):
    out = {
        "name": row.get("name"),
        "approval_expires_at": row.get("approval_expires_at"),
        "approval_status": row.get("approval_status"),
        "effective_approval": derive.effective_approval(row),
    }
    return _common(row, out)


def engagement(row):
    engagement_id = row["id"]
    counts = derive.partition_counts(engagement_id)
    projection = derive.compliance_projection(engagement_id)
    plan = derive.active_plan(engagement_id)
    out = {
        "client_legal_name": row.get("client_legal_name"),
        "merchant_level": row.get("merchant_level"),
        "assessment_year": row.get("assessment_year"),
        "acquirer_name": row.get("acquirer_name"),
        "fieldwork_start_date": row.get("fieldwork_start_date"),
        "fieldwork_end_date": row.get("fieldwork_end_date"),
        "approved_budget_amount": calc.as_float(row.get("approved_budget_amount"), 2),
        "lead_assessor_id": row.get("lead_assessor_id"),
        "qa_reviewer_id": row.get("qa_reviewer_id"),
        "status": row.get("status"),
        "posture": derive.posture(row),
        "scope_locked": row.get("scope_locked"),
        "cde_component_count": counts["cde_component_count"],
        "connected_component_count": counts["connected_component_count"],
        "out_of_scope_component_count": counts["out_of_scope_component_count"],
        "in_scope_component_count": counts["in_scope_component_count"],
        "unvalidated_segment_count": derive.unvalidated_segment_count(engagement_id),
        "open_gap_count": derive.open_gap_count(engagement_id),
        "unmet_requirement_count": derive.unmet_requirement_count(engagement_id),
        "applicable_requirement_count": projection["applicable_requirement_count"],
        "accepted_ccw_count": derive.accepted_ccw_count(engagement_id),
        "active_sampling_plan_id": plan["id"] if plan is not None else None,
        "active_plan_stale": derive.active_plan_stale(engagement_id),
        "estimated_hours": row.get("estimated_hours"),
        "assessment_fee_total": calc.as_float(row.get("assessment_fee_total"), 2),
        "as_found_compliance_percentage": float(projection["as_found_compliance_percentage"]),
        "as_attested_compliance_percentage": float(projection["as_attested_compliance_percentage"]),
        "quarterly_scan_compliant": derive.quarterly_scan_compliant(engagement_id),
        "scope_affecting_change_count": derive.scope_affecting_change_count(engagement_id),
        "reassessment_required": derive.reassessment_required(engagement_id),
        "reassessment_due_date": row.get("reassessment_due_date"),
        "next_assessment_start_date": row.get("next_assessment_start_date"),
        "attested_at": row.get("attested_at"),
    }
    return _common(row, out)


def engagement_summary(row):
    engagement_id = row["id"]
    counts = derive.partition_counts(engagement_id)
    projection = derive.compliance_projection(engagement_id)
    return {
        "engagement_id": engagement_id,
        "posture": derive.posture(row),
        "cde_component_count": counts["cde_component_count"],
        "connected_component_count": counts["connected_component_count"],
        "out_of_scope_component_count": counts["out_of_scope_component_count"],
        "total_component_count": counts["total_component_count"],
        "open_gap_count": derive.open_gap_count(engagement_id),
        "unvalidated_segment_count": derive.unvalidated_segment_count(engagement_id),
        "accepted_ccw_count": derive.accepted_ccw_count(engagement_id),
        "estimated_hours": row.get("estimated_hours"),
        "assessment_fee_total": calc.as_float(row.get("assessment_fee_total"), 2),
        "as_found_compliance_percentage": float(projection["as_found_compliance_percentage"]),
        "as_attested_compliance_percentage": float(projection["as_attested_compliance_percentage"]),
        "quarterly_scan_compliant": derive.quarterly_scan_compliant(engagement_id),
        "scope_affecting_change_count": derive.scope_affecting_change_count(engagement_id),
        "reassessment_required": derive.reassessment_required(engagement_id),
    }


def network_segment(row):
    out = {
        "engagement_id": row.get("engagement_id"),
        "name": row.get("name"),
        "segment_class": row.get("segment_class"),
        "parent_segment_id": row.get("parent_segment_id"),
        "segmentation_status": row.get("segmentation_status"),
        "test_method": row.get("test_method"),
        "planned_date": row.get("planned_date"),
        "effective_class": row.get("effective_class"),
        "scope_expanded_by_failure": row.get("scope_expanded_by_failure"),
        "revalidation_round": row.get("revalidation_round"),
        "last_validated_at": row.get("last_validated_at"),
    }
    return _common(row, out)


def system_component(row):
    out = {
        "engagement_id": row.get("engagement_id"),
        "segment_id": row.get("segment_id"),
        "hostname": row.get("hostname"),
        "component_type": row.get("component_type"),
        "function_class": row.get("function_class"),
        "stores_chd": row.get("stores_chd"),
        "facility_name": row.get("facility_name"),
        "facility_type": row.get("facility_type"),
        "declared_scope_class": row.get("declared_scope_class"),
        "scope_class": row.get("scope_class"),
        "sampling_stratum": row.get("sampling_stratum"),
        "in_sample": row.get("in_sample"),
    }
    return _common(row, out)


def sampling_plan(row):
    out = {
        "engagement_id": row.get("engagement_id"),
        "plan_variant": row.get("plan_variant"),
        "justification_text": row.get("justification_text"),
        "status": row.get("status"),
        "eligible_component_count": row.get("eligible_component_count"),
        "component_sample_size": row.get("component_sample_size"),
        "stratum_allocations": dict(row.get("stratum_allocations") or {}),
        "facility_population_count": row.get("facility_population_count"),
        "facility_sample_size": row.get("facility_sample_size"),
        "sampled_facility_names": list(row.get("sampled_facility_names") or []),
        "coverage_ratio": calc.as_float(row.get("coverage_ratio"), 4),
        "superseded_at": row.get("superseded_at"),
    }
    return _common(row, out)


def requirement_assessment(row):
    out = {
        "engagement_id": row.get("engagement_id"),
        "requirement_ref": row.get("requirement_ref"),
        "requirement_family": row.get("requirement_family"),
        "testing_procedure_count": row.get("testing_procedure_count"),
        "applicability": row.get("applicability"),
        "test_status": row.get("test_status"),
        "remediation_status": row.get("remediation_status"),
        "evidence_item_count": row.get("evidence_item_count"),
        "evidence_type_coverage": list(row.get("evidence_type_coverage") or []),
        "evidence_completeness": row.get("evidence_completeness"),
        "conclusion_rationale": row.get("conclusion_rationale"),
        "reopen_count": row.get("reopen_count"),
        "risk_points": row.get("risk_points"),
    }
    return _common(row, out)


def evidence_item(row):
    out = {
        "requirement_assessment_id": row.get("requirement_assessment_id"),
        "engagement_id": row.get("engagement_id"),
        "evidence_type": row.get("evidence_type"),
        "procedure_ref": row.get("procedure_ref"),
        "component_id": row.get("component_id"),
        "interviewee_name": row.get("interviewee_name"),
        "interviewee_title": row.get("interviewee_title"),
        "sufficiency": row.get("sufficiency"),
        "collector_assessor_id": row.get("collector_assessor_id"),
        "collected_at": row.get("collected_at"),
        "note": row.get("note"),
    }
    return _common(row, out, versioned=False)


def ccw(row):
    out = {
        "requirement_assessment_id": row.get("requirement_assessment_id"),
        "engagement_id": row.get("engagement_id"),
        "constraint_text": row.get("constraint_text"),
        "objective_text": row.get("objective_text"),
        "identified_risk_text": row.get("identified_risk_text"),
        "control_refs": list(row.get("control_refs") or []),
        "monitoring_interval_days": row.get("monitoring_interval_days"),
        "validation_text": row.get("validation_text"),
        "maintenance_text": row.get("maintenance_text"),
        "status": row.get("status"),
        "control_depth_points": calc.as_float(row.get("control_depth_points"), 2),
        "monitoring_factor": calc.as_float(row.get("monitoring_factor"), 2),
        "risk_offset_points": calc.as_float(row.get("risk_offset_points"), 2),
        "rigor_score": calc.as_float(row.get("rigor_score"), 2),
        "thin_control_capped": row.get("thin_control_capped"),
        "reviewer_note": row.get("reviewer_note"),
        "decided_at": row.get("decided_at"),
    }
    return _common(row, out)


def remediation_item(row):
    out = {
        "engagement_id": row.get("engagement_id"),
        "requirement_assessment_id": row.get("requirement_assessment_id"),
        "source": row.get("source"),
        "source_scan_finding_id": row.get("source_scan_finding_id"),
        "gap_description": row.get("gap_description"),
        "severity": row.get("severity"),
        "status": row.get("status"),
        "owner_reference": row.get("owner_reference"),
        "due_date": row.get("due_date"),
        "retest_count": row.get("retest_count"),
        "closed_at": row.get("closed_at"),
    }
    return _common(row, out)


def roc_report(row):
    out = {
        "engagement_id": row.get("engagement_id"),
        "roc_version_label": row.get("roc_version_label"),
        "status": row.get("status"),
        "applicable_requirement_count": row.get("applicable_requirement_count"),
        "in_place_count": row.get("in_place_count"),
        "ccw_covered_count": row.get("ccw_covered_count"),
        "not_in_place_count": row.get("not_in_place_count"),
        "as_found_compliance_percentage": calc.as_float(
            row.get("as_found_compliance_percentage"), 2),
        "as_attested_compliance_percentage": calc.as_float(
            row.get("as_attested_compliance_percentage"), 2),
        "compliance_result": row.get("compliance_result"),
        "attestation_signature_name": row.get("attestation_signature_name"),
        "attesting_assessor_id": row.get("attesting_assessor_id"),
        "attested_at": row.get("attested_at"),
        "submitted_to": row.get("submitted_to"),
        "submission_reference": row.get("submission_reference"),
        "qa_decision_note": row.get("qa_decision_note"),
        "revision_count": row.get("revision_count"),
    }
    return _common(row, out)


def scan_cycle(row):
    out = {
        "engagement_id": row.get("engagement_id"),
        "asv_vendor_id": row.get("asv_vendor_id"),
        "quarter_label": row.get("quarter_label"),
        "window_start": row.get("window_start"),
        "window_end": row.get("window_end"),
        "status": row.get("status"),
        "raw_high_finding_count": row.get("raw_high_finding_count"),
        "accepted_false_positive_count": row.get("accepted_false_positive_count"),
        "effective_high_finding_count": row.get("effective_high_finding_count"),
        "open_dispute_count": row.get("open_dispute_count"),
        "scan_completed_at": row.get("scan_completed_at"),
        "attestation_of_scan_compliance": row.get("attestation_of_scan_compliance"),
    }
    return _common(row, out)


def scan_finding(row):
    out = {
        "scan_cycle_id": row.get("scan_cycle_id"),
        "component_id": row.get("component_id"),
        "plugin_reference": row.get("plugin_reference"),
        "cvss_score": calc.as_float(row.get("cvss_score"), 1),
        "severity_class": row.get("severity_class"),
        "dispute_status": row.get("dispute_status"),
        "dispute_rationale": row.get("dispute_rationale"),
        "decision_note": row.get("decision_note"),
        "decided_at": row.get("decided_at"),
    }
    return _common(row, out)


def change_log_entry(row):
    out = {
        "engagement_id": row.get("engagement_id"),
        "component_id": row.get("component_id"),
        "change_type": row.get("change_type"),
        "description": row.get("description"),
        "affects_scope": row.get("affects_scope"),
        "triggers_reassessment": row.get("triggers_reassessment"),
        "recorded_at": row.get("recorded_at"),
    }
    return _common(row, out, versioned=False)
