"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Members -------------------------------------------------------------
    def register_member(self, payload, headers):
        return self._request("POST", "/members/register", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def create_points_adjustment(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/points-adjustments", payload, headers)

    def list_ledger_entries(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/ledger-entries", headers=headers, params=params)

    def list_memberships(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/memberships", headers=headers, params=params)

    def list_member_home_listings(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/home-listings", headers=headers, params=params)

    def list_member_verifications(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/verifications", headers=headers, params=params)

    def list_member_exchange_requests(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/exchange-requests", headers=headers, params=params)

    # --- Memberships ---------------------------------------------------------
    def create_membership(self, payload, headers):
        return self._request("POST", "/memberships", payload, headers)

    def activate_membership(self, membership_id, headers):
        return self._request("POST", f"/memberships/{membership_id}/activate", headers=headers)

    def cancel_membership(self, membership_id, headers):
        return self._request("POST", f"/memberships/{membership_id}/cancel", headers=headers)

    # --- Verifications -------------------------------------------------------
    def create_verification(self, payload, headers):
        return self._request("POST", "/verifications", payload, headers)

    def decide_verification(self, verification_id, payload, headers):
        return self._request("POST", f"/verifications/{verification_id}/decide", payload, headers)

    # --- Home Listings -------------------------------------------------------
    def create_home_listing(self, payload, headers):
        return self._request("POST", "/home-listings", payload, headers)

    def get_home_listing(self, listing_id, headers):
        return self._request("GET", f"/home-listings/{listing_id}", headers=headers)

    def activate_home_listing(self, listing_id, headers):
        return self._request("POST", f"/home-listings/{listing_id}/activate", headers=headers)

    def create_availability_window(self, listing_id, payload, headers):
        return self._request("POST", f"/home-listings/{listing_id}/availability-windows", payload, headers)

    def list_availability_windows(self, listing_id, headers, params=None):
        return self._request("GET", f"/home-listings/{listing_id}/availability-windows", headers=headers, params=params)

    def list_listing_exchange_requests(self, listing_id, headers, params=None):
        return self._request("GET", f"/home-listings/{listing_id}/exchange-requests", headers=headers, params=params)

    def get_availability_window(self, window_id, headers):
        return self._request("GET", f"/availability-windows/{window_id}", headers=headers)

    # --- Exchange Requests ---------------------------------------------------
    def create_exchange_request(self, payload, headers):
        return self._request("POST", "/exchange-requests", payload, headers)

    def get_exchange_request(self, request_id, headers):
        return self._request("GET", f"/exchange-requests/{request_id}", headers=headers)

    def counter_exchange_request(self, request_id, payload, headers):
        return self._request("POST", f"/exchange-requests/{request_id}/counter", payload, headers)

    def repropose_exchange_request(self, request_id, payload, headers):
        return self._request("POST", f"/exchange-requests/{request_id}/repropose", payload, headers)

    def accept_exchange_request(self, request_id, payload, headers):
        return self._request("POST", f"/exchange-requests/{request_id}/accept", payload, headers)

    def decline_exchange_request(self, request_id, headers):
        return self._request("POST", f"/exchange-requests/{request_id}/decline", headers=headers)

    def withdraw_exchange_request(self, request_id, headers):
        return self._request("POST", f"/exchange-requests/{request_id}/withdraw", headers=headers)

    # --- Exchange Agreements -------------------------------------------------
    def get_exchange_agreement(self, agreement_id, headers):
        return self._request("GET", f"/exchange-agreements/{agreement_id}", headers=headers)

    def list_exchange_agreements(self, headers, params=None):
        return self._request("GET", "/exchange-agreements", headers=headers, params=params)

    def list_agreement_ledger_entries(self, agreement_id, headers, params=None):
        return self._request("GET", f"/exchange-agreements/{agreement_id}/ledger-entries", headers=headers, params=params)

    def confirm_agreement(self, agreement_id, headers):
        return self._request("POST", f"/exchange-agreements/{agreement_id}/confirm", headers=headers)

    def start_agreement(self, agreement_id, headers):
        return self._request("POST", f"/exchange-agreements/{agreement_id}/start", headers=headers)

    def complete_agreement(self, agreement_id, headers):
        return self._request("POST", f"/exchange-agreements/{agreement_id}/complete", headers=headers)

    def cancel_agreement(self, agreement_id, headers):
        return self._request("POST", f"/exchange-agreements/{agreement_id}/cancel", headers=headers)

    def create_damage_claim(self, agreement_id, payload, headers):
        return self._request("POST", f"/exchange-agreements/{agreement_id}/damage-claims", payload, headers)

    def create_dispute(self, agreement_id, payload, headers):
        return self._request("POST", f"/exchange-agreements/{agreement_id}/disputes", payload, headers)

    # --- Damage Claims -------------------------------------------------------
    def get_damage_claim(self, claim_id, headers):
        return self._request("GET", f"/damage-claims/{claim_id}", headers=headers)

    def list_damage_claims(self, headers, params=None):
        return self._request("GET", "/damage-claims", headers=headers, params=params)

    def adjudicate_damage_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/damage-claims/{claim_id}/adjudicate", payload, headers)

    # --- Disputes ------------------------------------------------------------
    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/disputes/{dispute_id}", headers=headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/disputes", headers=headers, params=params)

    def review_dispute(self, dispute_id, headers):
        return self._request("POST", f"/disputes/{dispute_id}/review", headers=headers)

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/disputes/{dispute_id}/resolve", payload, headers)

    # --- Logical clock -------------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
