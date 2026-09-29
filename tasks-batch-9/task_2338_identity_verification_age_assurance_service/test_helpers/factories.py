"""Payload factories — one per resource, input fields only."""
from typing import Any, Dict

DEFAULTS: Dict[str, Any] = {
    "CLIENT_NAME": "Acme Relying Party",
    "HOME_JURISDICTION": "US",
    "DAILY_SESSION_QUOTA": 50,
    "GRANTED_REVIEW_CREDITS": 1,
    "SUBJECT_REF": "subj-1",
    "REMEDIATION_NOTE": "Vendor retrained the model on a balanced cohort sample.",
}


# --------------------------------------------------------------------------
# Clients
# --------------------------------------------------------------------------
def create_client_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["CLIENT_NAME"],
        "home_jurisdiction_code": DEFAULTS["HOME_JURISDICTION"],
        "biometric_retention_mode": "DELETE_ON_COMPLETE",
        "daily_session_quota": DEFAULTS["DAILY_SESSION_QUOTA"],
        "granted_review_credits": DEFAULTS["GRANTED_REVIEW_CREDITS"],
    }
    payload.update(overrides)
    return payload


def patch_client_payload(**overrides) -> dict:
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Method profiles — the canonical vendor catalogue used by the fixtures
# --------------------------------------------------------------------------
def create_method_profile_payload(**overrides) -> dict:
    payload = {
        "method_code": "DOCUMENT_SCAN",
        "vendor_code": "docv1",
        "assurance_weight": 45,
        "acceptance_floor_bps": 8000,
        "far_bps": 30,
        "frr_bps": 400,
        "strong_evidence": True,
        "cost_cents": 120,
    }
    payload.update(overrides)
    return payload


def document_scan_profile_payload(**overrides) -> dict:
    payload = create_method_profile_payload(
        method_code="DOCUMENT_SCAN",
        vendor_code="docv1",
        assurance_weight=45,
        acceptance_floor_bps=8000,
        far_bps=30,
        frr_bps=400,
        strong_evidence=True,
        cost_cents=120,
    )
    payload.update(overrides)
    return payload


def database_check_profile_payload(**overrides) -> dict:
    payload = create_method_profile_payload(
        method_code="DATABASE_CHECK",
        vendor_code="dbv1",
        assurance_weight=25,
        acceptance_floor_bps=6000,
        far_bps=80,
        frr_bps=600,
        strong_evidence=False,
        cost_cents=40,
    )
    payload.update(overrides)
    return payload


def knowledge_based_profile_payload(**overrides) -> dict:
    payload = create_method_profile_payload(
        method_code="KNOWLEDGE_BASED",
        vendor_code="kbav1",
        assurance_weight=15,
        acceptance_floor_bps=6000,
        far_bps=150,
        frr_bps=900,
        strong_evidence=False,
        cost_cents=20,
    )
    payload.update(overrides)
    return payload


def biometric_profile_payload(**overrides) -> dict:
    payload = create_method_profile_payload(
        method_code="BIOMETRIC_COMPARISON",
        vendor_code="biov1",
        assurance_weight=35,
        acceptance_floor_bps=7000,
        far_bps=20,
        frr_bps=500,
        strong_evidence=True,
        cost_cents=200,
    )
    payload.update(overrides)
    return payload


def vouching_profile_payload(**overrides) -> dict:
    payload = create_method_profile_payload(
        method_code="VOUCHING_ATTESTATION",
        vendor_code="vouv1",
        assurance_weight=30,
        acceptance_floor_bps=6000,
        far_bps=100,
        frr_bps=700,
        strong_evidence=False,
        cost_cents=60,
    )
    payload.update(overrides)
    return payload


FULL_BAND_ACCURACY_BPS = {
    "U13": 8500,
    "B13_15": 8800,
    "B16_17": 9100,
    "B18_20": 9400,
    "A21_PLUS": 9600,
}


def age_estimation_profile_payload(**overrides) -> dict:
    payload = create_method_profile_payload(
        method_code="AGE_ESTIMATION",
        vendor_code="agev1",
        assurance_weight=10,
        acceptance_floor_bps=5000,
        far_bps=200,
        frr_bps=800,
        strong_evidence=False,
        cost_cents=30,
        estimation_mae_months=18,
        band_accuracy_bps=dict(FULL_BAND_ACCURACY_BPS),
    )
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Verification policies
# --------------------------------------------------------------------------
def create_verification_policy_payload(client_id: str, **overrides) -> dict:
    payload = {
        "client_id": client_id,
        "policy_version": 1,
        "allowed_method_codes": ["DOCUMENT_SCAN"],
        "min_assurance_score": 60,
    }
    payload.update(overrides)
    return payload


def publish_policy_payload(expected_client_version: int) -> dict:
    return {"expected_client_version": expected_client_version}


# --------------------------------------------------------------------------
# Verification sessions
# --------------------------------------------------------------------------
def create_verification_session_payload(client_id: str, **overrides) -> dict:
    payload = {
        "client_id": client_id,
        "external_subject_ref": DEFAULTS["SUBJECT_REF"],
        "requested_assurance_tier": "STANDARD",
        "subject_jurisdiction_code": "US",
        "declared_transaction_value_cents": 0,
        "biometric_consent": False,
        "documentation_status": "STANDARD_DOCS",
    }
    payload.update(overrides)
    return payload


def create_method_attempt_payload(**overrides) -> dict:
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Evidence rows
# --------------------------------------------------------------------------
def create_document_capture_payload(**overrides) -> dict:
    payload = {
        "document_type": "PASSPORT",
        "required_feature_count": 16,
        "passed_feature_count": 16,
        "tamper_signal_count": 0,
        "mrz_checksum_valid": True,
    }
    payload.update(overrides)
    return payload


def create_liveness_check_payload(**overrides) -> dict:
    payload = {
        "capture_modality": "PASSIVE",
        "pad_score_bps": 9000,
        "match_score_bps": 9200,
    }
    payload.update(overrides)
    return payload


def database_evidence_payload(matched_field_count: int, total_field_count: int) -> dict:
    return {
        "matched_field_count": matched_field_count,
        "total_field_count": total_field_count,
    }


def knowledge_based_evidence_payload(correct_answer_count: int, question_count: int) -> dict:
    return {
        "correct_answer_count": correct_answer_count,
        "question_count": question_count,
    }


# --------------------------------------------------------------------------
# Age assurance results
# --------------------------------------------------------------------------
def estimation_result_payload(estimation_profile_id: str, estimated_age_months: int) -> dict:
    return {
        "method": "ESTIMATION",
        "estimation_profile_id": estimation_profile_id,
        "estimated_age_months": estimated_age_months,
    }


def verification_result_payload(date_of_birth: str) -> dict:
    return {"method": "VERIFICATION", "date_of_birth": date_of_birth}


# --------------------------------------------------------------------------
# Inclusion pathways
# --------------------------------------------------------------------------
def vouching_pathway_payload(voucher_reference: str = "voucher-1") -> dict:
    return {"pathway_type": "VOUCHING", "voucher_reference": voucher_reference}


def attestation_pathway_payload(attestation_document_ref: str = "attest-1") -> dict:
    return {
        "pathway_type": "ATTESTATION",
        "attestation_document_ref": attestation_document_ref,
    }


def pathway_decision_payload(action: str) -> dict:
    return {"action": action}


# --------------------------------------------------------------------------
# Manual review
# --------------------------------------------------------------------------
def assign_case_payload(assigned_reviewer_user_id: str) -> dict:
    return {"assigned_reviewer_user_id": assigned_reviewer_user_id}


def review_decision_payload(decision: str) -> dict:
    return {"decision": decision}


# --------------------------------------------------------------------------
# Bias testing
# --------------------------------------------------------------------------
def create_bias_audit_payload(method_profile_id: str, window_start: str, window_end: str) -> dict:
    return {
        "method_profile_id": method_profile_id,
        "window_start": window_start,
        "window_end": window_end,
    }


def create_cohort_metric_payload(
    cohort_code: str,
    attempt_count: int,
    false_reject_count: int,
    false_accept_count: int = 2,
) -> dict:
    return {
        "cohort_code": cohort_code,
        "attempt_count": attempt_count,
        "false_reject_count": false_reject_count,
        "false_accept_count": false_accept_count,
    }


def remediation_payload(expected_method_profile_version: int, **overrides) -> dict:
    payload = {
        "expected_method_profile_version": expected_method_profile_version,
        "remediation_note": DEFAULTS["REMEDIATION_NOTE"],
    }
    payload.update(overrides)
    return payload
