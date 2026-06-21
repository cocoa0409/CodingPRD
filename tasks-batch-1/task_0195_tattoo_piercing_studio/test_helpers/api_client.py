"""API client: one method per endpoint defined in the Tattoo & Piercing
Studio PRD (§4). The base _request() method is inherited from the framework's
GenericApiClient. Every path is mounted under the /studio prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clock (test-driving) ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/studio/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ---- Artist ----
    def create_artist(self, payload, headers):
        return self._request("POST", "/studio/artists", payload, headers)

    def get_artist(self, artist_id, headers):
        return self._request("GET", f"/studio/artists/{artist_id}", headers=headers)

    def list_artists(self, headers, params=None):
        return self._request("GET", "/studio/artists", headers=headers, params=params)

    def list_artist_flash_designs(self, artist_id, headers, params=None):
        return self._request(
            "GET", f"/studio/artists/{artist_id}/flash-designs",
            headers=headers, params=params,
        )

    def list_artist_custom_requests(self, artist_id, headers, params=None):
        return self._request(
            "GET", f"/studio/artists/{artist_id}/custom-requests",
            headers=headers, params=params,
        )

    def list_artist_portfolio_items(self, artist_id, headers, params=None):
        return self._request(
            "GET", f"/studio/artists/{artist_id}/portfolio-items",
            headers=headers, params=params,
        )

    # ---- Client ----
    def create_client(self, payload, headers):
        return self._request("POST", "/studio/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/studio/clients/{client_id}", headers=headers)

    def list_client_waivers(self, client_id, headers, params=None):
        return self._request(
            "GET", f"/studio/clients/{client_id}/waivers",
            headers=headers, params=params,
        )

    def submit_id_verification(self, client_id, payload, headers):
        return self._request(
            "POST", f"/studio/clients/{client_id}/id-verification", payload, headers,
        )

    def approve_id_verification(self, client_id, headers, payload=None):
        return self._request(
            "POST", f"/studio/clients/{client_id}/id-verification/approve",
            payload or {}, headers,
        )

    def reject_id_verification(self, client_id, headers, payload=None):
        return self._request(
            "POST", f"/studio/clients/{client_id}/id-verification/reject",
            payload or {}, headers,
        )

    # ---- FlashDesign ----
    def create_flash_design(self, payload, headers):
        return self._request("POST", "/studio/flash-designs", payload, headers)

    def get_flash_design(self, flash_id, headers):
        return self._request("GET", f"/studio/flash-designs/{flash_id}", headers=headers)

    def retire_flash_design(self, flash_id, headers):
        return self._request(
            "POST", f"/studio/flash-designs/{flash_id}/retire", {}, headers,
        )

    # ---- CustomDesignRequest ----
    def create_custom_request(self, payload, headers):
        return self._request("POST", "/studio/custom-requests", payload, headers)

    def get_custom_request(self, request_id, headers):
        return self._request("GET", f"/studio/custom-requests/{request_id}", headers=headers)

    def list_custom_requests(self, headers, params=None):
        return self._request("GET", "/studio/custom-requests", headers=headers, params=params)

    def quote_custom_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/studio/custom-requests/{request_id}/quote", payload, headers,
        )

    def request_revision_custom_request(self, request_id, headers):
        return self._request(
            "POST", f"/studio/custom-requests/{request_id}/request-revision", {}, headers,
        )

    def approve_custom_request(self, request_id, headers):
        return self._request(
            "POST", f"/studio/custom-requests/{request_id}/approve", {}, headers,
        )

    def decline_custom_request(self, request_id, headers):
        return self._request(
            "POST", f"/studio/custom-requests/{request_id}/decline", {}, headers,
        )

    # ---- Chair ----
    def create_chair(self, payload, headers):
        return self._request("POST", "/studio/chairs", payload, headers)

    def get_chair(self, chair_id, headers):
        return self._request("GET", f"/studio/chairs/{chair_id}", headers=headers)

    def list_chairs(self, headers, params=None):
        return self._request("GET", "/studio/chairs", headers=headers, params=params)

    # ---- Appointment ----
    def create_appointment(self, payload, headers):
        return self._request("POST", "/studio/appointments", payload, headers)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/studio/appointments/{appointment_id}", headers=headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/studio/appointments", headers=headers, params=params)

    def pay_deposit(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/studio/appointments/{appointment_id}/deposits", payload, headers,
        )

    def list_deposits(self, appointment_id, headers, params=None):
        return self._request(
            "GET", f"/studio/appointments/{appointment_id}/deposits",
            headers=headers, params=params,
        )

    def record_waiver(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/studio/appointments/{appointment_id}/waiver", payload, headers,
        )

    def list_waivers(self, appointment_id, headers, params=None):
        return self._request(
            "GET", f"/studio/appointments/{appointment_id}/waiver",
            headers=headers, params=params,
        )

    def confirm_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/studio/appointments/{appointment_id}/confirm", {}, headers,
        )

    def cancel_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/studio/appointments/{appointment_id}/cancel", {}, headers,
        )

    def cancel_appointment_by_artist(self, appointment_id, headers):
        return self._request(
            "POST", f"/studio/appointments/{appointment_id}/cancel-by-artist", {}, headers,
        )

    def reschedule_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/studio/appointments/{appointment_id}/reschedule", payload, headers,
        )

    def complete_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/studio/appointments/{appointment_id}/complete", payload, headers,
        )

    def no_show_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/studio/appointments/{appointment_id}/no-show", {}, headers,
        )

    def get_payout(self, appointment_id, headers):
        return self._request(
            "GET", f"/studio/appointments/{appointment_id}/payout", headers=headers,
        )

    # ---- TouchUp ----
    def request_touchup(self, appointment_id, headers, payload=None):
        return self._request(
            "POST", f"/studio/appointments/{appointment_id}/touchups",
            payload or {}, headers,
        )

    def list_touchups(self, appointment_id, headers, params=None):
        return self._request(
            "GET", f"/studio/appointments/{appointment_id}/touchups",
            headers=headers, params=params,
        )

    def get_touchup(self, touchup_id, headers):
        return self._request("GET", f"/studio/touchups/{touchup_id}", headers=headers)

    def schedule_touchup(self, touchup_id, headers):
        return self._request("POST", f"/studio/touchups/{touchup_id}/schedule", {}, headers)

    def deny_touchup(self, touchup_id, headers):
        return self._request("POST", f"/studio/touchups/{touchup_id}/deny", {}, headers)

    # ---- PortfolioItem ----
    def create_portfolio_item(self, payload, headers):
        return self._request("POST", "/studio/portfolio-items", payload, headers)

    def get_portfolio_item(self, item_id, headers):
        return self._request("GET", f"/studio/portfolio-items/{item_id}", headers=headers)

    def list_portfolio_items(self, headers, params=None):
        return self._request("GET", "/studio/portfolio-items", headers=headers, params=params)

    def publish_portfolio_item(self, item_id, headers):
        return self._request(
            "POST", f"/studio/portfolio-items/{item_id}/publish", {}, headers,
        )

    def takedown_portfolio_item(self, item_id, headers):
        return self._request(
            "POST", f"/studio/portfolio-items/{item_id}/takedown", {}, headers,
        )


api_client = ApiClient()
