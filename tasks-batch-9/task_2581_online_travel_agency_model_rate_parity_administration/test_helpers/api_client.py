"""Typed HTTP client: one method per endpoint of the OTA administration API."""
from __future__ import annotations

from typing import Any, Dict, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient

from .types import Headers, Json


class ApiClient(GenericApiClient):
    """One method per declared endpoint, with the same argument order as the path."""

    # ------------------------------------------------------------ test capabilities
    def set_clock(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def simulate_chargeback(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request(
            "POST", "/_payments/simulate-chargeback", payload, headers
        )

    # ----------------------------------------------------------------------- markets
    def create_market(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/markets", payload, headers)

    def get_market(self, market_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/markets/{market_id}", headers=headers)

    def list_markets(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/markets", headers=headers, params=params)

    # --------------------------------------------------------------------- suppliers
    def create_supplier(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/suppliers", payload, headers)

    def get_supplier(self, supplier_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/suppliers/{supplier_id}", headers=headers)

    def list_suppliers(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/suppliers", headers=headers, params=params)

    def reinstate_supplier(
        self, supplier_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/suppliers/{supplier_id}/reinstate", payload, headers
        )

    def offboard_supplier(
        self, supplier_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/suppliers/{supplier_id}/offboard", payload, headers
        )

    # -------------------------------------------------------------- model agreements
    def create_model_agreement(
        self, supplier_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/suppliers/{supplier_id}/model-agreements", payload, headers
        )

    def get_model_agreement(
        self, agreement_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"/model-agreements/{agreement_id}", headers=headers
        )

    def list_model_agreements(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/model-agreements", headers=headers, params=params
        )

    def activate_model_agreement(
        self, agreement_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/model-agreements/{agreement_id}/activate", payload, headers
        )

    def terminate_model_agreement(
        self, agreement_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/model-agreements/{agreement_id}/terminate", payload, headers
        )

    def withdraw_model_agreement(
        self, agreement_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/model-agreements/{agreement_id}/withdraw", payload, headers
        )

    # ---------------------------------------------------------------- certifications
    def create_certification(
        self, supplier_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/suppliers/{supplier_id}/certifications", payload, headers
        )

    def get_certification(self, cert_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/certifications/{cert_id}", headers=headers)

    def list_certifications(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/certifications", headers=headers, params=params)

    def start_certification_review(
        self, cert_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/certifications/{cert_id}/start-review", payload, headers
        )

    def decide_certification(
        self, cert_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/certifications/{cert_id}/decide", payload, headers
        )

    def remediate_certification(
        self, cert_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/certifications/{cert_id}/remediate", payload, headers
        )

    def revoke_certification(
        self, cert_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/certifications/{cert_id}/revoke", payload, headers
        )

    # -------------------------------------------------------------------- rate plans
    def create_rate_plan(
        self, supplier_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/suppliers/{supplier_id}/rate-plans", payload, headers
        )

    def get_rate_plan(self, plan_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/rate-plans/{plan_id}", headers=headers)

    def list_rate_plans(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/rate-plans", headers=headers, params=params)

    def release_parity_hold(
        self, plan_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/rate-plans/{plan_id}/release-parity-hold", payload, headers
        )

    def archive_rate_plan(
        self, plan_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/rate-plans/{plan_id}/archive", payload, headers
        )

    # ------------------------------------------------------------------------ offers
    def create_offer(
        self, plan_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"/rate-plans/{plan_id}/offers", payload, headers)

    def get_offer(self, offer_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/offers/{offer_id}", headers=headers)

    def list_offers(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/offers", headers=headers, params=params)

    def publish_offer(
        self, offer_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"/offers/{offer_id}/publish", payload, headers)

    def suppress_offer(
        self, offer_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"/offers/{offer_id}/suppress", payload, headers)

    def close_out_offer(
        self, offer_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"/offers/{offer_id}/close-out", payload, headers)

    # ------------------------------------------------------------- parity observation
    def create_parity_observation(
        self, plan_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/rate-plans/{plan_id}/parity-observations", payload, headers
        )

    def get_parity_observation(
        self, observation_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"/parity-observations/{observation_id}", headers=headers
        )

    def list_parity_observations(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/parity-observations", headers=headers, params=params
        )

    # ------------------------------------------------------------------ parity cases
    def get_parity_case(self, case_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/parity-cases/{case_id}", headers=headers)

    def list_parity_cases(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/parity-cases", headers=headers, params=params)

    def notify_parity_supplier(
        self, case_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/parity-cases/{case_id}/notify-supplier", payload, headers
        )

    def respond_parity_case(
        self, case_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/parity-cases/{case_id}/respond", payload, headers
        )

    def escalate_parity_case(
        self, case_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/parity-cases/{case_id}/escalate", payload, headers
        )

    def close_parity_case(
        self, case_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/parity-cases/{case_id}/close", payload, headers
        )

    # ----------------------------------------------------------- commission overrides
    def create_commission_override(
        self, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/commission-overrides", payload, headers)

    def get_commission_override(
        self, override_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"/commission-overrides/{override_id}", headers=headers
        )

    def list_commission_overrides(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/commission-overrides", headers=headers, params=params
        )

    def approve_commission_override(
        self, override_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/commission-overrides/{override_id}/approve", payload, headers
        )

    def reject_commission_override(
        self, override_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/commission-overrides/{override_id}/reject", payload, headers
        )

    # --------------------------------------------------------- placement agreements
    def create_placement_agreement(
        self, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/placement-agreements", payload, headers)

    def get_placement_agreement(
        self, placement_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"/placement-agreements/{placement_id}", headers=headers
        )

    def list_placement_agreements(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/placement-agreements", headers=headers, params=params
        )

    def approve_placement_agreement(
        self, placement_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/placement-agreements/{placement_id}/approve", payload, headers
        )

    def cancel_placement_agreement(
        self, placement_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/placement-agreements/{placement_id}/cancel", payload, headers
        )

    # ------------------------------------------------------------------ ranking runs
    def create_ranking_run(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/ranking-runs", payload, headers)

    def get_ranking_run(self, run_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/ranking-runs/{run_id}", headers=headers)

    def list_ranking_runs(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/ranking-runs", headers=headers, params=params)

    def publish_ranking_run(
        self, run_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/ranking-runs/{run_id}/publish", payload, headers
        )

    def withdraw_ranking_run(
        self, run_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/ranking-runs/{run_id}/withdraw", payload, headers
        )

    # --------------------------------------------------------------- ranking entries
    def get_ranking_entry(self, entry_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/ranking-entries/{entry_id}", headers=headers)

    def list_ranking_entries(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/ranking-entries", headers=headers, params=params)

    # ---------------------------------------------------------------------- packages
    def create_package(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/packages", payload, headers)

    def get_package(self, package_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/packages/{package_id}", headers=headers)

    def list_packages(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/packages", headers=headers, params=params)

    def create_package_component(
        self, package_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/packages/{package_id}/components", payload, headers
        )

    def price_package(
        self, package_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"/packages/{package_id}/price", payload, headers)

    def publish_package(
        self, package_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/packages/{package_id}/publish", payload, headers
        )

    def withdraw_package(
        self, package_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/packages/{package_id}/withdraw", payload, headers
        )

    def get_package_component(
        self, component_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"/package-components/{component_id}", headers=headers
        )

    def list_package_components(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/package-components", headers=headers, params=params
        )

    # ---------------------------------------------------------------------- bookings
    def create_booking(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/bookings", payload, headers)

    def get_booking(self, booking_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def list_bookings(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/bookings", headers=headers, params=params)

    def capture_booking(
        self, booking_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/bookings/{booking_id}/capture", payload, headers
        )

    def confirm_booking(
        self, booking_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/bookings/{booking_id}/confirm", payload, headers
        )

    def cancel_booking(
        self, booking_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"/bookings/{booking_id}/cancel", payload, headers)

    def complete_booking(
        self, booking_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/bookings/{booking_id}/complete", payload, headers
        )

    # ----------------------------------------------------------------- dispute cases
    def create_dispute_case(
        self, booking_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/bookings/{booking_id}/dispute-cases", payload, headers
        )

    def get_dispute_case(self, dispute_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/dispute-cases/{dispute_id}", headers=headers)

    def list_dispute_cases(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/dispute-cases", headers=headers, params=params)

    def request_dispute_response(
        self, dispute_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/dispute-cases/{dispute_id}/request-response", payload, headers
        )

    def respond_dispute_case(
        self, dispute_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/dispute-cases/{dispute_id}/respond", payload, headers
        )

    def resolve_dispute_case(
        self, dispute_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/dispute-cases/{dispute_id}/resolve", payload, headers
        )

    # -------------------------------------------------------------------- scorecards
    def create_scorecard(
        self, supplier_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/suppliers/{supplier_id}/scorecards", payload, headers
        )

    def get_scorecard(self, scorecard_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/scorecards/{scorecard_id}", headers=headers)

    def list_scorecards(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/scorecards", headers=headers, params=params)

    def finalize_scorecard(
        self, scorecard_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/scorecards/{scorecard_id}/finalize", payload, headers
        )
