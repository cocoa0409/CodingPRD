"""API client: one method per endpoint defined in the PRD.

Every business resource is mounted under ``/idv``; the logical-clock control
endpoint lives outside that prefix at ``/_clock/set_current_utc``.
"""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

IDV = "/idv"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, current_utc: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers=headers
        )

    # ------------------------------------------------------------------
    # Clients
    # ------------------------------------------------------------------
    def create_client(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{IDV}/clients", payload, headers=headers)

    def patch_client(self, client_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"{IDV}/clients/{client_id}", payload, headers=headers)

    def get_client(self, client_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{IDV}/clients/{client_id}", headers=headers)

    # ------------------------------------------------------------------
    # Method profiles
    # ------------------------------------------------------------------
    def create_method_profile(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{IDV}/method-profiles", payload, headers=headers)

    def get_method_profile(self, profile_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{IDV}/method-profiles/{profile_id}", headers=headers)

    def list_profile_bias_audits(
        self, profile_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{IDV}/method-profiles/{profile_id}/bias-audits", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Verification policies
    # ------------------------------------------------------------------
    def create_verification_policy(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{IDV}/verification-policies", payload, headers=headers)

    def publish_verification_policy(
        self, policy_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{IDV}/verification-policies/{policy_id}/publish", payload, headers=headers
        )

    def get_verification_policy(self, policy_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{IDV}/verification-policies/{policy_id}", headers=headers)

    def list_verification_policies(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{IDV}/verification-policies", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Verification sessions
    # ------------------------------------------------------------------
    def create_verification_session(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{IDV}/verification-sessions", payload, headers=headers)

    def get_verification_session(self, session_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{IDV}/verification-sessions/{session_id}", headers=headers)

    def list_verification_sessions(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{IDV}/verification-sessions", headers=headers, params=params
        )

    def create_method_attempt(
        self, session_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{IDV}/verification-sessions/{session_id}/method-attempts", payload,
            headers=headers,
        )

    def create_age_assurance_result(
        self, session_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{IDV}/verification-sessions/{session_id}/age-assurance-results", payload,
            headers=headers,
        )

    def list_age_assurance_results(
        self, session_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{IDV}/verification-sessions/{session_id}/age-assurance-results",
            headers=headers, params=params,
        )

    def step_up_session(self, session_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request(
            "POST", f"{IDV}/verification-sessions/{session_id}/step-up", payload or {},
            headers=headers,
        )

    def complete_session(self, session_id: str, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request(
            "POST", f"{IDV}/verification-sessions/{session_id}/complete", payload or {},
            headers=headers,
        )

    def create_alternative_pathway(
        self, session_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{IDV}/verification-sessions/{session_id}/alternative-pathways", payload,
            headers=headers,
        )

    def list_alternative_pathways(
        self, session_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{IDV}/verification-sessions/{session_id}/alternative-pathways",
            headers=headers, params=params,
        )

    def list_biometric_templates(
        self, session_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{IDV}/verification-sessions/{session_id}/biometric-templates",
            headers=headers, params=params,
        )

    def list_manual_review_cases(
        self, session_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{IDV}/verification-sessions/{session_id}/manual-review-cases",
            headers=headers, params=params,
        )

    def list_audit_events(
        self, session_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{IDV}/verification-sessions/{session_id}/audit-events",
            headers=headers, params=params,
        )

    # ------------------------------------------------------------------
    # Method attempts and evidence
    # ------------------------------------------------------------------
    def create_document_capture(
        self, attempt_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{IDV}/method-attempts/{attempt_id}/document-captures", payload,
            headers=headers,
        )

    def list_document_captures(
        self, attempt_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{IDV}/method-attempts/{attempt_id}/document-captures",
            headers=headers, params=params,
        )

    def create_liveness_check(
        self, attempt_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{IDV}/method-attempts/{attempt_id}/liveness-checks", payload,
            headers=headers,
        )

    def list_liveness_checks(
        self, attempt_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{IDV}/method-attempts/{attempt_id}/liveness-checks",
            headers=headers, params=params,
        )

    def create_data_evidence(
        self, attempt_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{IDV}/method-attempts/{attempt_id}/data-evidence", payload, headers=headers
        )

    def finalize_method_attempt(
        self, attempt_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{IDV}/method-attempts/{attempt_id}/finalize", payload or {}, headers=headers
        )

    def get_method_attempt(self, attempt_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{IDV}/method-attempts/{attempt_id}", headers=headers)

    def list_method_attempts(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{IDV}/method-attempts", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Inclusion pathways
    # ------------------------------------------------------------------
    def decide_alternative_pathway(
        self, pathway_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{IDV}/alternative-pathways/{pathway_id}/decision", payload, headers=headers
        )

    # ------------------------------------------------------------------
    # Manual review
    # ------------------------------------------------------------------
    def assign_manual_review_case(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{IDV}/manual-review-cases/{case_id}/assign", payload, headers=headers
        )

    def decide_manual_review_case(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{IDV}/manual-review-cases/{case_id}/decision", payload, headers=headers
        )

    # ------------------------------------------------------------------
    # Bias testing programme
    # ------------------------------------------------------------------
    def create_bias_audit(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{IDV}/bias-audits", payload, headers=headers)

    def get_bias_audit(self, audit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{IDV}/bias-audits/{audit_id}", headers=headers)

    def create_cohort_metric(
        self, audit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{IDV}/bias-audits/{audit_id}/cohort-metrics", payload, headers=headers
        )

    def list_cohort_metrics(
        self, audit_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{IDV}/bias-audits/{audit_id}/cohort-metrics", headers=headers, params=params
        )

    def evaluate_bias_audit(
        self, audit_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{IDV}/bias-audits/{audit_id}/evaluate", payload or {}, headers=headers
        )

    def remediate_bias_audit(
        self, audit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{IDV}/bias-audits/{audit_id}/remediation", payload, headers=headers
        )

    # ------------------------------------------------------------------
    # Operations sweep
    # ------------------------------------------------------------------
    def run_retention_sweep(self, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request(
            "POST", f"{IDV}/retention-sweeps", payload or {}, headers=headers
        )


api_client = ApiClient()
