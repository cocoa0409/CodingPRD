"""One method per endpoint of the RV club program API.

All endpoints are mounted at the service root; there is no common path prefix.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient, build_user_headers

Headers = Optional[Dict[str, str]]
Payload = Optional[Dict[str, Any]]
Params = Optional[Dict[str, Any]]


class ApiClient(GenericApiClient):
    """Thin, complete transport over the documented operations."""

    # ------------------------------------------------------------------
    # Membership tiers
    # ------------------------------------------------------------------

    def create_membership_tier(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", "/membership-tiers", payload, headers)

    def get_membership_tier(self, tier_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/membership-tiers/{tier_id}", headers=headers)

    def list_membership_tiers(self, headers: Headers, params: Params = None) -> requests.Response:
        return self._request("GET", "/membership-tiers", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Members
    # ------------------------------------------------------------------

    def create_member(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/members/{member_id}", headers=headers)

    # ------------------------------------------------------------------
    # Memberships
    # ------------------------------------------------------------------

    def create_membership(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", "/memberships", payload, headers)

    def get_membership(self, membership_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/memberships/{membership_id}", headers=headers)

    def list_memberships(self, headers: Headers, params: Params = None) -> requests.Response:
        return self._request("GET", "/memberships", headers=headers, params=params)

    def list_membership_dues_invoices(
        self, membership_id: str, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/memberships/{membership_id}/dues-invoices", headers=headers, params=params
        )

    def list_membership_satisfaction_surveys(
        self, membership_id: str, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/memberships/{membership_id}/satisfaction-surveys",
            headers=headers,
            params=params,
        )

    def suspend_membership(
        self, membership_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"/memberships/{membership_id}/suspension", payload, headers)

    def reinstate_membership(
        self, membership_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/memberships/{membership_id}/reinstatement", payload, headers
        )

    # ------------------------------------------------------------------
    # Dues invoices and payments
    # ------------------------------------------------------------------

    def get_dues_invoice(self, invoice_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/dues-invoices/{invoice_id}", headers=headers)

    def pay_dues_invoice(
        self, invoice_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"/dues-invoices/{invoice_id}/payments", payload, headers)

    def reverse_dues_payment(
        self, invoice_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/dues-invoices/{invoice_id}/payment-reversals", payload, headers
        )

    def run_annual_dues(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", "/ops/annual-dues-run", payload, headers)

    def run_dues_delinquency(self, headers: Headers, payload: Payload = None) -> requests.Response:
        return self._request("POST", "/ops/dues-delinquency-run", payload or {}, headers)

    # ------------------------------------------------------------------
    # Parks
    # ------------------------------------------------------------------

    def create_park(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", "/parks", payload, headers)

    def get_park(self, park_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/parks/{park_id}", headers=headers)

    def list_parks(self, headers: Headers, params: Params = None) -> requests.Response:
        return self._request("GET", "/parks", headers=headers, params=params)

    def open_park_season(
        self, park_id: str, headers: Headers, payload: Payload = None
    ) -> requests.Response:
        return self._request("POST", f"/parks/{park_id}/season-openings", payload or {}, headers)

    def close_park_season(
        self, park_id: str, headers: Headers, payload: Payload = None
    ) -> requests.Response:
        return self._request("POST", f"/parks/{park_id}/season-closures", payload or {}, headers)

    def file_amenity_inspection(
        self, park_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"/parks/{park_id}/amenity-inspections", payload, headers)

    def list_park_amenity_inspections(
        self, park_id: str, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/parks/{park_id}/amenity-inspections", headers=headers, params=params
        )

    def list_park_satisfaction_surveys(
        self, park_id: str, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/parks/{park_id}/satisfaction-surveys", headers=headers, params=params
        )

    def list_park_maintenance_windows(
        self, park_id: str, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/parks/{park_id}/maintenance-windows", headers=headers, params=params
        )

    def list_park_capital_projects(
        self, park_id: str, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/parks/{park_id}/capital-projects", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Maintenance windows
    # ------------------------------------------------------------------

    def create_maintenance_window(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", "/maintenance-windows", payload, headers)

    def activate_maintenance_window(
        self, window_id: str, headers: Headers, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/maintenance-windows/{window_id}/activation", payload or {}, headers
        )

    def complete_maintenance_window(
        self, window_id: str, headers: Headers, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/maintenance-windows/{window_id}/completion", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Reservations
    # ------------------------------------------------------------------

    def create_reservation(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", "/reservations", payload, headers)

    def create_transient_reservation(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/transient-reservations", payload, headers)

    def get_reservation(self, reservation_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/reservations/{reservation_id}", headers=headers)

    def list_reservations(self, headers: Headers, params: Params = None) -> requests.Response:
        return self._request("GET", "/reservations", headers=headers, params=params)

    def cancel_reservation(
        self, reservation_id: str, headers: Headers, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/reservations/{reservation_id}/cancellation", payload or {}, headers
        )

    def check_in_reservation(
        self, reservation_id: str, headers: Headers, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/reservations/{reservation_id}/check-in", payload or {}, headers
        )

    def check_out_reservation(
        self, reservation_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"/reservations/{reservation_id}/check-out", payload, headers)

    def extend_reservation(
        self, reservation_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"/reservations/{reservation_id}/extensions", payload, headers)

    def submit_satisfaction_survey(
        self, reservation_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/reservations/{reservation_id}/satisfaction-surveys", payload, headers
        )

    def list_reservation_satisfaction_surveys(
        self, reservation_id: str, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/reservations/{reservation_id}/satisfaction-surveys",
            headers=headers,
            params=params,
        )

    def list_reservation_occupancy_exceptions(
        self, reservation_id: str, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/reservations/{reservation_id}/occupancy-exceptions",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Occupancy exceptions
    # ------------------------------------------------------------------

    def get_occupancy_exception(self, exception_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/occupancy-exceptions/{exception_id}", headers=headers)

    def decide_occupancy_exception(
        self, exception_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/occupancy-exceptions/{exception_id}/decision", payload, headers
        )

    # ------------------------------------------------------------------
    # Transfer requests
    # ------------------------------------------------------------------

    def create_transfer_request(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", "/transfer-requests", payload, headers)

    def get_transfer_request(self, request_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/transfer-requests/{request_id}", headers=headers)

    def list_transfer_requests(self, headers: Headers, params: Params = None) -> requests.Response:
        return self._request("GET", "/transfer-requests", headers=headers, params=params)

    def decide_transfer_request(
        self, request_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"/transfer-requests/{request_id}/decision", payload, headers)

    # ------------------------------------------------------------------
    # Affiliate agreements
    # ------------------------------------------------------------------

    def create_affiliate_agreement(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", "/affiliate-agreements", payload, headers)

    def get_affiliate_agreement(self, agreement_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/affiliate-agreements/{agreement_id}", headers=headers)

    def change_affiliate_agreement_status(
        self, agreement_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/affiliate-agreements/{agreement_id}/status-changes", payload, headers
        )

    # ------------------------------------------------------------------
    # Capital projects and reinvestment
    # ------------------------------------------------------------------

    def create_capital_project(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", "/capital-projects", payload, headers)

    def get_capital_project(self, project_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/capital-projects/{project_id}", headers=headers)

    def decide_capital_project(
        self, project_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"/capital-projects/{project_id}/decision", payload, headers)

    def run_reinvestment(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", "/ops/reinvestment-runs", payload, headers)

    # ------------------------------------------------------------------
    # Logical clock test hook
    # ------------------------------------------------------------------

    def set_clock(self, current_utc: str, headers: Headers = None) -> requests.Response:
        """Move the logical clock. The hook mutates no entity.

        All five roles are authorised, so a ClubAdmin identity is supplied by
        default; pass ``headers`` explicitly to exercise another principal.
        """
        if headers is None:
            headers = build_user_headers("clubadmin-hq-1", "ClubAdmin")
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )


api_client = ApiClient()
