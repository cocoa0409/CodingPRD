"""Per-entity response serializers. Derived postures listed in PRD 2.12 are
recomputed fresh for the response and never written back by a read."""
import calc
import derive
from store import S, fmt_dt, now


def _common(row, out, versioned=True):
    out["created_at"] = fmt_dt(row["created_at"])
    if versioned:
        out["updated_at"] = fmt_dt(row["updated_at"])
        out["version"] = row["version"]
    return out


def client(row):
    out = {
        "id": row["id"],
        "legal_name": row["legal_name"],
        "industry_code": row["industry_code"],
        "grading_policy": row["grading_policy"],
        "max_trir": row["max_trir"],
        "max_dart_rate": row["max_dart_rate"],
        "max_emr": row["max_emr"],
        "max_citation_points": row["max_citation_points"],
        "weight_trir": row["weight_trir"],
        "weight_dart": row["weight_dart"],
        "weight_emr": row["weight_emr"],
        "weight_citation": row["weight_citation"],
        "conditional_band_pct": row["conditional_band_pct"],
        "requalification_interval_months": row["requalification_interval_months"],
        "audit_sample_rate_pct": row["audit_sample_rate_pct"],
        "cascade_depth_limit": row["cascade_depth_limit"],
        "required_coverage_types": list(row["required_coverage_types"]),
    }
    return _common(row, out)


def site(row):
    out = {
        "id": row["id"],
        "client_id": row["client_id"],
        "site_code": row["site_code"],
        "required_hazard_classes": list(row["required_hazard_classes"]),
        "min_grade": row["min_grade"],
        "granted_worker_count": derive.site_granted_worker_count(row["id"]),
        "access_gate_status": derive.site_access_gate_status(row["id"]),
    }
    return _common(row, out)


def contractor(row):
    out = {
        "id": row["id"],
        "legal_name": row["legal_name"],
        "scope_of_work": list(row["scope_of_work"]),
        "hazard_profile": list(row["hazard_profile"]),
        "employee_count": row["employee_count"],
        "status": row["status"],
        "base_hazard_tier": row["base_hazard_tier"],
        "incident_review_flag": row["incident_review_flag"],
        "open_severe_incident_count": row["open_severe_incident_count"],
        "open_deficiency_count": row["open_deficiency_count"],
        "verified_coverage_types": list(row["verified_coverage_types"]),
    }
    return _common(row, out)


def prequalification(row):
    out = {
        "id": row["id"],
        "contractor_id": row["contractor_id"],
        "client_id": row["client_id"],
        "cycle_year": row["cycle_year"],
        "status": row["status"],
        "statistics_verification_status": derive.statistics_verification_status(row["id"]),
        "document_review_status": derive.document_review_status(row),
        "provisional_composite_score": row["provisional_composite_score"],
        "final_composite_score": row["final_composite_score"],
        "grade": row["grade"],
        "deficiency_codes": list(row["deficiency_codes"]),
        "effective_thresholds": row["effective_thresholds"],
        "graded_at": fmt_dt(row["graded_at"]),
        "graded_by_user_id": row["graded_by_user_id"],
        "expires_at": fmt_dt(row["expires_at"]),
        "conditional_expires_at": fmt_dt(row["conditional_expires_at"]),
        "audit_state": row["audit_state"],
        "audit_selected_at": fmt_dt(row["audit_selected_at"]),
        "audit_findings_count": row["audit_findings_count"],
    }
    return _common(row, out)


def safety_statistic(row):
    out = {
        "id": row["id"],
        "prequalification_id": row["prequalification_id"],
        "reporting_year": row["reporting_year"],
        "hours_worked": row["hours_worked"],
        "recordable_incidents": row["recordable_incidents"],
        "dart_cases": row["dart_cases"],
        "fatalities": row["fatalities"],
        "emr": row["emr"],
        "citation_count_willful": row["citation_count_willful"],
        "citation_count_serious": row["citation_count_serious"],
        "citation_count_other": row["citation_count_other"],
        "source_document_ref": row["source_document_ref"],
        "verification_status": row["verification_status"],
        "verified_by_user_id": row["verified_by_user_id"],
        "verified_at": fmt_dt(row["verified_at"]),
        "trir": row["trir"],
        "dart_rate": row["dart_rate"],
        "citation_points": row["citation_points"],
    }
    return _common(row, out)


def written_program(row):
    preq = S.prequalifications[row["prequalification_id"]]
    contractor_row = S.contractors[preq["contractor_id"]]
    required = calc.required_program_set(contractor_row["hazard_profile"])
    out = {
        "id": row["id"],
        "prequalification_id": row["prequalification_id"],
        "program_type": row["program_type"],
        "revision_date": fmt_dt(row["revision_date"]),
        "document_ref": row["document_ref"],
        "review_status": row["review_status"],
        "reviewer_note": row["reviewer_note"],
        "reviewed_by_user_id": row["reviewed_by_user_id"],
        "is_required": row["program_type"] in required,
    }
    return _common(row, out)


def improvement_plan(row):
    out = {
        "id": row["id"],
        "prequalification_id": row["prequalification_id"],
        "due_date": fmt_dt(row["due_date"]),
        "milestone_count": row["milestone_count"],
        "deficiency_codes": list(row["deficiency_codes"]),
        "evidence_ref": row["evidence_ref"],
        "status": derive.plan_projected_status(row),
        "decided_by_user_id": row["decided_by_user_id"],
        "closed_at": fmt_dt(row["closed_at"]),
    }
    return _common(row, out)


def insurance_certificate(row):
    contractor_row = S.contractors[row["contractor_id"]]
    out = {
        "id": row["id"],
        "contractor_id": row["contractor_id"],
        "coverage_type": row["coverage_type"],
        "carrier_name": row["carrier_name"],
        "each_occurrence_limit": row["each_occurrence_limit"],
        "aggregate_limit": row["aggregate_limit"],
        "effective_date": fmt_dt(row["effective_date"]),
        "expiration_date": fmt_dt(row["expiration_date"]),
        "additional_insured": row["additional_insured"],
        "waiver_of_subrogation": row["waiver_of_subrogation"],
        "verification_status": row["verification_status"],
        "verified_by_user_id": row["verified_by_user_id"],
        "lifecycle_status": calc.lifecycle_status(row, now()),
        "available_aggregate": calc.available_aggregate(
            row["aggregate_limit"], contractor_row["open_severe_incident_count"]
        ),
    }
    return _common(row, out)


def worker(row):
    out = {
        "id": row["id"],
        "contractor_id": row["contractor_id"],
        "full_name": row["full_name"],
        "employee_ref": row["employee_ref"],
        "trade_code": row["trade_code"],
    }
    return _common(row, out, versioned=False)


def worker_qualification(row):
    out = {
        "id": row["id"],
        "worker_id": row["worker_id"],
        "qualification_code": row["qualification_code"],
        "issued_date": fmt_dt(row["issued_date"]),
        "expiration_date": fmt_dt(row["expiration_date"]),
        "training_provider": row["training_provider"],
        "evidence_ref": row["evidence_ref"],
    }
    return _common(row, out, versioned=False)


def site_access_grant(row):
    out = {
        "id": row["id"],
        "worker_id": row["worker_id"],
        "site_id": row["site_id"],
        "prequalification_id": row["prequalification_id"],
        "granted_at": fmt_dt(row["granted_at"]),
        "expires_at": fmt_dt(row["expires_at"]),
        "status": row["status"],
        "revocation_reason": row["revocation_reason"],
        "revoked_at": fmt_dt(row["revoked_at"]),
        "qualification_snapshot": list(row["qualification_snapshot"]),
    }
    return _common(row, out)


def incident_report(row):
    out = {
        "id": row["id"],
        "contractor_id": row["contractor_id"],
        "site_id": row["site_id"],
        "occurred_at": fmt_dt(row["occurred_at"]),
        "severity": row["severity"],
        "osha_reportable": row["osha_reportable"],
        "description": row["description"],
        "review_status": row["review_status"],
        "findings_note": row["findings_note"],
        "closed_at": fmt_dt(row["closed_at"]),
        "triggered_suspension_count": row["triggered_suspension_count"],
    }
    return _common(row, out)


def variance(row):
    out = {
        "id": row["id"],
        "prequalification_id": row["prequalification_id"],
        "requirement_code": row["requirement_code"],
        "requested_value": row["requested_value"],
        "justification": row["justification"],
        "status": row["status"],
        "expires_at": fmt_dt(row["expires_at"]),
        "decided_by_user_id": row["decided_by_user_id"],
    }
    return _common(row, out)


def subcontractor_link(row):
    out = {
        "id": row["id"],
        "parent_contractor_id": row["parent_contractor_id"],
        "child_contractor_id": row["child_contractor_id"],
        "prequalification_id": row["prequalification_id"],
        "scope_of_work": list(row["scope_of_work"]),
        "depth": row["depth"],
        "flow_down_status": row["flow_down_status"],
        "status": row["status"],
    }
    return _common(row, out)
