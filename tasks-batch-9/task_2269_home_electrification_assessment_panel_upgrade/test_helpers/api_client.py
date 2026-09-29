"""Typed HTTP client — one method per endpoint of PRD §4.

Every method returns the raw `requests.Response` so tests can assert on status
codes and error envelopes themselves. The service is mounted at the root path,
so every collection is addressed as a top-level path.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for the Home Electrification Rebates API."""

    # ------------------------------------------------------------------ #
    # Programs
    # ------------------------------------------------------------------ #

    def create_program(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/programs", payload, headers)

    def get_program(self, program_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/programs/{program_id}", None, headers)

    def list_programs(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/programs", params, headers)

    def set_program_status(
        self, program_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/programs/{program_id}/status", payload, headers)

    def sweep_program(
        self, program_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("POST", f"/programs/{program_id}/sweep", payload or {}, headers)

    # ------------------------------------------------------------------ #
    # Measure catalog
    # ------------------------------------------------------------------ #

    def create_catalog_item(
        self, program_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/programs/{program_id}/measure-catalog-items", payload, headers
        )

    def list_catalog_items(
        self, program_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/programs/{program_id}/measure-catalog-items", params, headers
        )

    def retire_catalog_item(
        self,
        program_id: str,
        item_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/programs/{program_id}/measure-catalog-items/{item_id}/retirement",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------ #
    # Program-scoped population listings
    # ------------------------------------------------------------------ #

    def list_program_households(
        self, program_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"/programs/{program_id}/households", params, headers)

    def list_program_contractors(
        self, program_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"/programs/{program_id}/contractors", params, headers)

    def list_program_inspectors(
        self, program_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"/programs/{program_id}/inspectors", params, headers)

    # ------------------------------------------------------------------ #
    # Households and income verification
    # ------------------------------------------------------------------ #

    def create_household(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/households", payload, headers)

    def get_household(self, household_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/households/{household_id}", None, headers)

    def create_income_verification(
        self, household_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/households/{household_id}/income-verifications", payload, headers
        )

    def list_income_verifications(
        self, household_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/households/{household_id}/income-verifications", params, headers
        )

    def verify_income_verification(
        self, verification_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/income-verifications/{verification_id}/verify", payload, headers
        )

    # ------------------------------------------------------------------ #
    # Contractors
    # ------------------------------------------------------------------ #

    def create_contractor(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/contractors", payload, headers)

    def get_contractor(self, contractor_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/contractors/{contractor_id}", None, headers)

    def decide_contractor_enrollment(
        self, contractor_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/contractors/{contractor_id}/enrollment-decision", payload, headers
        )

    def set_contractor_suspension(
        self, contractor_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/contractors/{contractor_id}/suspension", payload, headers
        )

    def get_contractor_quality_review(
        self, contractor_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/contractors/{contractor_id}/quality-review", None, headers)

    # ------------------------------------------------------------------ #
    # Inspectors
    # ------------------------------------------------------------------ #

    def create_inspector(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/inspectors", payload, headers)

    def get_inspector(self, inspector_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/inspectors/{inspector_id}", None, headers)

    # ------------------------------------------------------------------ #
    # Assessments
    # ------------------------------------------------------------------ #

    def create_assessment(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/assessments", payload, headers)

    def get_assessment(self, assessment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/assessments/{assessment_id}", None, headers)

    def list_assessments(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/assessments", params, headers)

    def list_eligible_measures(
        self, assessment_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/assessments/{assessment_id}/eligible-measures", params, headers
        )

    def review_assessment(
        self, assessment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/assessments/{assessment_id}/approve", payload, headers)

    # ------------------------------------------------------------------ #
    # Rebate projects
    # ------------------------------------------------------------------ #

    def create_rebate_project(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/rebate-projects", payload, headers)

    def get_rebate_project(self, project_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/rebate-projects/{project_id}", None, headers)

    def list_rebate_projects(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/rebate-projects", params, headers)

    def list_project_measures(
        self, project_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"/rebate-projects/{project_id}/measures", params, headers)

    def submit_rebate_project(
        self, project_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/rebate-projects/{project_id}/submit", payload or {}, headers
        )

    def review_rebate_project(
        self, project_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/rebate-projects/{project_id}/review", payload, headers)

    def get_incentive_quote(
        self, project_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/rebate-projects/{project_id}/incentive-quote", params, headers
        )

    def create_reservation(
        self, project_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/rebate-projects/{project_id}/reservations", payload, headers
        )

    def report_installation(
        self, project_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/rebate-projects/{project_id}/installation", payload, headers
        )

    def create_stacking_declaration(
        self, project_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/rebate-projects/{project_id}/stacking-declarations", payload, headers
        )

    def list_stacking_declarations(
        self, project_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/rebate-projects/{project_id}/stacking-declarations", params, headers
        )

    def open_remediation(
        self, project_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/rebate-projects/{project_id}/remediation", payload or {}, headers
        )

    def disburse_payment(
        self, project_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/rebate-projects/{project_id}/payment", payload or {}, headers
        )

    # ------------------------------------------------------------------ #
    # Reservations
    # ------------------------------------------------------------------ #

    def get_reservation(self, reservation_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/reservations/{reservation_id}", None, headers)

    def list_reservations(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/reservations", params, headers)

    def create_reservation_extension(
        self, reservation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/reservations/{reservation_id}/extensions", payload, headers
        )

    # ------------------------------------------------------------------ #
    # Inspections
    # ------------------------------------------------------------------ #

    def create_inspection(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/inspections", payload, headers)

    def get_inspection(self, inspection_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/inspections/{inspection_id}", None, headers)

    def list_inspections(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/inspections", params, headers)

    def record_inspection_result(
        self, inspection_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/inspections/{inspection_id}/result", payload, headers)

    def cancel_inspection(
        self, inspection_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/inspections/{inspection_id}/cancellation", payload or {}, headers
        )

    # ------------------------------------------------------------------ #
    # Clawback actions
    # ------------------------------------------------------------------ #

    def get_clawback_action(self, action_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/clawback-actions/{action_id}", None, headers)

    def list_clawback_actions(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/clawback-actions", params, headers)

    # ------------------------------------------------------------------ #
    # Logical clock (§2.5)
    # ------------------------------------------------------------------ #

    def set_clock(self, current_utc: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )


__all__ = ["ApiClient"]
