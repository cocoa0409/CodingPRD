"""Entity assertions and domain invariant checkers."""
from typing import Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AgeBand,
    AgeDecision,
    AgeMethod,
    AgeState,
    AttemptState,
    AuditEventType,
    AuditState,
    BiasState,
    BiometricRetentionMode,
    CaptureModality,
    CohortCode,
    DeletionReason,
    DocumentAssessment,
    DocumentType,
    IdentityState,
    IntegrationState,
    LivenessDecision,
    MethodCode,
    PathwayState,
    PathwayType,
    PolicyState,
    ReviewCaseState,
    ReviewTriggerReason,
    RiskLevel,
    SelectionMode,
    TemplateState,
)


def _values(enum_cls) -> list:
    return [member.value for member in enum_cls]


def assert_mutable_common_fields(data: dict) -> None:
    """Resources that carry the full common-field set."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version starts at 1, got {data['version']}"


def assert_write_once_common_fields(data: dict) -> None:
    """Write-once observations carry only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert "updated_at" not in data, "write-once records must not expose updated_at"
    assert "version" not in data, "write-once records must not expose version"


# --------------------------------------------------------------------------
# Clients
# --------------------------------------------------------------------------
def assert_client(data: dict) -> None:
    assert_mutable_common_fields(data)
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert data["home_jurisdiction_code"].isupper() and len(data["home_jurisdiction_code"]) == 2
    assert data["integration_state"] in _values(IntegrationState)
    assert data["biometric_retention_mode"] in _values(BiometricRetentionMode)
    assert data["daily_session_quota"] >= 1
    assert data["granted_review_credits"] >= 0
    assert_credit_pool_invariant(data)
    assert data["stored_template_count"] >= 0
    assert data["pending_stepup_count"] >= 0
    assert data["consumed_review_count"] >= 0


def assert_credit_pool_invariant(client: dict) -> None:
    """Reserved plus available credits always sum to the granted total."""
    assert client["reserved_review_credits"] >= 0
    assert (
        client["reserved_review_credits"] + client["available_review_credits"]
        == client["granted_review_credits"]
    ), (
        "reserved + available must equal granted, got "
        f"{client['reserved_review_credits']} + {client['available_review_credits']} "
        f"!= {client['granted_review_credits']}"
    )


# --------------------------------------------------------------------------
# Method profiles
# --------------------------------------------------------------------------
def assert_method_profile(data: dict) -> None:
    assert_mutable_common_fields(data)
    assert data["method_code"] in _values(MethodCode)
    assert 1 <= len(data["vendor_code"]) <= 24
    assert 1 <= data["assurance_weight"] <= 100
    assert 0 <= data["acceptance_floor_bps"] <= 10000
    assert 0 <= data["far_bps"] <= 10000
    assert 0 <= data["frr_bps"] <= 10000
    assert isinstance(data["strong_evidence"], bool)
    assert data["cost_cents"] >= 0
    assert data["estimation_mae_months"] >= 0
    assert isinstance(data["band_accuracy_bps"], dict)
    assert data["bias_state"] in _values(BiasState)


# --------------------------------------------------------------------------
# Verification policies
# --------------------------------------------------------------------------
def assert_verification_policy(data: dict) -> None:
    assert_mutable_common_fields(data)
    assert is_valid_uuid(data["client_id"])
    assert data["policy_version"] >= 1
    assert data["state"] in _values(PolicyState)
    assert isinstance(data["allowed_method_codes"], list) and data["allowed_method_codes"]
    for code in data["allowed_method_codes"]:
        assert code in ["DOCUMENT_SCAN", "DATABASE_CHECK", "BIOMETRIC_COMPARISON", "KNOWLEDGE_BASED"]
    assert 1 <= data["min_assurance_score"] <= 100
    assert 5001 <= data["doc_authenticity_floor_bps"] <= 10000
    assert 1000 <= data["pad_threshold_bps"] <= 9500
    assert 10000 <= data["age_buffer_multiplier_bps"] <= 30000
    assert 0 <= data["step_up_max_rounds"] <= 5
    assert 0 <= data["required_min_age_years"] <= 25
    assert isinstance(data["alternative_pathway_enabled"], bool)
    assert isinstance(data["degraded_flag"], bool)


# --------------------------------------------------------------------------
# Verification sessions
# --------------------------------------------------------------------------
def assert_verification_session(data: dict) -> None:
    assert_mutable_common_fields(data)
    assert is_valid_uuid(data["client_id"])
    assert is_valid_uuid(data["policy_id"])
    assert 1 <= len(data["external_subject_ref"]) <= 64
    assert data["requested_assurance_tier"] in ["BASIC", "STANDARD", "ENHANCED"]
    assert data["declared_transaction_value_cents"] >= 0
    assert len(data["subject_jurisdiction_code"]) == 2
    assert isinstance(data["biometric_consent"], bool)
    assert data["documentation_status"] in ["STANDARD_DOCS", "NO_STANDARD_DOCS"]
    assert data["risk_score"] >= 0
    assert data["risk_level"] in _values(RiskLevel)
    assert data["identity_state"] in _values(IdentityState)
    assert data["age_state"] in _values(AgeState)
    assert 0 <= data["assurance_score_provisional"] <= 100
    if data["assurance_score_final"] is not None:
        assert 0 <= data["assurance_score_final"] <= 100
    assert 0 <= data["assurance_ceiling"] <= 100
    if data["resolved_age_band"] is not None:
        assert data["resolved_age_band"] in _values(AgeBand)
    assert data["fraud_signal_count"] >= 0
    assert data["step_up_round"] >= 0
    assert isinstance(data["manual_override_flag"], bool)
    assert is_iso8601_timestamp(data["expires_at"])


def assert_risk_banding(session: dict) -> None:
    """The derived risk level follows the frozen risk score."""
    score = session["risk_score"]
    if score >= 70:
        expected = "HIGH"
    elif score >= 40:
        expected = "MEDIUM"
    else:
        expected = "LOW"
    assert session["risk_level"] == expected, (
        f"risk_score {score} must band as {expected}, got {session['risk_level']}"
    )


# --------------------------------------------------------------------------
# Method attempts
# --------------------------------------------------------------------------
def assert_method_attempt(data: dict) -> None:
    assert_mutable_common_fields(data)
    assert is_valid_uuid(data["session_id"])
    assert is_valid_uuid(data["method_profile_id"])
    assert data["method_code"] in _values(MethodCode)
    assert data["selection_mode"] in _values(SelectionMode)
    assert data["retry_index"] >= 0
    assert data["state"] in _values(AttemptState)
    assert isinstance(data["tamper_flag"], bool)


def assert_contribution_truncated(attempt: dict, assurance_weight: int) -> None:
    """Each attempt's contribution is truncated toward zero before summation."""
    quality = attempt["evidence_quality_bps"]
    assert quality is not None, "evidence quality must be scored before contribution"
    expected = assurance_weight * quality // 10000
    assert attempt["contribution_points"] == expected, (
        f"contribution_points must be {expected} for weight {assurance_weight} and "
        f"quality {quality}, got {attempt['contribution_points']}"
    )


# --------------------------------------------------------------------------
# Evidence rows
# --------------------------------------------------------------------------
def assert_document_capture(data: dict) -> None:
    assert_write_once_common_fields(data)
    assert is_valid_uuid(data["attempt_id"])
    assert data["document_type"] in _values(DocumentType)
    assert 1 <= data["required_feature_count"] <= 40
    assert 0 <= data["passed_feature_count"] <= data["required_feature_count"]
    assert 0 <= data["tamper_signal_count"] <= 20
    assert isinstance(data["mrz_checksum_valid"], bool)
    assert 0 <= data["base_score_bps"] <= 10000
    assert data["tamper_tier_multiplier_bps"] in [10000, 15000, 20000]
    assert data["tamper_penalty_bps"] >= 0
    assert 0 <= data["authenticity_score_bps"] <= 10000
    assert data["assessment"] in _values(DocumentAssessment)


def assert_liveness_check(data: dict) -> None:
    assert_write_once_common_fields(data)
    assert is_valid_uuid(data["attempt_id"])
    assert data["capture_modality"] in _values(CaptureModality)
    assert 0 <= data["pad_score_bps"] <= 10000
    assert data["retry_index"] >= 0
    assert 0 <= data["effective_threshold_bps"] <= 9500
    assert data["decision"] in _values(LivenessDecision)


def assert_age_assurance_result(data: dict) -> None:
    assert_write_once_common_fields(data)
    assert is_valid_uuid(data["session_id"])
    assert data["method"] in _values(AgeMethod)
    assert data["buffer_months"] >= 0
    assert data["effective_age_months"] >= 0
    assert data["resolved_band"] in _values(AgeBand)
    assert data["decision"] in _values(AgeDecision)


# --------------------------------------------------------------------------
# Biometric templates
# --------------------------------------------------------------------------
def assert_biometric_template(data: dict) -> None:
    assert_mutable_common_fields(data)
    assert is_valid_uuid(data["session_id"])
    assert data["source_method_code"] == "BIOMETRIC_COMPARISON"
    assert data["state"] in _values(TemplateState)
    if data["deletion_reason"] is not None:
        assert data["deletion_reason"] in _values(DeletionReason)


# --------------------------------------------------------------------------
# Inclusion pathways
# --------------------------------------------------------------------------
def assert_alternative_pathway(data: dict) -> None:
    assert_mutable_common_fields(data)
    assert is_valid_uuid(data["session_id"])
    assert data["pathway_type"] in _values(PathwayType)
    assert data["state"] in _values(PathwayState)


# --------------------------------------------------------------------------
# Manual review cases
# --------------------------------------------------------------------------
def assert_manual_review_case(data: dict) -> None:
    assert_mutable_common_fields(data)
    assert is_valid_uuid(data["session_id"])
    assert data["trigger_reason"] in _values(ReviewTriggerReason)
    assert data["state"] in _values(ReviewCaseState)
    assert is_iso8601_timestamp(data["sla_due_at"])


# --------------------------------------------------------------------------
# Bias audits and cohort rows
# --------------------------------------------------------------------------
def assert_bias_audit(data: dict) -> None:
    assert_mutable_common_fields(data)
    assert is_valid_uuid(data["method_profile_id"])
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["state"] in _values(AuditState)
    assert data["remediation_round"] >= 0
    assert data["included_cohort_count"] >= 0
    assert data["excluded_cohort_count"] >= 0
    assert isinstance(data["insufficient_sample"], bool)
    if data["worst_cohort_code"] is not None:
        assert data["worst_cohort_code"] in _values(CohortCode)


def assert_cohort_metric(data: dict) -> None:
    assert_write_once_common_fields(data)
    assert is_valid_uuid(data["bias_audit_id"])
    assert data["cohort_code"] in _values(CohortCode)
    assert data["attempt_count"] >= 0
    assert 0 <= data["false_reject_count"] <= data["attempt_count"]
    assert 0 <= data["false_accept_count"] <= data["attempt_count"]
    assert 0 <= data["frr_bps"] <= 10000
    assert 0 <= data["far_bps"] <= 10000
    assert isinstance(data["included_in_ratio"], bool)


# --------------------------------------------------------------------------
# Audit trail
# --------------------------------------------------------------------------
def assert_audit_event(data: dict) -> None:
    assert_write_once_common_fields(data)
    assert is_valid_uuid(data["session_id"])
    assert data["event_type"] in _values(AuditEventType)
    assert is_iso8601_timestamp(data["occurred_at"])


def find_events(events: list, event_type: str) -> list:
    return [event for event in events if event.get("event_type") == event_type]


def assert_event_recorded(events: list, event_type: str, expected_count: int = 1) -> None:
    matching = find_events(events, event_type)
    assert len(matching) == expected_count, (
        f"expected {expected_count} {event_type} event(s), found {len(matching)}"
    )


# --------------------------------------------------------------------------
# Cross-resource invariants
# --------------------------------------------------------------------------
def assert_stored_template_count_matches(client: dict, templates: list) -> None:
    stored = [t for t in templates if t["state"] == "STORED"]
    assert client["stored_template_count"] == len(stored), (
        f"stored_template_count {client['stored_template_count']} must equal the "
        f"{len(stored)} template(s) still in STORED"
    )


def assert_pending_stepup_matches(client: dict, sessions: list) -> None:
    awaiting = [s for s in sessions if s["identity_state"] == "AWAITING_EVIDENCE"]
    assert client["pending_stepup_count"] == len(awaiting), (
        f"pending_stepup_count {client['pending_stepup_count']} must equal the "
        f"{len(awaiting)} session(s) at AWAITING_EVIDENCE"
    )


def assert_reserved_credits_match_assigned(client: dict, cases: list) -> None:
    assigned = [c for c in cases if c["state"] == "ASSIGNED"]
    assert client["reserved_review_credits"] == len(assigned), (
        f"reserved_review_credits {client['reserved_review_credits']} must equal the "
        f"{len(assigned)} case(s) in ASSIGNED"
    )
