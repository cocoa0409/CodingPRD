"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Hosts ──────────────────────────────────────────────────────────
    def create_host(self, payload, headers):
        return self._request("POST", "/hosts", payload, headers)

    def get_host(self, host_id, headers):
        return self._request("GET", f"/hosts/{host_id}", headers=headers)

    def list_host_ledger(self, host_id, headers, params=None):
        return self._request("GET", f"/hosts/{host_id}/ledger", headers=headers, params=params)

    # ─── Drivers ────────────────────────────────────────────────────────
    def create_driver(self, payload, headers):
        return self._request("POST", "/drivers", payload, headers)

    def get_driver(self, driver_id, headers):
        return self._request("GET", f"/drivers/{driver_id}", headers=headers)

    def topup_wallet(self, driver_id, payload, headers):
        return self._request("POST", f"/drivers/{driver_id}/wallet/topup", payload, headers)

    def list_driver_violations(self, driver_id, headers, params=None):
        return self._request("GET", f"/drivers/{driver_id}/violations", headers=headers, params=params)

    # ─── Spots ──────────────────────────────────────────────────────────
    def create_spot(self, payload, headers):
        return self._request("POST", "/spots", payload, headers)

    def get_spot(self, spot_id, headers):
        return self._request("GET", f"/spots/{spot_id}", headers=headers)

    def list_spots(self, headers, params=None):
        return self._request("GET", "/spots", headers=headers, params=params)

    def list_spot_bookings(self, spot_id, headers, params=None):
        return self._request("GET", f"/spots/{spot_id}/bookings", headers=headers, params=params)

    def unlist_spot(self, spot_id, headers):
        return self._request("POST", f"/spots/{spot_id}/unlist", {}, headers)

    def relist_spot(self, spot_id, headers):
        return self._request("POST", f"/spots/{spot_id}/relist", {}, headers)

    # ─── Pricing Events ─────────────────────────────────────────────────
    def create_pricing_event(self, payload, headers):
        return self._request("POST", "/pricing-events", payload, headers)

    def get_pricing_event(self, event_id, headers):
        return self._request("GET", f"/pricing-events/{event_id}", headers=headers)

    def list_pricing_events(self, headers, params=None):
        return self._request("GET", "/pricing-events", headers=headers, params=params)

    def cancel_pricing_event(self, event_id, headers):
        return self._request("POST", f"/pricing-events/{event_id}/cancel", {}, headers)

    # ─── Bookings ───────────────────────────────────────────────────────
    def create_booking(self, payload, headers):
        return self._request("POST", "/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/bookings", headers=headers, params=params)

    def list_booking_transfer_offers(self, booking_id, headers, params=None):
        return self._request("GET", f"/bookings/{booking_id}/transfer-offers", headers=headers, params=params)

    def list_booking_violations(self, booking_id, headers, params=None):
        return self._request("GET", f"/bookings/{booking_id}/violations", headers=headers, params=params)

    def get_booking_access_pass(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}/access-pass", headers=headers)

    def list_booking_ledger_entries(self, booking_id, headers, params=None):
        return self._request("GET", f"/bookings/{booking_id}/ledger-entries", headers=headers, params=params)

    def check_in_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/check-in", {}, headers)

    def check_out_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/check-out", {}, headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/cancel", {}, headers)

    def mark_no_show(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/mark-no-show", {}, headers)

    def reverse_payout(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/reverse-payout", payload, headers)

    # ─── Access Passes ──────────────────────────────────────────────────
    def redeem_access_pass(self, payload, headers):
        return self._request("POST", "/access-passes/redeem", payload, headers)

    # ─── Transfer Offers ────────────────────────────────────────────────
    def create_transfer_offer(self, payload, headers):
        return self._request("POST", "/transfer-offers", payload, headers)

    def get_transfer_offer(self, offer_id, headers):
        return self._request("GET", f"/transfer-offers/{offer_id}", headers=headers)

    def list_transfer_offers(self, headers, params=None):
        return self._request("GET", "/transfer-offers", headers=headers, params=params)

    def accept_transfer_offer(self, offer_id, headers):
        return self._request("POST", f"/transfer-offers/{offer_id}/accept", {}, headers)

    def decline_transfer_offer(self, offer_id, headers):
        return self._request("POST", f"/transfer-offers/{offer_id}/decline", {}, headers)

    def withdraw_transfer_offer(self, offer_id, headers):
        return self._request("POST", f"/transfer-offers/{offer_id}/withdraw", {}, headers)

    # ─── Violations ─────────────────────────────────────────────────────
    def create_violation(self, payload, headers):
        return self._request("POST", "/violations", payload, headers)

    def get_violation(self, violation_id, headers):
        return self._request("GET", f"/violations/{violation_id}", headers=headers)

    def list_violations(self, headers, params=None):
        return self._request("GET", "/violations", headers=headers, params=params)

    def confirm_violation(self, violation_id, headers):
        return self._request("POST", f"/violations/{violation_id}/confirm", {}, headers)

    def dismiss_violation(self, violation_id, headers):
        return self._request("POST", f"/violations/{violation_id}/dismiss", {}, headers)

    # ─── Test-driving / clock ───────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
