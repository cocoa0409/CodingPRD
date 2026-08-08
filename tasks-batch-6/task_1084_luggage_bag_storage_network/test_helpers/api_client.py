"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Host ---
    def create_host(self, payload, headers):
        return self._request("POST", "/hosts", payload, headers)

    def get_host(self, host_id, headers):
        return self._request("GET", f"/hosts/{host_id}", headers=headers)

    def set_host_status(self, host_id, payload, headers):
        return self._request("POST", f"/hosts/{host_id}/status", payload, headers)

    # --- Traveler ---
    def create_traveler(self, payload, headers=None):
        return self._request("POST", "/travelers", payload, headers)

    def get_traveler(self, traveler_id, headers):
        return self._request("GET", f"/travelers/{traveler_id}", headers=headers)

    # --- InsurancePlan ---
    def create_insurance_plan(self, payload, headers):
        return self._request("POST", "/insurance-plans", payload, headers)

    def get_insurance_plan(self, plan_id, headers):
        return self._request("GET", f"/insurance-plans/{plan_id}", headers=headers)

    # --- Location ---
    def create_location(self, host_id, payload, headers):
        return self._request("POST", f"/hosts/{host_id}/locations", payload, headers)

    def get_location(self, location_id, headers):
        return self._request("GET", f"/locations/{location_id}", headers=headers)

    def list_host_locations(self, host_id, headers, params=None):
        return self._request("GET", f"/hosts/{host_id}/locations", headers=headers, params=params)

    def set_location_status(self, location_id, payload, headers):
        return self._request("POST", f"/locations/{location_id}/status", payload, headers)

    # --- Booking ---
    def create_booking(self, payload, headers):
        return self._request("POST", "/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/bookings", headers=headers, params=params)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/cancel", {}, headers)

    def dropoff_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/dropoff", payload, headers)

    def pickup_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/pickup", payload, headers)

    # --- Bag ---
    def get_bag(self, bag_id, headers):
        return self._request("GET", f"/bags/{bag_id}", headers=headers)

    def list_booking_bags(self, booking_id, headers, params=None):
        return self._request("GET", f"/bookings/{booking_id}/bags", headers=headers, params=params)

    # --- Extension ---
    def create_extension(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/extensions", payload, headers)

    def decide_extension(self, extension_id, payload, headers):
        return self._request("POST", f"/extensions/{extension_id}/decide", payload, headers)

    def list_booking_extensions(self, booking_id, headers, params=None):
        return self._request("GET", f"/bookings/{booking_id}/extensions", headers=headers, params=params)

    # --- Claim ---
    def create_claim(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def review_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/review", {}, headers)

    def request_info_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/request-info", {}, headers)

    def resubmit_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/resubmit", {}, headers)

    def decide_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/decide", payload, headers)

    # --- Payout ---
    def get_payout(self, payout_id, headers):
        return self._request("GET", f"/payouts/{payout_id}", headers=headers)

    def list_payouts(self, headers, params=None):
        return self._request("GET", "/payouts", headers=headers, params=params)

    def release_payout(self, payout_id, headers):
        return self._request("POST", f"/payouts/{payout_id}/release", {}, headers)

    def reverse_payout(self, payout_id, headers):
        return self._request("POST", f"/payouts/{payout_id}/reverse", {}, headers)

    # --- Rating ---
    def create_rating(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/rating", payload, headers)

    def get_rating(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}/rating", headers=headers)


api_client = ApiClient()
