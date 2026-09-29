"""HTTP client with one method per endpoint in PRD §4.

All paths are mounted at the server root — this API declares no path prefix — so
the paths below are exactly the ones the PRD's endpoint table lists.

Every method returns the raw ``requests.Response`` so that tests can assert on
status codes as well as bodies.
"""

from typing import Any, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed surface over the 50 endpoints the PRD declares."""

    # ─── Logical clock (PRD §2.5) ──────────────────────────────────────────

    def set_clock(self, current_utc: str, headers: Optional[dict] = None) -> requests.Response:
        """Set the server's logical clock. Moving the clock performs no transitions."""
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # ─── Model assets (PRD §3.1) ───────────────────────────────────────────

    def create_model_asset(self, payload: dict, headers: Optional[dict] = None) -> requests.Response:
        return self._request("POST", "/model-assets", payload, headers)

    def list_model_assets(
        self, headers: Optional[dict] = None, **params: Any
    ) -> requests.Response:
        return self._request("GET", "/model-assets", params or None, headers)

    def get_model_asset(self, asset_id: str, headers: Optional[dict] = None) -> requests.Response:
        return self._request("GET", f"/model-assets/{asset_id}", None, headers)

    def update_model_asset(
        self, asset_id: str, payload: dict, headers: Optional[dict] = None
    ) -> requests.Response:
        return self._request("PATCH", f"/model-assets/{asset_id}", payload, headers)

    def approve_asset_for_use(
        self, asset_id: str, payload: Optional[dict] = None, headers: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/model-assets/{asset_id}/approve-for-use", payload or {}, headers
        )

    def list_asset_model_bindings(
        self, asset_id: str, headers: Optional[dict] = None, **params: Any
    ) -> requests.Response:
        return self._request(
            "GET", f"/model-assets/{asset_id}/model-bindings", params or None, headers
        )

    def create_vendor_assessment(
        self, asset_id: str, payload: dict, headers: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/model-assets/{asset_id}/vendor-assessments", payload, headers
        )

    def list_vendor_assessments(
        self, asset_id: str, headers: Optional[dict] = None, **params: Any
    ) -> requests.Response:
        return self._request(
            "GET", f"/model-assets/{asset_id}/vendor-assessments", params or None, headers
        )

    def decide_vendor_assessment(
        self, assessment_id: str, payload: dict, headers: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/vendor-assessments/{assessment_id}/decide", payload, headers
        )

    # ─── Use case intake and classification (PRD §3.2) ─────────────────────

    def create_use_case(self, payload: dict, headers: Optional[dict] = None) -> requests.Response:
        return self._request("POST", "/use-cases", payload, headers)

    def list_use_cases(
        self, headers: Optional[dict] = None, **params: Any
    ) -> requests.Response:
        return self._request("GET", "/use-cases", params or None, headers)

    def get_use_case(self, use_case_id: str, headers: Optional[dict] = None) -> requests.Response:
        return self._request("GET", f"/use-cases/{use_case_id}", None, headers)

    def update_use_case(
        self, use_case_id: str, payload: dict, headers: Optional[dict] = None
    ) -> requests.Response:
        return self._request("PATCH", f"/use-cases/{use_case_id}", payload, headers)

    def classify_use_case(
        self, use_case_id: str, payload: dict, headers: Optional[dict] = None
    ) -> requests.Response:
        return self._request("POST", f"/use-cases/{use_case_id}/classify", payload, headers)

    def list_classification_snapshots(
        self, use_case_id: str, headers: Optional[dict] = None, **params: Any
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/use-cases/{use_case_id}/classification-snapshots",
            params or None,
            headers,
        )

    # ─── Review gates (PRD §3.3) ───────────────────────────────────────────

    def list_review_gates(
        self, use_case_id: str, headers: Optional[dict] = None, **params: Any
    ) -> requests.Response:
        return self._request(
            "GET", f"/use-cases/{use_case_id}/review-gates", params or None, headers
        )

    def start_gate_review(
        self, gate_id: str, payload: Optional[dict] = None, headers: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/review-gates/{gate_id}/start-review", payload or {}, headers
        )

    def issue_gate_conditions(
        self, gate_id: str, payload: dict, headers: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/review-gates/{gate_id}/issue-conditions", payload, headers
        )

    def clear_gate(
        self, gate_id: str, payload: Optional[dict] = None, headers: Optional[dict] = None
    ) -> requests.Response:
        return self._request("POST", f"/review-gates/{gate_id}/clear", payload or {}, headers)

    def reopen_gate(
        self, gate_id: str, payload: Optional[dict] = None, headers: Optional[dict] = None
    ) -> requests.Response:
        return self._request("POST", f"/review-gates/{gate_id}/reopen", payload or {}, headers)

    # ─── Model bindings (PRD §3.4) ─────────────────────────────────────────

    def create_model_binding(
        self, use_case_id: str, payload: dict, headers: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/use-cases/{use_case_id}/model-bindings", payload, headers
        )

    def list_model_bindings(
        self, use_case_id: str, headers: Optional[dict] = None, **params: Any
    ) -> requests.Response:
        return self._request(
            "GET", f"/use-cases/{use_case_id}/model-bindings", params or None, headers
        )

    # ─── Oversight designs (PRD §3.5) ──────────────────────────────────────

    def create_oversight_design(
        self, use_case_id: str, payload: dict, headers: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/use-cases/{use_case_id}/oversight-designs", payload, headers
        )

    def list_oversight_designs(
        self, use_case_id: str, headers: Optional[dict] = None, **params: Any
    ) -> requests.Response:
        return self._request(
            "GET", f"/use-cases/{use_case_id}/oversight-designs", params or None, headers
        )

    def decide_oversight_design(
        self, design_id: str, payload: dict, headers: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/oversight-designs/{design_id}/decide", payload, headers
        )

    # ─── Test evaluations (PRD §3.4) ───────────────────────────────────────

    def create_test_evaluation(
        self, payload: dict, headers: Optional[dict] = None
    ) -> requests.Response:
        return self._request("POST", "/test-evaluations", payload, headers)

    def list_test_evaluations(
        self, headers: Optional[dict] = None, **params: Any
    ) -> requests.Response:
        return self._request("GET", "/test-evaluations", params or None, headers)

    def get_test_evaluation(
        self, evaluation_id: str, headers: Optional[dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/test-evaluations/{evaluation_id}", None, headers)

    def complete_test_evaluation(
        self, evaluation_id: str, payload: dict, headers: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/test-evaluations/{evaluation_id}/complete", payload, headers
        )

    # ─── Disclosure notices (PRD §3.6) ─────────────────────────────────────

    def create_disclosure_notice(
        self, use_case_id: str, payload: dict, headers: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/use-cases/{use_case_id}/disclosure-notices", payload, headers
        )

    def list_disclosure_notices(
        self, use_case_id: str, headers: Optional[dict] = None, **params: Any
    ) -> requests.Response:
        return self._request(
            "GET", f"/use-cases/{use_case_id}/disclosure-notices", params or None, headers
        )

    def withdraw_disclosure_notice(
        self, notice_id: str, payload: Optional[dict] = None, headers: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/disclosure-notices/{notice_id}/withdraw", payload or {}, headers
        )

    # ─── Approval and revocation (PRD §3.7) ────────────────────────────────

    def approve_use_case(
        self, use_case_id: str, payload: dict, headers: Optional[dict] = None
    ) -> requests.Response:
        return self._request("POST", f"/use-cases/{use_case_id}/approve", payload, headers)

    def revoke_use_case(
        self, use_case_id: str, payload: Optional[dict] = None, headers: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/use-cases/{use_case_id}/revoke", payload or {}, headers
        )

    def complete_reassessment(
        self, use_case_id: str, payload: dict, headers: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/use-cases/{use_case_id}/complete-reassessment", payload, headers
        )

    def list_ledger_entries(
        self, use_case_id: str, headers: Optional[dict] = None, **params: Any
    ) -> requests.Response:
        return self._request(
            "GET", f"/use-cases/{use_case_id}/ledger-entries", params or None, headers
        )

    # ─── Monitoring incidents (PRD §3.8) ───────────────────────────────────

    def create_monitoring_incident(
        self, payload: dict, headers: Optional[dict] = None
    ) -> requests.Response:
        return self._request("POST", "/monitoring-incidents", payload, headers)

    def list_monitoring_incidents(
        self, headers: Optional[dict] = None, **params: Any
    ) -> requests.Response:
        return self._request("GET", "/monitoring-incidents", params or None, headers)

    def get_monitoring_incident(
        self, incident_id: str, headers: Optional[dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/monitoring-incidents/{incident_id}", None, headers)

    def contain_incident(
        self, incident_id: str, payload: Optional[dict] = None, headers: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/monitoring-incidents/{incident_id}/contain", payload or {}, headers
        )

    def resolve_incident(
        self, incident_id: str, payload: Optional[dict] = None, headers: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/monitoring-incidents/{incident_id}/resolve", payload or {}, headers
        )

    # ─── Shadow deployments (PRD §3.9) ─────────────────────────────────────

    def create_shadow_deployment(
        self, payload: dict, headers: Optional[dict] = None
    ) -> requests.Response:
        return self._request("POST", "/shadow-deployments", payload, headers)

    def list_shadow_deployments(
        self, headers: Optional[dict] = None, **params: Any
    ) -> requests.Response:
        return self._request("GET", "/shadow-deployments", params or None, headers)

    def get_shadow_deployment(
        self, shadow_id: str, headers: Optional[dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/shadow-deployments/{shadow_id}", None, headers)

    def link_shadow_deployment(
        self, shadow_id: str, payload: dict, headers: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/shadow-deployments/{shadow_id}/link", payload, headers
        )

    def grant_shadow_grace(
        self, shadow_id: str, payload: dict, headers: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/shadow-deployments/{shadow_id}/grant-grace", payload, headers
        )

    def retire_shadow_deployment(
        self, shadow_id: str, payload: Optional[dict] = None, headers: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/shadow-deployments/{shadow_id}/retire", payload or {}, headers
        )

    # ─── Reconciliation and sweep (PRD §2.11, §3.9) ────────────────────────

    def get_inventory_summary(
        self, headers: Optional[dict] = None, **params: Any
    ) -> requests.Response:
        return self._request("GET", "/inventory-summary", params or None, headers)

    def run_governance_sweep(
        self, payload: Optional[dict] = None, headers: Optional[dict] = None
    ) -> requests.Response:
        return self._request("POST", "/_ops/governance-sweep", payload or {}, headers)


# Module-level client the suite's ``api`` fixture hands out. The base URL comes
# from API_BASE_URL, which the runner sets.
api_client = ApiClient()
