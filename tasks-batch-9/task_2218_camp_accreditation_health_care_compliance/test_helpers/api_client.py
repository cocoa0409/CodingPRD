"""One method per endpoint of the camp accreditation and health compliance API."""

from __future__ import annotations

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX, CLOCK_PATH

Headers = Optional[Dict[str, str]]
Payload = Optional[Dict[str, Any]]


class ApiClient(GenericApiClient):
    """Thin transport wrapper: every method returns the raw response."""

    # ------------------------------------------------------------------
    # low level
    # ------------------------------------------------------------------
    def patch(self, path: str, json: Payload = None, headers: Headers = None):
        return self._request("PATCH", path, payload=json, headers=headers)

    # ------------------------------------------------------------------
    # logical clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601: str, headers: Headers = None) -> requests.Response:
        return self._request("POST", CLOCK_PATH, {"to_iso8601": to_iso8601}, headers)

    def set_clock_raw(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", CLOCK_PATH, payload, headers)

    # ------------------------------------------------------------------
    # camps
    # ------------------------------------------------------------------
    def create_camp(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/camps", payload, headers)

    def get_camp(self, camp_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/camps/{camp_id}", None, headers)

    def list_camps(self, params: Payload = None, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/camps", params, headers)

    def get_camp_risk_index(self, camp_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/camps/{camp_id}/risk-index", None, headers)

    def patch_state_license(
        self, camp_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "PATCH", f"{API_PREFIX}/camps/{camp_id}/state-license", payload, headers
        )

    def patch_health_center(
        self, camp_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "PATCH", f"{API_PREFIX}/camps/{camp_id}/health-center", payload, headers
        )

    # ------------------------------------------------------------------
    # standards editions and standards
    # ------------------------------------------------------------------
    def create_standards_set(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/standards-sets", payload, headers)

    def get_standards_set(self, set_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/standards-sets/{set_id}", None, headers)

    def list_standards_sets(
        self, params: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/standards-sets", params, headers)

    def publish_standards_set(self, set_id: str, headers: Headers = None) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/standards-sets/{set_id}/publish", {}, headers
        )

    def create_standard(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/standards", payload, headers)

    def get_standard(self, standard_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/standards/{standard_id}", None, headers)

    def list_standards(self, params: Payload = None, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/standards", params, headers)

    # ------------------------------------------------------------------
    # cycles
    # ------------------------------------------------------------------
    def create_cycle(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/cycles", payload, headers)

    def get_cycle(self, cycle_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/cycles/{cycle_id}", None, headers)

    def list_cycles(self, params: Payload = None, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/cycles", params, headers)

    def get_compliance_summary(self, cycle_id: str, headers: Headers = None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/cycles/{cycle_id}/compliance-summary", None, headers
        )

    def submit_self_assessment(self, cycle_id: str, headers: Headers = None) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/cycles/{cycle_id}/submit-self-assessment", {}, headers
        )

    def issue_decision(self, cycle_id: str, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/cycles/{cycle_id}/decision", {}, headers)

    # ------------------------------------------------------------------
    # standard evaluations
    # ------------------------------------------------------------------
    def get_evaluation(self, evaluation_id: str, headers: Headers = None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/standard-evaluations/{evaluation_id}", None, headers
        )

    def list_evaluations(
        self, params: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/standard-evaluations", params, headers)

    def patch_self_assessment(
        self, evaluation_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "PATCH",
            f"{API_PREFIX}/standard-evaluations/{evaluation_id}/self-assessment",
            payload,
            headers,
        )

    def patch_visitor_score(
        self, evaluation_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "PATCH",
            f"{API_PREFIX}/standard-evaluations/{evaluation_id}/visitor-score",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # written plans
    # ------------------------------------------------------------------
    def create_written_plan(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/written-plans", payload, headers)

    def get_written_plan(self, plan_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/written-plans/{plan_id}", None, headers)

    def list_written_plans(
        self, params: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/written-plans", params, headers)

    def review_written_plan(
        self, plan_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/written-plans/{plan_id}/review", payload, headers
        )

    # ------------------------------------------------------------------
    # visitors
    # ------------------------------------------------------------------
    def create_visitor(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/visitors", payload, headers)

    def get_visitor(self, visitor_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/visitors/{visitor_id}", None, headers)

    def list_visitors(self, params: Payload = None, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/visitors", params, headers)

    def deactivate_visitor(
        self, visitor_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/visitors/{visitor_id}/deactivate", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # visits and team seats
    # ------------------------------------------------------------------
    def create_visit(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/visits", payload, headers)

    def get_visit(self, visit_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/visits/{visit_id}", None, headers)

    def list_visits(self, params: Payload = None, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/visits", params, headers)

    def schedule_visit(self, visit_id: str, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/visits/{visit_id}/schedule", {}, headers)

    def start_visit(self, visit_id: str, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/visits/{visit_id}/start", {}, headers)

    def finalize_scoring(self, visit_id: str, headers: Headers = None) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/visits/{visit_id}/finalize-scoring", {}, headers
        )

    def create_visit_assignment(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/visit-assignments", payload, headers)

    def get_visit_assignment(
        self, assignment_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/visit-assignments/{assignment_id}", None, headers
        )

    def list_visit_assignments(
        self, params: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/visit-assignments", params, headers)

    def withdraw_visit_assignment(
        self, assignment_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/visit-assignments/{assignment_id}/withdraw",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # deficiencies
    # ------------------------------------------------------------------
    def get_deficiency(self, deficiency_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/deficiencies/{deficiency_id}", None, headers)

    def list_deficiencies(
        self, params: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/deficiencies", params, headers)

    def file_correction_plan(
        self, deficiency_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/deficiencies/{deficiency_id}/correction-plan",
            payload,
            headers,
        )

    def review_deficiency(
        self, deficiency_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/deficiencies/{deficiency_id}/review", payload, headers
        )

    # ------------------------------------------------------------------
    # medication administration records
    # ------------------------------------------------------------------
    def create_medication_record(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/medication-records", payload, headers)

    def get_medication_record(self, record_id: str, headers: Headers = None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/medication-records/{record_id}", None, headers
        )

    def list_medication_records(
        self, params: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/medication-records", params, headers)

    def void_medication_record(
        self, record_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/medication-records/{record_id}/void", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # annual reports and incident disclosures
    # ------------------------------------------------------------------
    def create_annual_report(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/annual-reports", payload, headers)

    def get_annual_report(self, report_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/annual-reports/{report_id}", None, headers)

    def list_annual_reports(
        self, params: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/annual-reports", params, headers)

    def submit_annual_report(
        self, report_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/annual-reports/{report_id}/submit", payload, headers
        )

    def review_annual_report(
        self, report_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/annual-reports/{report_id}/review", payload, headers
        )

    def create_incident_disclosure(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/incident-disclosures", payload, headers)

    def get_incident_disclosure(
        self, disclosure_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/incident-disclosures/{disclosure_id}", None, headers
        )

    def list_incident_disclosures(
        self, params: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/incident-disclosures", params, headers)
