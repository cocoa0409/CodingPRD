"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; the base _request(method, path,
json_body=None, headers=None, params=None) is inherited.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Members ---
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def list_member_ledger(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/ledger", headers=headers, params=params)

    def list_member_segments(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/segments", headers=headers, params=params)

    # --- Flight segments ---
    def create_flight_segment(self, payload, headers):
        return self._request("POST", "/flight-segments", payload, headers)

    def get_flight_segment(self, segment_id, headers):
        return self._request("GET", f"/flight-segments/{segment_id}", headers=headers)

    def fly_flight_segment(self, segment_id, headers):
        return self._request("POST", f"/flight-segments/{segment_id}/fly", {}, headers)

    def accrue_flight_segment(self, segment_id, headers):
        return self._request("POST", f"/flight-segments/{segment_id}/accrue", {}, headers)

    def cancel_flight_segment(self, segment_id, headers):
        return self._request("POST", f"/flight-segments/{segment_id}/cancel", {}, headers)

    # --- Award bookings ---
    def create_award_booking(self, payload, headers):
        return self._request("POST", "/award-bookings", payload, headers)

    def get_award_booking(self, award_id, headers):
        return self._request("GET", f"/award-bookings/{award_id}", headers=headers)

    def list_award_bookings(self, headers, params=None):
        return self._request("GET", "/award-bookings", headers=headers, params=params)

    def issue_award_booking(self, award_id, headers):
        return self._request("POST", f"/award-bookings/{award_id}/issue", {}, headers)

    def cancel_award_booking(self, award_id, headers):
        return self._request("POST", f"/award-bookings/{award_id}/cancel", {}, headers)

    def fly_award_booking(self, award_id, headers):
        return self._request("POST", f"/award-bookings/{award_id}/fly", {}, headers)

    # --- Flight pools ---
    def create_flight_pool(self, payload, headers):
        return self._request("POST", "/flight-pools", payload, headers)

    def get_flight_pool(self, pool_id, headers):
        return self._request("GET", f"/flight-pools/{pool_id}", headers=headers)

    def list_pool_upgrade_requests(self, pool_id, headers, params=None):
        return self._request("GET", f"/flight-pools/{pool_id}/upgrade-requests", headers=headers, params=params)

    def clear_waitlist(self, pool_id, headers):
        return self._request("POST", f"/flight-pools/{pool_id}/clear-waitlist", {}, headers)

    # --- Upgrade requests ---
    def create_upgrade_request(self, payload, headers):
        return self._request("POST", "/upgrade-requests", payload, headers)

    def get_upgrade_request(self, request_id, headers):
        return self._request("GET", f"/upgrade-requests/{request_id}", headers=headers)

    def list_upgrade_requests(self, headers, params=None):
        return self._request("GET", "/upgrade-requests", headers=headers, params=params)

    def withdraw_upgrade_request(self, request_id, headers):
        return self._request("POST", f"/upgrade-requests/{request_id}/withdraw", {}, headers)

    # --- Companion certificates ---
    def create_companion_certificate(self, payload, headers):
        return self._request("POST", "/companion-certificates", payload, headers)

    def get_companion_certificate(self, cert_id, headers):
        return self._request("GET", f"/companion-certificates/{cert_id}", headers=headers)

    def list_companion_certificates(self, headers, params=None):
        return self._request("GET", "/companion-certificates", headers=headers, params=params)

    # --- Points gifts ---
    def create_points_gift(self, payload, headers):
        return self._request("POST", "/points-gifts", payload, headers)

    def get_points_gift(self, gift_id, headers):
        return self._request("GET", f"/points-gifts/{gift_id}", headers=headers)

    def list_points_gifts(self, headers, params=None):
        return self._request("GET", "/points-gifts", headers=headers, params=params)

    def settle_points_gift(self, gift_id, payload, headers):
        return self._request("POST", f"/points-gifts/{gift_id}/settle", payload, headers)

    def reverse_points_gift(self, gift_id, headers):
        return self._request("POST", f"/points-gifts/{gift_id}/reverse", {}, headers)

    # --- Status matches ---
    def create_status_match(self, payload, headers):
        return self._request("POST", "/status-matches", payload, headers)

    def get_status_match(self, match_id, headers):
        return self._request("GET", f"/status-matches/{match_id}", headers=headers)

    def list_status_matches(self, headers, params=None):
        return self._request("GET", "/status-matches", headers=headers, params=params)

    # --- Clock & test-seeding ---
    def advance_clock(self, current_utc, headers):
        return self._request("POST", "/_clock/advance", {"current_utc": current_utc}, headers)

    def get_clock(self, headers):
        return self._request("GET", "/_clock", headers=headers)

    def inject_points(self, member_id, amount, headers):
        return self._request("POST", "/_inject/points", {"member_id": member_id, "amount": amount}, headers)

    def inject_qualifying_segments(self, member_id, count, headers):
        return self._request("POST", "/_inject/qualifying_segments", {"member_id": member_id, "count": count}, headers)


api_client = ApiClient()
