"""Endpoint-per-method HTTP client for the Property Improvement Plan Compliance API.

Every documented operation gets exactly one method so that tests never hand-build
paths. All resources are mounted under ``/pip``; the logical-clock control sits
outside that prefix.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

JsonDict = Dict[str, Any]


class ApiClient(GenericApiClient):
    """One method per endpoint of the API under test."""

    # ------------------------------------------------------------------
    # Franchisee accounts
    # ------------------------------------------------------------------

    def create_franchisee_account(self, payload: JsonDict, headers: JsonDict) -> requests.Response:
        return self._request("POST", "/pip/franchisee-accounts", payload, headers)

    def get_franchisee_account(self, franchisee_id: str, headers: JsonDict) -> requests.Response:
        return self._request("GET", f"/pip/franchisee-accounts/{franchisee_id}", None, headers)

    def list_franchisee_accounts(
        self, headers: JsonDict, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request("GET", "/pip/franchisee-accounts", params, headers)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    def create_property(self, payload: JsonDict, headers: JsonDict) -> requests.Response:
        return self._request("POST", "/pip/properties", payload, headers)

    def get_property(self, property_id: str, headers: JsonDict) -> requests.Response:
        return self._request("GET", f"/pip/properties/{property_id}", None, headers)

    def list_properties(
        self, headers: JsonDict, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request("GET", "/pip/properties", params, headers)

    def patch_property(
        self, property_id: str, payload: JsonDict, headers: JsonDict
    ) -> requests.Response:
        return self._request("PATCH", f"/pip/properties/{property_id}", payload, headers)

    def create_reserve_contribution(
        self, property_id: str, payload: JsonDict, headers: JsonDict
    ) -> requests.Response:
        return self._request(
            "POST", f"/pip/properties/{property_id}/reserve-contributions", payload, headers
        )

    def get_property_risk_summary(self, property_id: str, headers: JsonDict) -> requests.Response:
        return self._request("GET", f"/pip/properties/{property_id}/risk-summary", None, headers)

    # ------------------------------------------------------------------
    # Plans
    # ------------------------------------------------------------------

    def create_plan(self, payload: JsonDict, headers: JsonDict) -> requests.Response:
        return self._request("POST", "/pip/plans", payload, headers)

    def get_plan(self, plan_id: str, headers: JsonDict) -> requests.Response:
        return self._request("GET", f"/pip/plans/{plan_id}", None, headers)

    def list_plans(self, headers: JsonDict, params: Optional[JsonDict] = None) -> requests.Response:
        return self._request("GET", "/pip/plans", params, headers)

    def issue_plan(
        self, plan_id: str, headers: JsonDict, payload: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request("POST", f"/pip/plans/{plan_id}/issue", payload or {}, headers)

    def acknowledge_plan(
        self, plan_id: str, headers: JsonDict, payload: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request("POST", f"/pip/plans/{plan_id}/acknowledge", payload or {}, headers)

    def withdraw_plan(
        self, plan_id: str, headers: JsonDict, payload: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request("POST", f"/pip/plans/{plan_id}/withdraw", payload or {}, headers)

    def get_plan_cost_summary(self, plan_id: str, headers: JsonDict) -> requests.Response:
        return self._request("GET", f"/pip/plans/{plan_id}/cost-summary", None, headers)

    def run_compliance_sweep(
        self, plan_id: str, headers: JsonDict, payload: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/pip/plans/{plan_id}/compliance-sweep", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Scoped items
    # ------------------------------------------------------------------

    def create_item(self, payload: JsonDict, headers: JsonDict) -> requests.Response:
        return self._request("POST", "/pip/items", payload, headers)

    def get_item(self, item_id: str, headers: JsonDict) -> requests.Response:
        return self._request("GET", f"/pip/items/{item_id}", None, headers)

    def list_items(self, headers: JsonDict, params: Optional[JsonDict] = None) -> requests.Response:
        return self._request("GET", "/pip/items", params, headers)

    def patch_item(self, item_id: str, payload: JsonDict, headers: JsonDict) -> requests.Response:
        return self._request("PATCH", f"/pip/items/{item_id}", payload, headers)

    def start_item(
        self, item_id: str, headers: JsonDict, payload: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request("POST", f"/pip/items/{item_id}/start", payload or {}, headers)

    def complete_item_work(
        self, item_id: str, headers: JsonDict, payload: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request("POST", f"/pip/items/{item_id}/complete-work", payload or {}, headers)

    # ------------------------------------------------------------------
    # Extension requests
    # ------------------------------------------------------------------

    def create_extension_request(self, payload: JsonDict, headers: JsonDict) -> requests.Response:
        return self._request("POST", "/pip/extension-requests", payload, headers)

    def get_extension_request(self, request_id: str, headers: JsonDict) -> requests.Response:
        return self._request("GET", f"/pip/extension-requests/{request_id}", None, headers)

    def list_extension_requests(
        self, headers: JsonDict, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request("GET", "/pip/extension-requests", params, headers)

    def decide_extension_request(
        self, request_id: str, payload: JsonDict, headers: JsonDict
    ) -> requests.Response:
        return self._request(
            "POST", f"/pip/extension-requests/{request_id}/decide", payload, headers
        )

    def resubmit_extension_request(
        self, request_id: str, payload: JsonDict, headers: JsonDict
    ) -> requests.Response:
        return self._request(
            "POST", f"/pip/extension-requests/{request_id}/resubmit", payload, headers
        )

    # ------------------------------------------------------------------
    # Capital budgets
    # ------------------------------------------------------------------

    def create_capital_budget(self, payload: JsonDict, headers: JsonDict) -> requests.Response:
        return self._request("POST", "/pip/capital-budgets", payload, headers)

    def get_capital_budget(self, budget_id: str, headers: JsonDict) -> requests.Response:
        return self._request("GET", f"/pip/capital-budgets/{budget_id}", None, headers)

    def list_capital_budgets(
        self, headers: JsonDict, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request("GET", "/pip/capital-budgets", params, headers)

    def approve_capital_budget(
        self, budget_id: str, headers: JsonDict, payload: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/pip/capital-budgets/{budget_id}/approve", payload or {}, headers
        )

    def lock_capital_budget(
        self, budget_id: str, headers: JsonDict, payload: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/pip/capital-budgets/{budget_id}/lock", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Reserve draws
    # ------------------------------------------------------------------

    def create_reserve_draw(self, payload: JsonDict, headers: JsonDict) -> requests.Response:
        return self._request("POST", "/pip/reserve-draws", payload, headers)

    def get_reserve_draw(self, draw_id: str, headers: JsonDict) -> requests.Response:
        return self._request("GET", f"/pip/reserve-draws/{draw_id}", None, headers)

    def list_reserve_draws(
        self, headers: JsonDict, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request("GET", "/pip/reserve-draws", params, headers)

    def consent_reserve_draw(
        self, draw_id: str, payload: JsonDict, headers: JsonDict
    ) -> requests.Response:
        return self._request("POST", f"/pip/reserve-draws/{draw_id}/consent", payload, headers)

    def disburse_reserve_draw(
        self, draw_id: str, headers: JsonDict, payload: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/pip/reserve-draws/{draw_id}/disburse", payload or {}, headers
        )

    def reverse_reserve_draw(
        self, draw_id: str, headers: JsonDict, payload: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/pip/reserve-draws/{draw_id}/reverse", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Renovation phases
    # ------------------------------------------------------------------

    def create_renovation_phase(self, payload: JsonDict, headers: JsonDict) -> requests.Response:
        return self._request("POST", "/pip/renovation-phases", payload, headers)

    def get_renovation_phase(self, phase_id: str, headers: JsonDict) -> requests.Response:
        return self._request("GET", f"/pip/renovation-phases/{phase_id}", None, headers)

    def list_renovation_phases(
        self, headers: JsonDict, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request("GET", "/pip/renovation-phases", params, headers)

    def activate_renovation_phase(
        self, phase_id: str, headers: JsonDict, payload: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/pip/renovation-phases/{phase_id}/activate", payload or {}, headers
        )

    def close_out_renovation_phase(
        self, phase_id: str, headers: JsonDict, payload: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/pip/renovation-phases/{phase_id}/close-out", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Contractors and bookings
    # ------------------------------------------------------------------

    def create_contractor(self, payload: JsonDict, headers: JsonDict) -> requests.Response:
        return self._request("POST", "/pip/contractors", payload, headers)

    def get_contractor(self, contractor_id: str, headers: JsonDict) -> requests.Response:
        return self._request("GET", f"/pip/contractors/{contractor_id}", None, headers)

    def list_contractors(
        self, headers: JsonDict, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request("GET", "/pip/contractors", params, headers)

    def create_contractor_booking(self, payload: JsonDict, headers: JsonDict) -> requests.Response:
        return self._request("POST", "/pip/contractor-bookings", payload, headers)

    def get_contractor_booking(self, booking_id: str, headers: JsonDict) -> requests.Response:
        return self._request("GET", f"/pip/contractor-bookings/{booking_id}", None, headers)

    def list_contractor_bookings(
        self, headers: JsonDict, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request("GET", "/pip/contractor-bookings", params, headers)

    # ------------------------------------------------------------------
    # Inspections and punch-list defects
    # ------------------------------------------------------------------

    def create_inspection(self, payload: JsonDict, headers: JsonDict) -> requests.Response:
        return self._request("POST", "/pip/inspections", payload, headers)

    def get_inspection(self, inspection_id: str, headers: JsonDict) -> requests.Response:
        return self._request("GET", f"/pip/inspections/{inspection_id}", None, headers)

    def list_inspections(
        self, headers: JsonDict, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request("GET", "/pip/inspections", params, headers)

    def perform_inspection(
        self, inspection_id: str, headers: JsonDict, payload: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/pip/inspections/{inspection_id}/perform", payload or {}, headers
        )

    def sign_off_inspection(
        self, inspection_id: str, headers: JsonDict, payload: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/pip/inspections/{inspection_id}/sign-off", payload or {}, headers
        )

    def create_punch_list_item(self, payload: JsonDict, headers: JsonDict) -> requests.Response:
        return self._request("POST", "/pip/punch-list-items", payload, headers)

    def get_punch_list_item(self, punch_id: str, headers: JsonDict) -> requests.Response:
        return self._request("GET", f"/pip/punch-list-items/{punch_id}", None, headers)

    def list_punch_list_items(
        self, headers: JsonDict, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request("GET", "/pip/punch-list-items", params, headers)

    def remediate_punch_list_item(
        self, punch_id: str, headers: JsonDict, payload: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/pip/punch-list-items/{punch_id}/remediate", payload or {}, headers
        )

    def verify_punch_list_item(
        self, punch_id: str, payload: JsonDict, headers: JsonDict
    ) -> requests.Response:
        return self._request("POST", f"/pip/punch-list-items/{punch_id}/verify", payload, headers)

    # ------------------------------------------------------------------
    # Scope disputes
    # ------------------------------------------------------------------

    def create_dispute(self, payload: JsonDict, headers: JsonDict) -> requests.Response:
        return self._request("POST", "/pip/disputes", payload, headers)

    def get_dispute(self, dispute_id: str, headers: JsonDict) -> requests.Response:
        return self._request("GET", f"/pip/disputes/{dispute_id}", None, headers)

    def list_disputes(
        self, headers: JsonDict, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request("GET", "/pip/disputes", params, headers)

    def resolve_dispute(
        self, dispute_id: str, payload: JsonDict, headers: JsonDict
    ) -> requests.Response:
        return self._request("POST", f"/pip/disputes/{dispute_id}/resolve", payload, headers)

    # ------------------------------------------------------------------
    # Default notices
    # ------------------------------------------------------------------

    def create_default_notice(self, payload: JsonDict, headers: JsonDict) -> requests.Response:
        return self._request("POST", "/pip/default-notices", payload, headers)

    def get_default_notice(self, notice_id: str, headers: JsonDict) -> requests.Response:
        return self._request("GET", f"/pip/default-notices/{notice_id}", None, headers)

    def list_default_notices(
        self, headers: JsonDict, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request("GET", "/pip/default-notices", params, headers)

    def cure_default_notice(
        self, notice_id: str, headers: JsonDict, payload: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/pip/default-notices/{notice_id}/cure", payload or {}, headers
        )

    def escalate_default_notice(
        self, notice_id: str, headers: JsonDict, payload: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/pip/default-notices/{notice_id}/escalate", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Compliance ledger
    # ------------------------------------------------------------------

    def get_compliance_ledger_entry(self, entry_id: str, headers: JsonDict) -> requests.Response:
        return self._request("GET", f"/pip/compliance-ledger-entries/{entry_id}", None, headers)

    def list_compliance_ledger_entries(
        self, headers: JsonDict, params: Optional[JsonDict] = None
    ) -> requests.Response:
        return self._request("GET", "/pip/compliance-ledger-entries", params, headers)

    # ------------------------------------------------------------------
    # Logical compliance clock
    # ------------------------------------------------------------------

    def set_clock(self, current_utc: str, headers: JsonDict) -> requests.Response:
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )


api_client = ApiClient()

__all__ = ["ApiClient", "api_client"]
