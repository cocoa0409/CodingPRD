"""API client: one method per endpoint defined in the PRD (§4 Endpoint Definitions)."""

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    def __init__(self, base_url=None):
        super().__init__(base_url)
        self._harden_transport()

    def _harden_transport(self):
        """Retry only at the transport layer — never on an HTTP status.

        Under `--isolation per-test-server` the runner reboots the server before
        every test and hands it an ephemeral port; a request issued in the brief
        listener-less window can self-connect on loopback and surface a
        BadStatusLine that never reached the app. Retrying dials a fresh source
        port and clears it. status_forcelist stays empty, so no real 4xx/5xx is
        ever retried and no implementation bug can be masked.
        """
        retry = Retry(
            total=5,
            connect=5,
            read=5,
            status=0,
            status_forcelist=(),
            allowed_methods=None,
            backoff_factor=0.2,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    # ─── System / clock ───────────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def run_billing_cycle(self, headers):
        return self._request("POST", "/_ops/run_billing_cycle", {}, headers)

    # ─── Member ───────────────────────────────────────────────────────────
    def create_member(self, payload, headers):
        return self._request("POST", "/club/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/club/members/{member_id}", headers=headers)

    def list_member_points_buckets(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/club/members/{member_id}/points-buckets", headers=headers, params=params
        )

    def list_member_statements(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/club/members/{member_id}/statements", headers=headers, params=params
        )

    def list_member_transfers(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/club/members/{member_id}/transfers", headers=headers, params=params
        )

    # ─── PointsBucket ─────────────────────────────────────────────────────
    def get_points_bucket(self, bucket_id, headers):
        return self._request("GET", f"/club/points-buckets/{bucket_id}", headers=headers)

    def bank_points(self, bucket_id, payload, headers):
        return self._request(
            "POST", f"/club/points-buckets/{bucket_id}/bank", payload, headers
        )

    def borrow_points(self, bucket_id, payload, headers):
        return self._request(
            "POST", f"/club/points-buckets/{bucket_id}/borrow", payload, headers
        )

    # ─── Resort / UnitType ────────────────────────────────────────────────
    def create_resort(self, payload, headers):
        return self._request("POST", "/club/resorts", payload, headers)

    def get_resort(self, resort_id, headers):
        return self._request("GET", f"/club/resorts/{resort_id}", headers=headers)

    def create_unit_type(self, resort_id, payload, headers):
        return self._request(
            "POST", f"/club/resorts/{resort_id}/unit-types", payload, headers
        )

    def list_resort_unit_types(self, resort_id, headers, params=None):
        return self._request(
            "GET", f"/club/resorts/{resort_id}/unit-types", headers=headers, params=params
        )

    def get_unit_type(self, unit_type_id, headers):
        return self._request("GET", f"/club/unit-types/{unit_type_id}", headers=headers)

    # ─── Reservation ──────────────────────────────────────────────────────
    def create_reservation(self, payload, headers):
        return self._request("POST", "/club/reservations", payload, headers)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/club/reservations/{reservation_id}", headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/club/reservations", headers=headers, params=params)

    def confirm_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/club/reservations/{reservation_id}/confirm", {}, headers
        )

    def cancel_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/club/reservations/{reservation_id}/cancel", {}, headers
        )

    # ─── Guest Certificate ────────────────────────────────────────────────
    def issue_guest_certificate(self, reservation_id, payload, headers):
        return self._request(
            "POST", f"/club/reservations/{reservation_id}/guest-certificates", payload, headers
        )

    def list_guest_certificates(self, reservation_id, headers, params=None):
        return self._request(
            "GET", f"/club/reservations/{reservation_id}/guest-certificates",
            headers=headers, params=params,
        )

    # ─── Listing ──────────────────────────────────────────────────────────
    def create_listing(self, reservation_id, payload, headers):
        return self._request(
            "POST", f"/club/reservations/{reservation_id}/listings", payload, headers
        )

    def list_listings(self, reservation_id, headers, params=None):
        return self._request(
            "GET", f"/club/reservations/{reservation_id}/listings",
            headers=headers, params=params,
        )

    # ─── Waitlist ─────────────────────────────────────────────────────────
    def create_waitlist_entry(self, payload, headers):
        return self._request("POST", "/club/waitlist-entries", payload, headers)

    def get_waitlist_entry(self, waitlist_id, headers):
        return self._request("GET", f"/club/waitlist-entries/{waitlist_id}", headers=headers)

    def list_waitlist_entries(self, headers, params=None):
        return self._request("GET", "/club/waitlist-entries", headers=headers, params=params)

    def cancel_waitlist_entry(self, waitlist_id, headers):
        return self._request(
            "POST", f"/club/waitlist-entries/{waitlist_id}/cancel", {}, headers
        )

    # ─── Statement ────────────────────────────────────────────────────────
    def generate_statement(self, member_id, payload, headers):
        return self._request(
            "POST", f"/club/members/{member_id}/statements", payload, headers
        )

    def pay_statement(self, statement_id, payload, headers):
        return self._request(
            "POST", f"/club/statements/{statement_id}/pay", payload, headers
        )

    # ─── Transfer ─────────────────────────────────────────────────────────
    def create_transfer(self, payload, headers):
        return self._request("POST", "/club/transfers", payload, headers)

    def accept_transfer(self, transfer_id, payload, headers):
        return self._request(
            "POST", f"/club/transfers/{transfer_id}/accept", payload, headers
        )


api_client = ApiClient()
