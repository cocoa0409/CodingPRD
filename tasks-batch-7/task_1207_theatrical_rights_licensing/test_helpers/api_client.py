"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving capability, PRD §2.5)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST",
            "/licensing/_clock/set_current_utc",
            {"to_iso8601": to_iso8601},
            headers,
        )

    # ------------------------------------------------------------------
    # Titles & territory restrictions
    # ------------------------------------------------------------------
    def create_title(self, payload, headers):
        return self._request("POST", "/licensing/titles", payload, headers)

    def get_title(self, title_id, headers):
        return self._request("GET", f"/licensing/titles/{title_id}", headers=headers)

    def list_titles(self, headers, params=None):
        return self._request("GET", "/licensing/titles", headers=headers, params=params)

    def withdraw_title(self, title_id, headers):
        return self._request(
            "POST", f"/licensing/titles/{title_id}/withdraw", {}, headers
        )

    def create_restriction(self, title_id, payload, headers):
        return self._request(
            "POST", f"/licensing/titles/{title_id}/restrictions", payload, headers
        )

    def list_title_restrictions(self, title_id, headers, params=None):
        return self._request(
            "GET",
            f"/licensing/titles/{title_id}/restrictions",
            headers=headers,
            params=params,
        )

    def get_restriction(self, restriction_id, headers):
        return self._request(
            "GET", f"/licensing/restrictions/{restriction_id}", headers=headers
        )

    def list_restrictions(self, headers, params=None):
        return self._request(
            "GET", "/licensing/restrictions", headers=headers, params=params
        )

    def lift_restriction(self, restriction_id, headers):
        return self._request(
            "POST", f"/licensing/restrictions/{restriction_id}/lift", {}, headers
        )

    # ------------------------------------------------------------------
    # Organizations
    # ------------------------------------------------------------------
    def create_organization(self, payload, headers):
        return self._request("POST", "/licensing/organizations", payload, headers)

    def get_organization(self, organization_id, headers):
        return self._request(
            "GET", f"/licensing/organizations/{organization_id}", headers=headers
        )

    def list_organizations(self, headers, params=None):
        return self._request(
            "GET", "/licensing/organizations", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # License applications
    # ------------------------------------------------------------------
    def create_application(self, payload, headers):
        return self._request("POST", "/licensing/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request(
            "GET", f"/licensing/applications/{application_id}", headers=headers
        )

    def list_applications(self, headers, params=None):
        return self._request(
            "GET", "/licensing/applications", headers=headers, params=params
        )

    def patch_application(self, application_id, payload, headers):
        return self._request(
            "PATCH", f"/licensing/applications/{application_id}", payload, headers
        )

    def submit_application(self, application_id, headers):
        return self._request(
            "POST", f"/licensing/applications/{application_id}/submit", {}, headers
        )

    def begin_review_application(self, application_id, headers):
        return self._request(
            "POST",
            f"/licensing/applications/{application_id}/begin_review",
            {},
            headers,
        )

    def return_for_info_application(self, application_id, payload, headers):
        return self._request(
            "POST",
            f"/licensing/applications/{application_id}/return_for_info",
            payload,
            headers,
        )

    def approve_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/licensing/applications/{application_id}/approve", payload, headers
        )

    def reject_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/licensing/applications/{application_id}/reject", payload, headers
        )

    def get_application_availability(self, application_id, headers):
        return self._request(
            "GET",
            f"/licensing/applications/{application_id}/availability",
            headers=headers,
        )

    # ------------------------------------------------------------------
    # License agreements
    # ------------------------------------------------------------------
    def get_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"/licensing/agreements/{agreement_id}", headers=headers
        )

    def list_agreements(self, headers, params=None):
        return self._request(
            "GET", "/licensing/agreements", headers=headers, params=params
        )

    def activate_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/licensing/agreements/{agreement_id}/activate", {}, headers
        )

    def create_payment(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/licensing/agreements/{agreement_id}/payments", payload, headers
        )

    def list_agreement_payments(self, agreement_id, headers, params=None):
        return self._request(
            "GET",
            f"/licensing/agreements/{agreement_id}/payments",
            headers=headers,
            params=params,
        )

    def list_payments(self, headers, params=None):
        return self._request("GET", "/licensing/payments", headers=headers, params=params)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/licensing/payments/{payment_id}", headers=headers)

    def create_performance(self, agreement_id, payload, headers):
        return self._request(
            "POST",
            f"/licensing/agreements/{agreement_id}/performances",
            payload,
            headers,
        )

    def list_agreement_performances(self, agreement_id, headers, params=None):
        return self._request(
            "GET",
            f"/licensing/agreements/{agreement_id}/performances",
            headers=headers,
            params=params,
        )

    def create_amendment(self, agreement_id, payload, headers):
        return self._request(
            "POST",
            f"/licensing/agreements/{agreement_id}/amendments",
            payload,
            headers,
        )

    def cancel_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/licensing/agreements/{agreement_id}/cancel", payload, headers
        )

    def declare_breach(self, agreement_id, payload, headers):
        return self._request(
            "POST",
            f"/licensing/agreements/{agreement_id}/declare_breach",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Performances
    # ------------------------------------------------------------------
    def get_performance(self, performance_id, headers):
        return self._request(
            "GET", f"/licensing/performances/{performance_id}", headers=headers
        )

    def list_performances(self, headers, params=None):
        return self._request(
            "GET", "/licensing/performances", headers=headers, params=params
        )

    def report_performance(self, performance_id, payload, headers):
        return self._request(
            "POST",
            f"/licensing/performances/{performance_id}/report",
            payload,
            headers,
        )

    def cancel_performance(self, performance_id, headers):
        return self._request(
            "POST", f"/licensing/performances/{performance_id}/cancel", {}, headers
        )

    # ------------------------------------------------------------------
    # Material rentals
    # ------------------------------------------------------------------
    def create_rental(self, payload, headers):
        return self._request("POST", "/licensing/rentals", payload, headers)

    def get_rental(self, rental_id, headers):
        return self._request("GET", f"/licensing/rentals/{rental_id}", headers=headers)

    def list_rentals(self, headers, params=None):
        return self._request("GET", "/licensing/rentals", headers=headers, params=params)

    def ship_rental(self, rental_id, headers):
        return self._request(
            "POST", f"/licensing/rentals/{rental_id}/ship", {}, headers
        )

    def mark_received_rental(self, rental_id, headers):
        return self._request(
            "POST", f"/licensing/rentals/{rental_id}/mark_received", {}, headers
        )

    def ship_return_rental(self, rental_id, headers):
        return self._request(
            "POST", f"/licensing/rentals/{rental_id}/ship_return", {}, headers
        )

    def receive_return_rental(self, rental_id, payload, headers):
        return self._request(
            "POST", f"/licensing/rentals/{rental_id}/receive_return", payload, headers
        )

    def declare_lost_rental(self, rental_id, headers):
        return self._request(
            "POST", f"/licensing/rentals/{rental_id}/declare_lost", {}, headers
        )

    # ------------------------------------------------------------------
    # Alteration requests
    # ------------------------------------------------------------------
    def create_alteration_request(self, payload, headers):
        return self._request("POST", "/licensing/alteration-requests", payload, headers)

    def get_alteration_request(self, request_id, headers):
        return self._request(
            "GET", f"/licensing/alteration-requests/{request_id}", headers=headers
        )

    def list_alteration_requests(self, headers, params=None):
        return self._request(
            "GET", "/licensing/alteration-requests", headers=headers, params=params
        )

    def approve_alteration_request(self, request_id, headers):
        return self._request(
            "POST", f"/licensing/alteration-requests/{request_id}/approve", {}, headers
        )

    def deny_alteration_request(self, request_id, headers):
        return self._request(
            "POST", f"/licensing/alteration-requests/{request_id}/deny", {}, headers
        )

    # ------------------------------------------------------------------
    # Recording grants
    # ------------------------------------------------------------------
    def create_recording_grant(self, payload, headers):
        return self._request("POST", "/licensing/recording-grants", payload, headers)

    def get_recording_grant(self, grant_id, headers):
        return self._request(
            "GET", f"/licensing/recording-grants/{grant_id}", headers=headers
        )

    def list_recording_grants(self, headers, params=None):
        return self._request(
            "GET", "/licensing/recording-grants", headers=headers, params=params
        )

    def approve_recording_grant(self, grant_id, headers):
        return self._request(
            "POST", f"/licensing/recording-grants/{grant_id}/approve", {}, headers
        )

    def deny_recording_grant(self, grant_id, headers):
        return self._request(
            "POST", f"/licensing/recording-grants/{grant_id}/deny", {}, headers
        )

    def mark_exercised_recording_grant(self, grant_id, headers):
        return self._request(
            "POST",
            f"/licensing/recording-grants/{grant_id}/mark_exercised",
            {},
            headers,
        )

    # ------------------------------------------------------------------
    # Fines
    # ------------------------------------------------------------------
    def get_fine(self, fine_id, headers):
        return self._request("GET", f"/licensing/fines/{fine_id}", headers=headers)

    def list_fines(self, headers, params=None):
        return self._request("GET", "/licensing/fines", headers=headers, params=params)

    def pay_fine(self, fine_id, headers):
        return self._request("POST", f"/licensing/fines/{fine_id}/pay", {}, headers)

    def waive_fine(self, fine_id, headers):
        return self._request("POST", f"/licensing/fines/{fine_id}/waive", {}, headers)

    def write_off_fine(self, fine_id, headers):
        return self._request(
            "POST", f"/licensing/fines/{fine_id}/write_off", {}, headers
        )

    # ------------------------------------------------------------------
    # Availability snapshots
    # ------------------------------------------------------------------
    def list_availability_snapshots(self, headers, params=None):
        return self._request(
            "GET", "/licensing/availability-snapshots", headers=headers, params=params
        )

    def get_availability_snapshot(self, snapshot_id, headers):
        return self._request(
            "GET",
            f"/licensing/availability-snapshots/{snapshot_id}",
            headers=headers,
        )


api_client = ApiClient()
