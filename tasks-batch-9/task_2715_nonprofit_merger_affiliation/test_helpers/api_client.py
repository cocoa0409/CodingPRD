"""Typed API client: one method per endpoint declared by the PRD.

Every method returns the raw requests.Response so tests can assert on status
codes as well as on the response envelope.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

Json = Dict[str, Any]


class ApiClient(GenericApiClient):
    """Client covering every endpoint of the nonprofit restructuring API."""

    # ------------------------------------------------------------------
    # Organizations
    # ------------------------------------------------------------------
    def create_organization(self, payload: Json, headers: Json) -> requests.Response:
        return self._request("POST", "/organizations", payload, headers)

    def get_organization(self, org_id: str, headers: Json) -> requests.Response:
        return self._request("GET", f"/organizations/{org_id}", None, headers)

    def list_organizations(
        self, headers: Json, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", "/organizations", params, headers)

    def financial_restatement(
        self, org_id: str, payload: Json, headers: Json
    ) -> requests.Response:
        return self._request(
            "POST", f"/organizations/{org_id}/financial-restatement", payload, headers
        )

    def list_organization_programs(
        self, org_id: str, headers: Json, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", f"/organizations/{org_id}/programs", params, headers)

    # ------------------------------------------------------------------
    # Programs
    # ------------------------------------------------------------------
    def create_program(self, payload: Json, headers: Json) -> requests.Response:
        return self._request("POST", "/programs", payload, headers)

    def continuity_decision(
        self, program_id: str, payload: Json, headers: Json
    ) -> requests.Response:
        return self._request(
            "POST", f"/programs/{program_id}/continuity-decision", payload, headers
        )

    # ------------------------------------------------------------------
    # Restructurings
    # ------------------------------------------------------------------
    def create_restructuring(self, payload: Json, headers: Json) -> requests.Response:
        return self._request("POST", "/restructurings", payload, headers)

    def get_restructuring(self, deal_id: str, headers: Json) -> requests.Response:
        return self._request("GET", f"/restructurings/{deal_id}", None, headers)

    def list_restructurings(
        self, headers: Json, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", "/restructurings", params, headers)

    def select_structure(
        self, deal_id: str, payload: Json, headers: Json
    ) -> requests.Response:
        return self._request(
            "POST", f"/restructurings/{deal_id}/select-structure", payload, headers
        )

    def consummate(
        self, deal_id: str, payload: Optional[Json], headers: Json
    ) -> requests.Response:
        return self._request(
            "POST", f"/restructurings/{deal_id}/consummate", payload or {}, headers
        )

    def abandon(
        self, deal_id: str, payload: Optional[Json], headers: Json
    ) -> requests.Response:
        return self._request(
            "POST", f"/restructurings/{deal_id}/abandon", payload or {}, headers
        )

    def get_dossier(self, deal_id: str, headers: Json) -> requests.Response:
        return self._request("GET", f"/restructurings/{deal_id}/dossier", None, headers)

    # ------------------------------------------------------------------
    # Deal-scoped list reads
    # ------------------------------------------------------------------
    def list_deal_alignment_assessments(
        self, deal_id: str, headers: Json, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/restructurings/{deal_id}/alignment-assessments", params, headers
        )

    def list_deal_letters_of_intent(
        self, deal_id: str, headers: Json, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/restructurings/{deal_id}/letters-of-intent", params, headers
        )

    def list_deal_diligence_requests(
        self, deal_id: str, headers: Json, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/restructurings/{deal_id}/diligence-requests", params, headers
        )

    def list_deal_board_approvals(
        self, deal_id: str, headers: Json, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/restructurings/{deal_id}/board-approvals", params, headers
        )

    def list_deal_ag_filings(
        self, deal_id: str, headers: Json, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/restructurings/{deal_id}/ag-filings", params, headers
        )

    def list_deal_restricted_funds(
        self, deal_id: str, headers: Json, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/restructurings/{deal_id}/restricted-funds", params, headers
        )

    # ------------------------------------------------------------------
    # Alignment assessments
    # ------------------------------------------------------------------
    def create_alignment_assessment(
        self, payload: Json, headers: Json
    ) -> requests.Response:
        return self._request("POST", "/alignment-assessments", payload, headers)

    # ------------------------------------------------------------------
    # Letters of intent
    # ------------------------------------------------------------------
    def create_letter_of_intent(self, payload: Json, headers: Json) -> requests.Response:
        return self._request("POST", "/letters-of-intent", payload, headers)

    def counter_letter_of_intent(
        self, loi_id: str, payload: Json, headers: Json
    ) -> requests.Response:
        return self._request(
            "POST", f"/letters-of-intent/{loi_id}/counter", payload, headers
        )

    def revise_letter_of_intent(
        self, loi_id: str, payload: Json, headers: Json
    ) -> requests.Response:
        return self._request(
            "POST", f"/letters-of-intent/{loi_id}/revise", payload, headers
        )

    def execute_letter_of_intent(
        self, loi_id: str, payload: Optional[Json], headers: Json
    ) -> requests.Response:
        return self._request(
            "POST", f"/letters-of-intent/{loi_id}/execute", payload or {}, headers
        )

    def withdraw_letter_of_intent(
        self, loi_id: str, payload: Optional[Json], headers: Json
    ) -> requests.Response:
        return self._request(
            "POST", f"/letters-of-intent/{loi_id}/withdraw", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Diligence requests
    # ------------------------------------------------------------------
    def create_diligence_request(self, payload: Json, headers: Json) -> requests.Response:
        return self._request("POST", "/diligence-requests", payload, headers)

    def respond_diligence_request(
        self, dr_id: str, payload: Json, headers: Json
    ) -> requests.Response:
        return self._request(
            "POST", f"/diligence-requests/{dr_id}/respond", payload, headers
        )

    def clear_diligence_request(
        self, dr_id: str, payload: Optional[Json], headers: Json
    ) -> requests.Response:
        return self._request(
            "POST", f"/diligence-requests/{dr_id}/clear", payload or {}, headers
        )

    def escalate_diligence_request(
        self, dr_id: str, payload: Optional[Json], headers: Json
    ) -> requests.Response:
        return self._request(
            "POST", f"/diligence-requests/{dr_id}/escalate", payload or {}, headers
        )

    def waive_diligence_request(
        self, dr_id: str, payload: Json, headers: Json
    ) -> requests.Response:
        return self._request(
            "POST", f"/diligence-requests/{dr_id}/waive", payload, headers
        )

    # ------------------------------------------------------------------
    # Restricted funds
    # ------------------------------------------------------------------
    def create_restricted_fund(self, payload: Json, headers: Json) -> requests.Response:
        return self._request("POST", "/restricted-funds", payload, headers)

    def get_restricted_fund(self, fund_id: str, headers: Json) -> requests.Response:
        return self._request("GET", f"/restricted-funds/{fund_id}", None, headers)

    def list_restricted_funds(
        self, headers: Json, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", "/restricted-funds", params, headers)

    def seek_consent(
        self, fund_id: str, payload: Json, headers: Json
    ) -> requests.Response:
        return self._request(
            "POST", f"/restricted-funds/{fund_id}/seek-consent", payload, headers
        )

    def record_consent(
        self, fund_id: str, payload: Json, headers: Json
    ) -> requests.Response:
        return self._request(
            "POST", f"/restricted-funds/{fund_id}/record-consent", payload, headers
        )

    def file_petition(
        self, fund_id: str, payload: Json, headers: Json
    ) -> requests.Response:
        return self._request(
            "POST", f"/restricted-funds/{fund_id}/file-petition", payload, headers
        )

    def record_court_decision(
        self, fund_id: str, payload: Json, headers: Json
    ) -> requests.Response:
        return self._request(
            "POST", f"/restricted-funds/{fund_id}/record-court-decision", payload, headers
        )

    def transfer_restricted_fund(
        self, fund_id: str, payload: Json, headers: Json
    ) -> requests.Response:
        return self._request(
            "POST", f"/restricted-funds/{fund_id}/transfer", payload, headers
        )

    def unwind_restricted_fund(
        self, fund_id: str, payload: Json, headers: Json
    ) -> requests.Response:
        return self._request(
            "POST", f"/restricted-funds/{fund_id}/unwind", payload, headers
        )

    # ------------------------------------------------------------------
    # Board approvals
    # ------------------------------------------------------------------
    def create_board_approval(self, payload: Json, headers: Json) -> requests.Response:
        return self._request("POST", "/board-approvals", payload, headers)

    def certify_board_approval(
        self, approval_id: str, payload: Json, headers: Json
    ) -> requests.Response:
        return self._request(
            "POST", f"/board-approvals/{approval_id}/certify", payload, headers
        )

    def rescind_board_approval(
        self, approval_id: str, payload: Json, headers: Json
    ) -> requests.Response:
        return self._request(
            "POST", f"/board-approvals/{approval_id}/rescind", payload, headers
        )

    # ------------------------------------------------------------------
    # Attorney-general filings
    # ------------------------------------------------------------------
    def create_ag_filing(self, payload: Json, headers: Json) -> requests.Response:
        return self._request("POST", "/ag-filings", payload, headers)

    def record_ag_decision(
        self, filing_id: str, payload: Json, headers: Json
    ) -> requests.Response:
        return self._request(
            "POST", f"/ag-filings/{filing_id}/decision", payload, headers
        )

    # ------------------------------------------------------------------
    # Integration tasks
    # ------------------------------------------------------------------
    def create_integration_task(self, payload: Json, headers: Json) -> requests.Response:
        return self._request("POST", "/integration-tasks", payload, headers)

    def get_integration_task(self, task_id: str, headers: Json) -> requests.Response:
        return self._request("GET", f"/integration-tasks/{task_id}", None, headers)

    def list_integration_tasks(
        self, headers: Json, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", "/integration-tasks", params, headers)

    def start_integration_task(
        self, task_id: str, payload: Optional[Json], headers: Json
    ) -> requests.Response:
        return self._request(
            "POST", f"/integration-tasks/{task_id}/start", payload or {}, headers
        )

    def complete_integration_task(
        self, task_id: str, payload: Optional[Json], headers: Json
    ) -> requests.Response:
        return self._request(
            "POST", f"/integration-tasks/{task_id}/complete", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Operator endpoints
    # ------------------------------------------------------------------
    def run_regulatory_sweep(
        self, payload: Optional[Json], headers: Json
    ) -> requests.Response:
        return self._request("POST", "/regulatory-sweeps", payload or {}, headers)

    def set_clock(self, payload: Json, headers: Json) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)
