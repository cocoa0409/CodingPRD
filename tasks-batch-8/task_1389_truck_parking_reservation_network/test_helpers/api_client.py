"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def _transport_resilient_session(session):
    """Mount retry-on-transport-error adapters on the shared session.

    The harness SIGKILLs and restarts the API server before every test
    (per-test-server isolation), and the concurrent stability sweep runs many
    rounds at once on a shared host alongside other pipelines. Residual TCP
    failure modes that survive the harness's own readiness polling:

    - a request landing in the kill-and-rebind window of a server restart
      (ECONNREFUSED / ConnectionResetError / RemoteDisconnected);
    - a connection cut by a transient, host-level event (connection reset or
      EOF before the response).

    In every case the request bytes never reached a processing server (the
    client is synchronous: a response is fully consumed before the next
    request is sent, and the Werkzeug dev server closes each connection only
    after writing a complete response), so retrying ANY method on a fresh
    connection is safe and cannot double-apply a mutation. Only transport
    errors are retried — HTTP responses (4xx/5xx) are returned untouched, so
    no assertion is affected. The retry budget (~0.75s) deliberately stays far
    below the per-test timeout.
    """
    retry = Retry(
        total=4,
        connect=4,
        read=4,
        status=0,
        other=4,
        backoff_factor=0.05,
        allowed_methods=None,  # all methods: failures here are pre-processing
        raise_on_status=False,
        respect_retry_after_header=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


class ApiClient(GenericApiClient):
    def __init__(self, base_url=None):
        super().__init__(base_url)
        _transport_resilient_session(self.session)

    # --- Sites ---
    def create_site(self, payload, headers):
        return self._request("POST", "/sites", payload, headers)

    def list_sites(self, headers, params=None):
        return self._request("GET", "/sites", headers=headers, params=params)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/sites/{site_id}", headers=headers)

    def update_site(self, site_id, payload, headers):
        return self._request("PATCH", f"/sites/{site_id}", payload, headers)

    def get_site_availability(self, site_id, headers, params=None):
        return self._request("GET", f"/sites/{site_id}/availability",
                             headers=headers, params=params)

    def get_site_forecast(self, site_id, headers, params=None):
        return self._request("GET", f"/sites/{site_id}/forecast",
                             headers=headers, params=params)

    def run_site_ops(self, site_id, headers):
        return self._request("POST", f"/sites/{site_id}/ops-run", {}, headers)

    # --- Stalls ---
    def create_stall(self, site_id, payload, headers):
        return self._request("POST", f"/sites/{site_id}/stalls", payload, headers)

    def list_stalls(self, site_id, headers, params=None):
        return self._request("GET", f"/sites/{site_id}/stalls",
                             headers=headers, params=params)

    def update_stall(self, site_id, stall_id, payload, headers):
        return self._request("PATCH", f"/sites/{site_id}/stalls/{stall_id}",
                             payload, headers)

    # --- Rate plans ---
    def create_rate_plan(self, site_id, payload, headers):
        return self._request("POST", f"/sites/{site_id}/rate-plans",
                             payload, headers)

    def list_rate_plans(self, site_id, headers, params=None):
        return self._request("GET", f"/sites/{site_id}/rate-plans",
                             headers=headers, params=params)

    def transition_rate_plan(self, site_id, rate_plan_id, payload, headers):
        return self._request(
            "POST",
            f"/sites/{site_id}/rate-plans/{rate_plan_id}/transition",
            payload, headers)

    # --- Amenity products ---
    def create_amenity_product(self, site_id, payload, headers):
        return self._request("POST", f"/sites/{site_id}/amenity-products",
                             payload, headers)

    def list_amenity_products(self, site_id, headers, params=None):
        return self._request("GET", f"/sites/{site_id}/amenity-products",
                             headers=headers, params=params)

    def update_amenity_product(self, site_id, amenity_product_id, payload, headers):
        return self._request(
            "PATCH",
            f"/sites/{site_id}/amenity-products/{amenity_product_id}",
            payload, headers)

    # --- Drivers ---
    def register_driver(self, payload, headers):
        return self._request("POST", "/drivers", payload, headers)

    def get_driver(self, driver_id, headers):
        return self._request("GET", f"/drivers/{driver_id}", headers=headers)

    # --- Fleet accounts ---
    def create_fleet_account(self, payload, headers):
        return self._request("POST", "/fleet-accounts", payload, headers)

    def get_fleet_account(self, fleet_account_id, headers):
        return self._request("GET", f"/fleet-accounts/{fleet_account_id}",
                             headers=headers)

    def close_fleet_account(self, fleet_account_id, headers):
        return self._request("POST", f"/fleet-accounts/{fleet_account_id}/close",
                             {}, headers)

    def run_fleet_ops(self, fleet_account_id, headers):
        return self._request("POST",
                             f"/fleet-accounts/{fleet_account_id}/ops-run",
                             {}, headers)

    def close_billing_period(self, fleet_account_id, payload, headers):
        return self._request(
            "POST", f"/fleet-accounts/{fleet_account_id}/close-billing-period",
            payload, headers)

    # --- Driver authorizations ---
    def create_driver_authorization(self, payload, headers):
        return self._request("POST", "/driver-authorizations", payload, headers)

    def list_driver_authorizations(self, headers, params=None):
        return self._request("GET", "/driver-authorizations",
                             headers=headers, params=params)

    def get_driver_authorization(self, auth_id, headers):
        return self._request("GET", f"/driver-authorizations/{auth_id}",
                             headers=headers)

    def transition_driver_authorization(self, auth_id, payload, headers):
        return self._request("POST",
                             f"/driver-authorizations/{auth_id}/transition",
                             payload, headers)

    # --- Bookings ---
    def create_booking(self, payload, headers):
        return self._request("POST", "/bookings", payload, headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/bookings", headers=headers, params=params)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/cancel", {}, headers)

    def check_in_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/check-in",
                             {}, headers)

    def check_out_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/check-out",
                             payload, headers)

    def extend_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/extend",
                             payload, headers)

    def pay_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/payments",
                             payload, headers)

    # --- Booking amenities ---
    def add_booking_amenity(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/amenities",
                             payload, headers)

    def list_booking_amenities(self, headers, params=None):
        return self._request("GET", "/booking-amenities",
                             headers=headers, params=params)

    def get_booking_amenity(self, amenity_line_id, headers):
        return self._request("GET", f"/booking-amenities/{amenity_line_id}",
                             headers=headers)

    def update_booking_amenity(self, amenity_line_id, payload, headers):
        return self._request("PATCH", f"/booking-amenities/{amenity_line_id}",
                             payload, headers)

    def delete_booking_amenity(self, amenity_line_id, headers):
        return self._request("DELETE", f"/booking-amenities/{amenity_line_id}",
                             headers=headers)

    # --- Waitlist entries ---
    def create_waitlist_entry(self, payload, headers):
        return self._request("POST", "/waitlist-entries", payload, headers)

    def list_waitlist_entries(self, headers, params=None):
        return self._request("GET", "/waitlist-entries",
                             headers=headers, params=params)

    def get_waitlist_entry(self, entry_id, headers):
        return self._request("GET", f"/waitlist-entries/{entry_id}",
                             headers=headers)

    def accept_waitlist_entry(self, entry_id, headers):
        return self._request("POST", f"/waitlist-entries/{entry_id}/accept",
                             {}, headers)

    def withdraw_waitlist_entry(self, entry_id, headers):
        return self._request("POST", f"/waitlist-entries/{entry_id}/withdraw",
                             {}, headers)

    # --- Incidents ---
    def create_incident(self, site_id, payload, headers):
        return self._request("POST", f"/sites/{site_id}/incidents",
                             payload, headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", "/incidents", headers=headers, params=params)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/incidents/{incident_id}", headers=headers)

    def transition_incident(self, incident_id, payload, headers):
        return self._request("POST", f"/incidents/{incident_id}/transition",
                             payload, headers)

    # --- Invoices ---
    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def pay_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/payments",
                             payload, headers)

    def dispute_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/dispute",
                             payload, headers)

    def resolve_invoice_dispute(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/resolve-dispute",
                             payload, headers)

    def write_off_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/write-off",
                             {}, headers)

    # --- Test-driving clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
