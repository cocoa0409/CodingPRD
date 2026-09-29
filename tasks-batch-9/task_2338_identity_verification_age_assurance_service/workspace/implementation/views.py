"""Resource representations.

PRD 2.4: clients, method profiles, verification policies, verification sessions, method
attempts, biometric templates, alternative pathways, manual review cases and bias audits
carry id / created_at / updated_at / version. Document captures, liveness checks, age
assurance results, cohort metrics and audit events are write-once observations and carry
only id and created_at.
"""
import clock
import derived


def _common(record):
    return {
        "created_at": clock.to_iso(record["created_at"]),
        "updated_at": clock.to_iso(record["updated_at"]),
        "version": record["version"],
    }


def client_view(client):
    reserved = derived.reserved_review_credits(client)
    out = {
        "id": client["id"],
        "name": client["name"],
        "home_jurisdiction_code": client["home_jurisdiction_code"],
        "integration_state": client["integration_state"],
        "biometric_retention_mode": client["biometric_retention_mode"],
        "daily_session_quota": client["daily_session_quota"],
        "granted_review_credits": client["granted_review_credits"],
        "reserved_review_credits": reserved,
        "available_review_credits": client["granted_review_credits"] - reserved,
        "stored_template_count": derived.stored_template_count(client),
        "pending_stepup_count": derived.pending_stepup_count(client),
        "consumed_review_count": derived.consumed_review_count(client),
    }
    out.update(_common(client))
    return out


def method_profile_view(profile):
    out = {
        "id": profile["id"],
        "method_code": profile["method_code"],
        "vendor_code": profile["vendor_code"],
        "assurance_weight": profile["assurance_weight"],
        "acceptance_floor_bps": profile["acceptance_floor_bps"],
        "far_bps": profile["far_bps"],
        "frr_bps": profile["frr_bps"],
        "strong_evidence": profile["strong_evidence"],
        "cost_cents": profile["cost_cents"],
        "estimation_mae_months": profile["estimation_mae_months"],
        "band_accuracy_bps": profile["band_accuracy_bps"],
        "bias_state": profile["bias_state"],
        "restricted_at": clock.to_iso(profile["restricted_at"]),
    }
    out.update(_common(profile))
    return out


def policy_view(policy):
    out = {
        "id": policy["id"],
        "client_id": policy["client_id"],
        "policy_version": policy["policy_version"],
        "state": policy["state"],
        "allowed_method_codes": list(policy["allowed_method_codes"]),
        "min_assurance_score": policy["min_assurance_score"],
        "doc_authenticity_floor_bps": policy["doc_authenticity_floor_bps"],
        "pad_threshold_bps": policy["pad_threshold_bps"],
        "required_min_age_years": policy["required_min_age_years"],
        "age_buffer_multiplier_bps": policy["age_buffer_multiplier_bps"],
        "step_up_max_rounds": policy["step_up_max_rounds"],
        "alternative_pathway_enabled": policy["alternative_pathway_enabled"],
        "published_at": clock.to_iso(policy["published_at"]),
        "retired_at": clock.to_iso(policy["retired_at"]),
        "degraded_flag": derived.policy_degraded_flag(policy),
    }
    out.update(_common(policy))
    return out


def session_view(session):
    out = {
        "id": session["id"],
        "client_id": session["client_id"],
        "policy_id": session["policy_id"],
        "external_subject_ref": session["external_subject_ref"],
        "requested_assurance_tier": session["requested_assurance_tier"],
        "declared_transaction_value_cents": session["declared_transaction_value_cents"],
        "subject_jurisdiction_code": session["subject_jurisdiction_code"],
        "biometric_consent": session["biometric_consent"],
        "documentation_status": session["documentation_status"],
        "risk_score": session["risk_score"],
        "risk_level": session["risk_level"],
        "identity_state": session["identity_state"],
        "age_state": session["age_state"],
        "assurance_score_provisional": session["assurance_score_provisional"],
        "assurance_score_final": session["assurance_score_final"],
        "assurance_ceiling": session["assurance_ceiling"],
        "resolved_age_band": session["resolved_age_band"],
        "fraud_signal_count": derived.fraud_signal_count(session),
        "step_up_round": session["step_up_round"],
        "manual_override_flag": session["manual_override_flag"],
        "disposition_reason": session["disposition_reason"],
        "expires_at": clock.to_iso(session["expires_at"]),
        "completed_at": clock.to_iso(session["completed_at"]),
    }
    out.update(_common(session))
    return out


def attempt_view(attempt):
    out = {
        "id": attempt["id"],
        "session_id": attempt["session_id"],
        "method_profile_id": attempt["method_profile_id"],
        "method_code": attempt["method_code"],
        "selection_mode": attempt["selection_mode"],
        "retry_index": attempt["retry_index"],
        "state": attempt["state"],
        "evidence_quality_bps": attempt["evidence_quality_bps"],
        "match_score_bps": attempt["match_score_bps"],
        "contribution_points": attempt["contribution_points"],
        "tamper_flag": attempt["tamper_flag"],
        "rejection_reason": attempt["rejection_reason"],
        "finalized_at": clock.to_iso(attempt["finalized_at"]),
    }
    out.update(_common(attempt))
    return out


def document_capture_view(capture):
    return {
        "id": capture["id"],
        "attempt_id": capture["attempt_id"],
        "document_type": capture["document_type"],
        "required_feature_count": capture["required_feature_count"],
        "passed_feature_count": capture["passed_feature_count"],
        "tamper_signal_count": capture["tamper_signal_count"],
        "mrz_checksum_valid": capture["mrz_checksum_valid"],
        "base_score_bps": capture["base_score_bps"],
        "tamper_tier_multiplier_bps": capture["tamper_tier_multiplier_bps"],
        "tamper_penalty_bps": capture["tamper_penalty_bps"],
        "authenticity_score_bps": capture["authenticity_score_bps"],
        "assessment": capture["assessment"],
        "created_at": clock.to_iso(capture["created_at"]),
    }


def liveness_check_view(check):
    return {
        "id": check["id"],
        "attempt_id": check["attempt_id"],
        "capture_modality": check["capture_modality"],
        "pad_score_bps": check["pad_score_bps"],
        "retry_index": check["retry_index"],
        "effective_threshold_bps": check["effective_threshold_bps"],
        "decision": check["decision"],
        "created_at": clock.to_iso(check["created_at"]),
    }


def biometric_template_view(template):
    out = {
        "id": template["id"],
        "session_id": template["session_id"],
        "source_method_code": template["source_method_code"],
        "state": template["state"],
        "retention_expires_at": clock.to_iso(template["retention_expires_at"]),
        "deleted_at": clock.to_iso(template["deleted_at"]),
        "deletion_reason": template["deletion_reason"],
    }
    out.update(_common(template))
    return out


def age_result_view(result):
    return {
        "id": result["id"],
        "session_id": result["session_id"],
        "method": result["method"],
        "estimated_age_months": result["estimated_age_months"],
        "date_of_birth": result["date_of_birth"],
        "source_vendor_code": result["source_vendor_code"],
        "mae_months_snapshot": result["mae_months_snapshot"],
        "buffer_months": result["buffer_months"],
        "effective_age_months": result["effective_age_months"],
        "resolved_band": result["resolved_band"],
        "documented_accuracy_bps": result["documented_accuracy_bps"],
        "decision": result["decision"],
        "created_at": clock.to_iso(result["created_at"]),
    }


def pathway_view(pathway):
    out = {
        "id": pathway["id"],
        "session_id": pathway["session_id"],
        "pathway_type": pathway["pathway_type"],
        "state": pathway["state"],
        "voucher_reference": pathway["voucher_reference"],
        "attestation_document_ref": pathway["attestation_document_ref"],
        "reviewer_user_id": pathway["reviewer_user_id"],
        "granted_points": pathway["granted_points"],
        "decided_at": clock.to_iso(pathway["decided_at"]),
    }
    out.update(_common(pathway))
    return out


def review_case_view(case):
    out = {
        "id": case["id"],
        "session_id": case["session_id"],
        "trigger_reason": case["trigger_reason"],
        "state": case["state"],
        "assigned_by_user_id": case["assigned_by_user_id"],
        "assigned_reviewer_user_id": case["assigned_reviewer_user_id"],
        "sla_due_at": clock.to_iso(case["sla_due_at"]),
        "decision": case["decision"],
        "decided_by_user_id": case["decided_by_user_id"],
        "decided_at": clock.to_iso(case["decided_at"]),
    }
    out.update(_common(case))
    return out


def bias_audit_view(audit):
    out = {
        "id": audit["id"],
        "method_profile_id": audit["method_profile_id"],
        "window_start": clock.to_iso(audit["window_start"]),
        "window_end": clock.to_iso(audit["window_end"]),
        "state": audit["state"],
        "remediation_round": audit["remediation_round"],
        "included_cohort_count": audit["included_cohort_count"],
        "excluded_cohort_count": audit["excluded_cohort_count"],
        "insufficient_sample": audit["insufficient_sample"],
        "max_frr_bps": audit["max_frr_bps"],
        "min_frr_bps": audit["min_frr_bps"],
        "pooled_frr_bps": audit["pooled_frr_bps"],
        "disparity_ratio_max_to_min_bps": audit["disparity_ratio_max_to_min_bps"],
        "disparity_ratio_max_to_pooled_bps": audit["disparity_ratio_max_to_pooled_bps"],
        "worst_cohort_code": audit["worst_cohort_code"],
        "evaluated_by_user_id": audit["evaluated_by_user_id"],
        "remediated_by_user_id": audit["remediated_by_user_id"],
        "remediated_at": clock.to_iso(audit["remediated_at"]),
    }
    out.update(_common(audit))
    return out


def cohort_metric_view(metric):
    return {
        "id": metric["id"],
        "bias_audit_id": metric["bias_audit_id"],
        "cohort_code": metric["cohort_code"],
        "attempt_count": metric["attempt_count"],
        "false_reject_count": metric["false_reject_count"],
        "false_accept_count": metric["false_accept_count"],
        "frr_bps": metric["frr_bps"],
        "far_bps": metric["far_bps"],
        "included_in_ratio": metric["included_in_ratio"],
        "created_at": clock.to_iso(metric["created_at"]),
    }


def audit_event_view(event):
    return {
        "id": event["id"],
        "session_id": event["session_id"],
        "event_type": event["event_type"],
        "actor_role": event["actor_role"],
        "actor_user_id": event["actor_user_id"],
        "payload_summary": event["payload_summary"],
        "occurred_at": clock.to_iso(event["occurred_at"]),
        "created_at": clock.to_iso(event["created_at"]),
    }
