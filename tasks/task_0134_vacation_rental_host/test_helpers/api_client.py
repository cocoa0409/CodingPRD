"""API client: one method per endpoint defined in the PRD.

All requests go through the inherited GenericApiClient._request(), which we
override here to defeat a per-test-server-restart flake: the inherited client
keeps a persistent requests.Session whose pooled connection points at the
*previous* server process after a restart. The first request on the freshly
rebooted server then reuses that dead socket and raises
ConnectionError(BadStatusLine). We send `Connection: close` so nothing is
pooled across the restart, and retry once on ConnectionError as a belt-and-
braces guard against the same-port reboot race.
"""
import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    def _request(self, method, path, payload=None, headers=None, params=None):
        merged = dict(headers or {})
        merged.setdefault("Connection", "close")
        try:
            return super()._request(method, path, payload, headers=merged, params=params)
        except requests.exceptions.ConnectionError:
            # One retry: the server was mid-restart when the first attempt fired.
            return super()._request(method, path, payload, headers=merged, params=params)

    # ---- Hosts & Guests ----
    def create_host(self, payload, headers=None):
        return self._request("POST", "/hosts", payload, headers=headers)

    def get_host(self, host_id, headers):
        return self._request("GET", f"/hosts/{host_id}", headers=headers)

    def create_guest(self, payload, headers=None):
        return self._request("POST", "/guests", payload, headers=headers)

    def get_guest(self, guest_id, headers):
        return self._request("GET", f"/guests/{guest_id}", headers=headers)

    # ---- Listings ----
    def create_listing(self, payload, headers):
        return self._request("POST", "/listings", payload, headers=headers)

    def get_listing(self, listing_id, headers):
        return self._request("GET", f"/listings/{listing_id}", headers=headers)

    def list_listings(self, headers, params=None):
        return self._request("GET", "/listings", headers=headers, params=params)

    def publish_listing(self, listing_id, headers):
        return self._request("POST", f"/listings/{listing_id}/publish", {}, headers=headers)

    def snooze_listing(self, listing_id, headers):
        return self._request("POST", f"/listings/{listing_id}/snooze", {}, headers=headers)

    def quote_listing(self, listing_id, headers, params=None):
        return self._request("GET", f"/listings/{listing_id}/quote", headers=headers, params=params)

    # ---- Rate plans ----
    def create_rate_plan(self, payload, headers):
        return self._request("POST", "/rate-plans", payload, headers=headers)

    def get_rate_plan(self, rate_plan_id, headers):
        return self._request("GET", f"/rate-plans/{rate_plan_id}", headers=headers)

    def list_rate_plans(self, headers, params=None):
        return self._request("GET", "/rate-plans", headers=headers, params=params)

    # ---- Calendar blocks ----
    def create_calendar_block(self, listing_id, payload, headers):
        return self._request("POST", f"/listings/{listing_id}/calendar-blocks", payload, headers=headers)

    def get_calendar_block(self, block_id, headers):
        return self._request("GET", f"/calendar-blocks/{block_id}", headers=headers)

    def list_calendar_blocks(self, listing_id, headers, params=None):
        return self._request("GET", f"/listings/{listing_id}/calendar-blocks", headers=headers, params=params)

    def release_calendar_block(self, listing_id, block_id, headers):
        return self._request("POST", f"/listings/{listing_id}/calendar-blocks/{block_id}/release", {}, headers=headers)

    # ---- Channel connections ----
    def create_channel_connection(self, payload, headers):
        return self._request("POST", "/channel-connections", payload, headers=headers)

    def get_channel_connection(self, cc_id, headers):
        return self._request("GET", f"/channel-connections/{cc_id}", headers=headers)

    def list_channel_connections(self, headers, params=None):
        return self._request("GET", "/channel-connections", headers=headers, params=params)

    def connect_channel(self, cc_id, headers):
        return self._request("POST", f"/channel-connections/{cc_id}/connect", {}, headers=headers)

    def sync_channel(self, cc_id, headers):
        return self._request("POST", f"/channel-connections/{cc_id}/sync", {}, headers=headers)

    def sync_complete_channel(self, cc_id, headers):
        return self._request("POST", f"/channel-connections/{cc_id}/sync-complete", {}, headers=headers)

    def sync_fail_channel(self, cc_id, headers):
        return self._request("POST", f"/channel-connections/{cc_id}/sync-fail", {}, headers=headers)

    def import_reservation(self, cc_id, payload, headers):
        return self._request("POST", f"/channel-connections/{cc_id}/imported-reservations", payload, headers=headers)

    def get_imported_reservation(self, ir_id, headers):
        return self._request("GET", f"/imported-reservations/{ir_id}", headers=headers)

    def list_channel_imported_reservations(self, cc_id, headers, params=None):
        return self._request("GET", f"/channel-connections/{cc_id}/imported-reservations", headers=headers, params=params)

    def list_imported_reservations(self, headers, params=None):
        return self._request("GET", "/imported-reservations", headers=headers, params=params)

    # ---- Bookings ----
    def create_booking(self, payload, headers):
        return self._request("POST", "/bookings", payload, headers=headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/bookings", headers=headers, params=params)

    def screen_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/screen", {}, headers=headers)

    def request_info_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/request-info", {}, headers=headers)

    def approve_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/approve", {}, headers=headers)

    def decline_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/decline", {}, headers=headers)

    def confirm_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/confirm", {}, headers=headers)

    def check_in_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/check-in", {}, headers=headers)

    def complete_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/complete", {}, headers=headers)

    def cancellation_quote(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}/cancellation-quote", headers=headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/cancel", {}, headers=headers)

    def list_booking_screening_results(self, booking_id, headers, params=None):
        return self._request("GET", f"/bookings/{booking_id}/screening-results", headers=headers, params=params)

    def get_screening_result(self, sr_id, headers):
        return self._request("GET", f"/screening-results/{sr_id}", headers=headers)

    def list_screening_results(self, headers, params=None):
        return self._request("GET", "/screening-results", headers=headers, params=params)

    # ---- Security deposits & damage claims ----
    def get_security_deposit(self, sd_id, headers):
        return self._request("GET", f"/security-deposits/{sd_id}", headers=headers)

    def list_booking_security_deposits(self, booking_id, headers, params=None):
        return self._request("GET", f"/bookings/{booking_id}/security-deposits", headers=headers, params=params)

    def file_claim(self, sd_id, payload, headers):
        return self._request("POST", f"/security-deposits/{sd_id}/claims", payload, headers=headers)

    def get_damage_claim(self, dc_id, headers):
        return self._request("GET", f"/damage-claims/{dc_id}", headers=headers)

    def list_deposit_claims(self, sd_id, headers, params=None):
        return self._request("GET", f"/security-deposits/{sd_id}/claims", headers=headers, params=params)

    def review_claim(self, dc_id, headers):
        return self._request("POST", f"/damage-claims/{dc_id}/review", {}, headers=headers)

    def approve_claim(self, dc_id, headers):
        return self._request("POST", f"/damage-claims/{dc_id}/approve", {}, headers=headers)

    def deny_claim(self, dc_id, headers):
        return self._request("POST", f"/damage-claims/{dc_id}/deny", {}, headers=headers)

    def dispute_claim(self, dc_id, headers):
        return self._request("POST", f"/damage-claims/{dc_id}/dispute", {}, headers=headers)

    # ---- Payouts ----
    def get_payout(self, payout_id, headers):
        return self._request("GET", f"/payouts/{payout_id}", headers=headers)

    def list_booking_payouts(self, booking_id, headers, params=None):
        return self._request("GET", f"/bookings/{booking_id}/payouts", headers=headers, params=params)

    def list_payouts(self, headers, params=None):
        return self._request("GET", "/payouts", headers=headers, params=params)

    def hold_payout(self, payout_id, headers):
        return self._request("POST", f"/payouts/{payout_id}/hold", {}, headers=headers)

    def unhold_payout(self, payout_id, headers):
        return self._request("POST", f"/payouts/{payout_id}/unhold", {}, headers=headers)

    def release_payout(self, payout_id, headers):
        return self._request("POST", f"/payouts/{payout_id}/release", {}, headers=headers)

    def mark_paid_payout(self, payout_id, headers):
        return self._request("POST", f"/payouts/{payout_id}/mark-paid", {}, headers=headers)

    # ---- Test-driving clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers=headers)


api_client = ApiClient()
