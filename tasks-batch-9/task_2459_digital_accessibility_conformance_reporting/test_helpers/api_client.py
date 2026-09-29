"""API client: one method per endpoint defined in the PRD (§4).

Every endpoint is mounted at the service root; there is no shared API prefix.
Every method returns the raw response so tests can assert status codes and error
envelopes.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed access to every endpoint of the Digital Accessibility Conformance
    API."""

    # ------------------------------------------------------------------
    # Standards and success criteria
    # ------------------------------------------------------------------
    def create_standard(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/standards", payload, headers)

    def get_standard(self, standard_id: str, headers=None):
        return self._request("GET", f"/standards/{standard_id}", headers=headers)

    def create_criterion(self, standard_id: str, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"/standards/{standard_id}/criteria", payload, headers)

    def list_criteria(self, standard_id: str, headers=None, params=None):
        return self._request(
            "GET", f"/standards/{standard_id}/criteria", headers=headers, params=params
        )

    def get_criterion(self, criterion_id: str, headers=None):
        return self._request("GET", f"/criteria/{criterion_id}", headers=headers)

    # ------------------------------------------------------------------
    # Products
    # ------------------------------------------------------------------
    def create_product(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/products", payload, headers)

    def get_product(self, product_id: str, headers=None):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def list_products(self, headers=None, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    def recompute_posture(self, product_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"/products/{product_id}/recompute-posture", payload, headers
        )

    # ------------------------------------------------------------------
    # Component inventory and design review
    # ------------------------------------------------------------------
    def create_component(self, product_id: str, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"/products/{product_id}/components", payload, headers)

    def list_components(self, product_id: str, headers=None, params=None):
        return self._request(
            "GET", f"/products/{product_id}/components", headers=headers, params=params
        )

    def get_component(self, component_id: str, headers=None):
        return self._request("GET", f"/components/{component_id}", headers=headers)

    def design_review(self, component_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"/components/{component_id}/design-review", payload, headers
        )

    # ------------------------------------------------------------------
    # Assistive-technology benches
    # ------------------------------------------------------------------
    def create_environment(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/test-environments", payload, headers)

    def get_environment(self, environment_id: str, headers=None):
        return self._request("GET", f"/test-environments/{environment_id}", headers=headers)

    # ------------------------------------------------------------------
    # Assessment runs
    # ------------------------------------------------------------------
    def create_run(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/assessment-runs", payload, headers)

    def get_run(self, run_id: str, headers=None):
        return self._request("GET", f"/assessment-runs/{run_id}", headers=headers)

    def list_runs(self, headers=None, params=None):
        return self._request("GET", "/assessment-runs", headers=headers, params=params)

    def complete_run(self, run_id: str, payload=None, headers=None):
        return self._request(
            "POST", f"/assessment-runs/{run_id}/complete", payload or {}, headers
        )

    def void_run(self, run_id: str, payload=None, headers=None):
        return self._request("POST", f"/assessment-runs/{run_id}/void", payload or {}, headers)

    # ------------------------------------------------------------------
    # Criterion assessments
    # ------------------------------------------------------------------
    def create_assessment(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/criterion-assessments", payload, headers)

    def get_assessment(self, assessment_id: str, headers=None):
        return self._request("GET", f"/criterion-assessments/{assessment_id}", headers=headers)

    def list_assessments(self, headers=None, params=None):
        return self._request("GET", "/criterion-assessments", headers=headers, params=params)

    def attest_assessment(self, assessment_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"/criterion-assessments/{assessment_id}/attest", payload, headers
        )

    # ------------------------------------------------------------------
    # Conformance reports
    # ------------------------------------------------------------------
    def create_report(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/conformance-reports", payload, headers)

    def get_report(self, report_id: str, headers=None):
        return self._request("GET", f"/conformance-reports/{report_id}", headers=headers)

    def list_reports(self, headers=None, params=None):
        return self._request("GET", "/conformance-reports", headers=headers, params=params)

    def submit_report(self, report_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"/conformance-reports/{report_id}/submit", payload, headers
        )

    def request_changes(self, report_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"/conformance-reports/{report_id}/request-changes", payload, headers
        )

    def approve_report(self, report_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"/conformance-reports/{report_id}/approve", payload, headers
        )

    def publish_report(self, report_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"/conformance-reports/{report_id}/publish", payload, headers
        )

    def withdraw_report(self, report_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"/conformance-reports/{report_id}/withdraw", payload, headers
        )

    # ------------------------------------------------------------------
    # Release trains and the remediation budget
    # ------------------------------------------------------------------
    def create_release_train(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/release-trains", payload, headers)

    def get_release_train(self, train_id: str, headers=None):
        return self._request("GET", f"/release-trains/{train_id}", headers=headers)

    def allocate_budget(self, train_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"/release-trains/{train_id}/allocate-budget", payload, headers
        )

    def deallocate_budget(self, train_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"/release-trains/{train_id}/deallocate-budget", payload, headers
        )

    # ------------------------------------------------------------------
    # Known issues
    # ------------------------------------------------------------------
    def create_known_issue(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/known-issues", payload, headers)

    def get_known_issue(self, issue_id: str, headers=None):
        return self._request("GET", f"/known-issues/{issue_id}", headers=headers)

    def list_known_issues(self, headers=None, params=None):
        return self._request("GET", "/known-issues", headers=headers, params=params)

    def triage_issue(self, issue_id: str, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"/known-issues/{issue_id}/triage", payload, headers)

    def board_review_issue(self, issue_id: str, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"/known-issues/{issue_id}/board-review", payload, headers)

    def commit_issue(self, issue_id: str, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"/known-issues/{issue_id}/commit", payload, headers)

    def resolve_issue(self, issue_id: str, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"/known-issues/{issue_id}/resolve", payload, headers)

    # ------------------------------------------------------------------
    # Procurement questionnaire responses
    # ------------------------------------------------------------------
    def create_questionnaire(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/questionnaire-responses", payload, headers)

    def get_questionnaire(self, questionnaire_id: str, headers=None):
        return self._request(
            "GET", f"/questionnaire-responses/{questionnaire_id}", headers=headers
        )

    def list_questionnaires(self, headers=None, params=None):
        return self._request("GET", "/questionnaire-responses", headers=headers, params=params)

    def submit_questionnaire(self, questionnaire_id: str, payload=None, headers=None):
        return self._request(
            "POST",
            f"/questionnaire-responses/{questionnaire_id}/submit",
            payload or {},
            headers,
        )

    def attest_questionnaire(self, questionnaire_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"/questionnaire-responses/{questionnaire_id}/attest", payload, headers
        )

    def revise_questionnaire(self, questionnaire_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", f"/questionnaire-responses/{questionnaire_id}/revise", payload, headers
        )

    # ------------------------------------------------------------------
    # Complaints and accommodation requests
    # ------------------------------------------------------------------
    def create_complaint(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/complaints", payload, headers)

    def get_complaint(self, complaint_id: str, headers=None):
        return self._request("GET", f"/complaints/{complaint_id}", headers=headers)

    def list_complaints(self, headers=None, params=None):
        return self._request("GET", "/complaints", headers=headers, params=params)

    def triage_complaint(self, complaint_id: str, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"/complaints/{complaint_id}/triage", payload, headers)

    def link_issue(self, complaint_id: str, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"/complaints/{complaint_id}/link-issue", payload, headers)

    def fulfill_accommodation(self, complaint_id: str, payload=None, headers=None):
        return self._request(
            "POST", f"/complaints/{complaint_id}/fulfill-accommodation", payload or {}, headers
        )

    def close_complaint(self, complaint_id: str, payload: Dict[str, Any], headers=None):
        return self._request("POST", f"/complaints/{complaint_id}/close", payload, headers)

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601: str, headers=None):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
