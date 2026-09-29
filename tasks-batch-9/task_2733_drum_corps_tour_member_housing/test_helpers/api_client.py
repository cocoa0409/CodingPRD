"""One method per endpoint declared by the PRD endpoint table."""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """HTTP client exposing every operation the PRD declares."""

    # ------------------------------------------------------------------
    # Escape hatch: a call with whatever headers the caller supplies,
    # including no auth headers at all.
    # ------------------------------------------------------------------
    def call(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ) -> requests.Response:
        return self._request(method, path, payload, headers, params)

    # ------------------------------------------------------------------ Seasons
    def create_season(self, payload, headers) -> requests.Response:
        return self._request("POST", "/seasons", payload, headers)

    def get_season(self, season_id, headers) -> requests.Response:
        return self._request("GET", f"/seasons/{season_id}", None, headers)

    def run_billing_cycle(self, season_id, headers) -> requests.Response:
        return self._request(
            "POST", f"/seasons/{season_id}/run-billing-cycle", None, headers
        )

    # ------------------------------------------------------------------ Members
    def create_member(self, payload, headers) -> requests.Response:
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers) -> requests.Response:
        return self._request("GET", f"/members/{member_id}", None, headers)

    def list_members(self, headers, params=None) -> requests.Response:
        return self._request("GET", "/members", None, headers, params)

    def record_audition_decision(self, member_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"/members/{member_id}/audition-decision", payload, headers
        )

    def set_medical_status(self, member_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"/members/{member_id}/medical-status", payload, headers
        )

    def withdraw_member(self, member_id, payload, headers) -> requests.Response:
        return self._request("POST", f"/members/{member_id}/withdraw", payload, headers)

    # -------------------------------------------------------- Member contracts
    def create_member_contract(self, payload, headers) -> requests.Response:
        return self._request("POST", "/member-contracts", payload, headers)

    def get_member_contract(self, contract_id, headers) -> requests.Response:
        return self._request("GET", f"/member-contracts/{contract_id}", None, headers)

    def list_member_contracts(self, headers, params=None) -> requests.Response:
        return self._request("GET", "/member-contracts", None, headers, params)

    def request_contract_revision(self, contract_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"/member-contracts/{contract_id}/request-revision", payload, headers
        )

    def reissue_member_contract(self, contract_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"/member-contracts/{contract_id}/reissue", payload, headers
        )

    def sign_member_contract(self, contract_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"/member-contracts/{contract_id}/sign", payload, headers
        )

    def execute_member_contract(self, contract_id, headers) -> requests.Response:
        return self._request(
            "POST", f"/member-contracts/{contract_id}/execute", None, headers
        )

    # ----------------------------------------------------------- Payment plans
    def create_payment_plan(self, payload, headers) -> requests.Response:
        return self._request("POST", "/payment-plans", payload, headers)

    def get_payment_plan(self, plan_id, headers) -> requests.Response:
        return self._request("GET", f"/payment-plans/{plan_id}", None, headers)

    def list_payment_plans(self, headers, params=None) -> requests.Response:
        return self._request("GET", "/payment-plans", None, headers, params)

    # -------------------------------------------------------- Tuition payments
    def create_tuition_payment(self, payload, headers) -> requests.Response:
        return self._request("POST", "/tuition-payments", payload, headers)

    def get_tuition_payment(self, payment_id, headers) -> requests.Response:
        return self._request("GET", f"/tuition-payments/{payment_id}", None, headers)

    def list_tuition_payments(self, headers, params=None) -> requests.Response:
        return self._request("GET", "/tuition-payments", None, headers, params)

    def reverse_tuition_payment(self, payment_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"/tuition-payments/{payment_id}/reverse", payload, headers
        )

    # ------------------------------------------------------------ Host schools
    def create_host_school(self, payload, headers) -> requests.Response:
        return self._request("POST", "/host-schools", payload, headers)

    def get_host_school(self, school_id, headers) -> requests.Response:
        return self._request("GET", f"/host-schools/{school_id}", None, headers)

    def list_host_schools(self, headers, params=None) -> requests.Response:
        return self._request("GET", "/host-schools", None, headers, params)

    # ----------------------------------------------------- Facility agreements
    def create_facility_agreement(self, payload, headers) -> requests.Response:
        return self._request("POST", "/facility-agreements", payload, headers)

    def get_facility_agreement(self, agreement_id, headers) -> requests.Response:
        return self._request(
            "GET", f"/facility-agreements/{agreement_id}", None, headers
        )

    def list_facility_agreements(self, headers, params=None) -> requests.Response:
        return self._request("GET", "/facility-agreements", None, headers, params)

    def submit_facility_agreement(self, agreement_id, headers) -> requests.Response:
        return self._request(
            "POST", f"/facility-agreements/{agreement_id}/submit", None, headers
        )

    def counter_facility_agreement(self, agreement_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"/facility-agreements/{agreement_id}/counter", payload, headers
        )

    def sign_facility_agreement(self, agreement_id, headers) -> requests.Response:
        return self._request(
            "POST", f"/facility-agreements/{agreement_id}/sign", None, headers
        )

    def cancel_facility_agreement(self, agreement_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"/facility-agreements/{agreement_id}/cancel", payload, headers
        )

    # ----------------------------------------------------- Housing assignments
    def create_housing_assignment(self, payload, headers) -> requests.Response:
        return self._request("POST", "/housing-assignments", payload, headers)

    def get_housing_assignment(self, assignment_id, headers) -> requests.Response:
        return self._request(
            "GET", f"/housing-assignments/{assignment_id}", None, headers
        )

    def list_housing_assignments(self, headers, params=None) -> requests.Response:
        return self._request("GET", "/housing-assignments", None, headers, params)

    def release_housing_assignment(self, assignment_id, headers) -> requests.Response:
        return self._request(
            "POST", f"/housing-assignments/{assignment_id}/release", None, headers
        )

    # -------------------------------------------------------------- Tour stops
    def create_tour_stop(self, payload, headers) -> requests.Response:
        return self._request("POST", "/tour-stops", payload, headers)

    def get_tour_stop(self, stop_id, headers) -> requests.Response:
        return self._request("GET", f"/tour-stops/{stop_id}", None, headers)

    def list_tour_stops(self, headers, params=None) -> requests.Response:
        return self._request("GET", "/tour-stops", None, headers, params)

    def confirm_tour_stop(self, stop_id, headers) -> requests.Response:
        return self._request("POST", f"/tour-stops/{stop_id}/confirm", None, headers)

    def complete_tour_stop(self, stop_id, headers) -> requests.Response:
        return self._request("POST", f"/tour-stops/{stop_id}/complete", None, headers)

    def cancel_tour_stop(self, stop_id, payload, headers) -> requests.Response:
        return self._request("POST", f"/tour-stops/{stop_id}/cancel", payload, headers)

    # ------------------------------------------------------------ Site bookings
    def create_site_booking(self, payload, headers) -> requests.Response:
        return self._request("POST", "/site-bookings", payload, headers)

    def get_site_booking(self, booking_id, headers) -> requests.Response:
        return self._request("GET", f"/site-bookings/{booking_id}", None, headers)

    def list_site_bookings(self, headers, params=None) -> requests.Response:
        return self._request("GET", "/site-bookings", None, headers, params)

    def release_site_booking(self, booking_id, headers) -> requests.Response:
        return self._request(
            "POST", f"/site-bookings/{booking_id}/release", None, headers
        )

    # --------------------------------------------------------------- Volunteers
    def create_volunteer(self, payload, headers) -> requests.Response:
        return self._request("POST", "/volunteers", payload, headers)

    def get_volunteer(self, volunteer_id, headers) -> requests.Response:
        return self._request("GET", f"/volunteers/{volunteer_id}", None, headers)

    def list_volunteers(self, headers, params=None) -> requests.Response:
        return self._request("GET", "/volunteers", None, headers, params)

    def record_screening_decision(self, volunteer_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"/volunteers/{volunteer_id}/screening-decision", payload, headers
        )

    # --------------------------------------------------------- Staff assignments
    def create_staff_assignment(self, payload, headers) -> requests.Response:
        return self._request("POST", "/staff-assignments", payload, headers)

    def get_staff_assignment(self, assignment_id, headers) -> requests.Response:
        return self._request(
            "GET", f"/staff-assignments/{assignment_id}", None, headers
        )

    def list_staff_assignments(self, headers, params=None) -> requests.Response:
        return self._request("GET", "/staff-assignments", None, headers, params)

    def accept_staff_assignment(self, assignment_id, headers) -> requests.Response:
        return self._request(
            "POST", f"/staff-assignments/{assignment_id}/accept", None, headers
        )

    def approve_staff_assignment(self, assignment_id, headers) -> requests.Response:
        return self._request(
            "POST", f"/staff-assignments/{assignment_id}/approve", None, headers
        )

    # ---------------------------------------------------------- Show settlements
    def create_show_settlement(self, payload, headers) -> requests.Response:
        return self._request("POST", "/show-settlements", payload, headers)

    def get_show_settlement(self, settlement_id, headers) -> requests.Response:
        return self._request(
            "GET", f"/show-settlements/{settlement_id}", None, headers
        )

    def list_show_settlements(self, headers, params=None) -> requests.Response:
        return self._request("GET", "/show-settlements", None, headers, params)

    def finalize_show_settlement(self, settlement_id, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"/show-settlements/{settlement_id}/finalize", payload, headers
        )

    # ------------------------------------------------------------ Logical clock
    def set_clock(self, to_iso8601, headers) -> requests.Response:
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
