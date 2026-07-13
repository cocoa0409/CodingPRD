"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Users & verification ---
    def create_user(self, payload, headers=None):
        return self._request("POST", "/users", payload, headers)

    def get_user(self, user_id, headers):
        return self._request("GET", f"/users/{user_id}", headers=headers)

    def create_verification(self, user_id, payload, headers):
        return self._request("POST", f"/users/{user_id}/verifications", payload, headers)

    def list_user_verifications(self, user_id, headers, params=None):
        return self._request("GET", f"/users/{user_id}/verifications", headers=headers, params=params)

    def decide_verification(self, verification_id, payload, headers):
        return self._request("POST", f"/verifications/{verification_id}/decide", payload, headers)

    # --- Listings ---
    def create_listing(self, payload, headers):
        return self._request("POST", "/listings", payload, headers)

    def get_listing(self, listing_id, headers):
        return self._request("GET", f"/listings/{listing_id}", headers=headers)

    def list_user_listings(self, user_id, headers, params=None):
        return self._request("GET", f"/users/{user_id}/listings", headers=headers, params=params)

    def update_listing(self, listing_id, payload, headers):
        return self._request("PATCH", f"/listings/{listing_id}", payload, headers)

    def activate_listing(self, listing_id, headers):
        return self._request("POST", f"/listings/{listing_id}/activate", {}, headers)

    def suspend_listing(self, listing_id, headers):
        return self._request("POST", f"/listings/{listing_id}/suspend", {}, headers)

    # --- Bookings ---
    def create_booking(self, payload, headers):
        return self._request("POST", "/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/bookings", headers=headers, params=params)

    def get_quote(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}/quote", headers=headers)

    def approve_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/approve", {}, headers)

    def decline_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/decline", {}, headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/cancel", {}, headers)

    def pickup_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/pickup", {}, headers)

    def return_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/return", {}, headers)

    def request_extension(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/extensions", payload, headers)

    def decide_extension(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/extension-decision", payload, headers)

    # --- Handoffs ---
    def create_handoff(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/handoffs", payload, headers)

    def list_booking_handoffs(self, booking_id, headers, params=None):
        return self._request("GET", f"/bookings/{booking_id}/handoffs", headers=headers, params=params)

    def list_user_handoffs(self, user_id, headers, params=None):
        return self._request("GET", f"/users/{user_id}/handoffs", headers=headers, params=params)

    def complete_handoff(self, handoff_id, headers):
        return self._request("POST", f"/handoffs/{handoff_id}/complete", {}, headers)

    # --- Condition reports ---
    def create_condition_report(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/condition-reports", payload, headers)

    def list_condition_reports(self, booking_id, headers, params=None):
        return self._request("GET", f"/bookings/{booking_id}/condition-reports", headers=headers, params=params)

    # --- Claims ---
    def create_claim(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/claims", payload, headers)

    def list_claims(self, booking_id, headers, params=None):
        return self._request("GET", f"/bookings/{booking_id}/claims", headers=headers, params=params)

    def review_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/review", {}, headers)

    def resolve_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/resolve", payload, headers)

    # --- Deposit / payout ---
    def get_deposit(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}/deposit", headers=headers)

    def release_payout(self, payout_id, headers):
        return self._request("POST", f"/payouts/{payout_id}/release", {}, headers)

    def get_payout(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}/payout", headers=headers)

    def list_user_payouts(self, user_id, headers, params=None):
        return self._request("GET", f"/users/{user_id}/payouts", headers=headers, params=params)

    # --- Ratings ---
    def create_rating(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/ratings", payload, headers)

    def list_booking_ratings(self, booking_id, headers, params=None):
        return self._request("GET", f"/bookings/{booking_id}/ratings", headers=headers, params=params)

    def list_user_ratings(self, user_id, headers, params=None):
        return self._request("GET", f"/users/{user_id}/ratings", headers=headers, params=params)

    # --- Ops / clock (Platform) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def detect_late_returns(self, headers):
        return self._request("POST", "/_ops/detect-late-returns", {}, headers)


api_client = ApiClient()
