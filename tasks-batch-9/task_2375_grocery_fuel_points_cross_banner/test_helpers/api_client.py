"""API client: one method per endpoint defined in the PRD.

Every collection is mounted at the server root as a peer top-level path, so no
path is nested under an owning parent; the three nested list paths that do exist
are reverse-lookup channels over foreign keys.
"""
from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601: str, headers=None):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ------------------------------------------------------------------
    # Banners
    # ------------------------------------------------------------------
    def create_banner(self, payload: dict, headers=None):
        return self._request("POST", "/banners", payload, headers)

    def get_banner(self, banner_id: str, headers=None):
        return self._request("GET", f"/banners/{banner_id}", headers=headers)

    def suspend_banner(self, banner_id: str, headers=None):
        return self._request("POST", f"/banners/{banner_id}/suspend", {}, headers)

    def list_banner_promo_events(self, banner_id: str, headers=None, params: Optional[dict] = None):
        return self._request(
            "GET", f"/banners/{banner_id}/promo-events", headers=headers, params=params
        )

    def list_banner_households(self, banner_id: str, headers=None, params: Optional[dict] = None):
        return self._request(
            "GET", f"/banners/{banner_id}/households", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Sites
    # ------------------------------------------------------------------
    def create_site(self, payload: dict, headers=None):
        return self._request("POST", "/sites", payload, headers)

    def get_site(self, site_id: str, headers=None):
        return self._request("GET", f"/sites/{site_id}", headers=headers)

    def list_sites(self, headers=None, params: Optional[dict] = None):
        return self._request("GET", "/sites", headers=headers, params=params)

    def suspend_site(self, site_id: str, headers=None):
        return self._request("POST", f"/sites/{site_id}/suspend", {}, headers)

    # ------------------------------------------------------------------
    # Households
    # ------------------------------------------------------------------
    def create_household(self, payload: dict, headers=None):
        return self._request("POST", "/households", payload, headers)

    def get_household(self, household_id: str, headers=None):
        return self._request("GET", f"/households/{household_id}", headers=headers)

    def list_household_fraud_signals(
        self, household_id: str, headers=None, params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"/households/{household_id}/fraud-signals", headers=headers, params=params
        )

    def freeze_household(self, household_id: str, headers=None):
        return self._request("POST", f"/households/{household_id}/freeze", {}, headers)

    def unfreeze_household(self, household_id: str, headers=None):
        return self._request("POST", f"/households/{household_id}/unfreeze", {}, headers)

    # ------------------------------------------------------------------
    # Members
    # ------------------------------------------------------------------
    def create_member(self, payload: dict, headers=None):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id: str, headers=None):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def list_members(self, headers=None, params: Optional[dict] = None):
        return self._request("GET", "/members", headers=headers, params=params)

    def get_points_summary(self, member_id: str, headers=None):
        return self._request("GET", f"/members/{member_id}/points-summary", headers=headers)

    # ------------------------------------------------------------------
    # Household linkages
    # ------------------------------------------------------------------
    def create_household_link(self, payload: dict, headers=None):
        return self._request("POST", "/household-links", payload, headers)

    def get_household_link(self, link_id: str, headers=None):
        return self._request("GET", f"/household-links/{link_id}", headers=headers)

    def list_household_links(self, headers=None, params: Optional[dict] = None):
        return self._request("GET", "/household-links", headers=headers, params=params)

    def activate_household_link(self, link_id: str, headers=None):
        return self._request("POST", f"/household-links/{link_id}/activate", {}, headers)

    def suspend_household_link(self, link_id: str, headers=None):
        return self._request("POST", f"/household-links/{link_id}/suspend", {}, headers)

    def revoke_household_link(self, link_id: str, headers=None):
        return self._request("POST", f"/household-links/{link_id}/revoke", {}, headers)

    # ------------------------------------------------------------------
    # Promotional events
    # ------------------------------------------------------------------
    def create_promo_event(self, payload: dict, headers=None):
        return self._request("POST", "/promo-events", payload, headers)

    def activate_promo_event(self, promo_event_id: str, headers=None):
        return self._request("POST", f"/promo-events/{promo_event_id}/activate", {}, headers)

    # ------------------------------------------------------------------
    # Point cycles
    # ------------------------------------------------------------------
    def create_point_cycle(self, payload: dict, headers=None):
        return self._request("POST", "/point-cycles", payload, headers)

    def get_point_cycle(self, cycle_id: str, headers=None):
        return self._request("GET", f"/point-cycles/{cycle_id}", headers=headers)

    def list_point_cycles(self, headers=None, params: Optional[dict] = None):
        return self._request("GET", "/point-cycles", headers=headers, params=params)

    def begin_close_point_cycle(self, cycle_id: str, headers=None):
        return self._request("POST", f"/point-cycles/{cycle_id}/begin-close", {}, headers)

    def close_point_cycle(self, cycle_id: str, headers=None):
        return self._request("POST", f"/point-cycles/{cycle_id}/close", {}, headers)

    # ------------------------------------------------------------------
    # Purchase transactions
    # ------------------------------------------------------------------
    def create_purchase_transaction(self, payload: dict, headers=None):
        return self._request("POST", "/purchase-transactions", payload, headers)

    def get_purchase_transaction(self, transaction_id: str, headers=None):
        return self._request("GET", f"/purchase-transactions/{transaction_id}", headers=headers)

    def list_purchase_transactions(self, headers=None, params: Optional[dict] = None):
        return self._request("GET", "/purchase-transactions", headers=headers, params=params)

    def post_purchase_transaction(self, transaction_id: str, headers=None):
        return self._request(
            "POST", f"/purchase-transactions/{transaction_id}/post", {}, headers
        )

    def void_purchase_transaction(self, transaction_id: str, headers=None):
        return self._request(
            "POST", f"/purchase-transactions/{transaction_id}/void", {}, headers
        )

    # ------------------------------------------------------------------
    # Point ledger entries
    # ------------------------------------------------------------------
    def get_point_ledger_entry(self, entry_id: str, headers=None):
        return self._request("GET", f"/point-ledger-entries/{entry_id}", headers=headers)

    def list_point_ledger_entries(self, headers=None, params: Optional[dict] = None):
        return self._request("GET", "/point-ledger-entries", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Point transfers
    # ------------------------------------------------------------------
    def create_point_transfer(self, payload: dict, headers=None):
        return self._request("POST", "/point-transfers", payload, headers)

    # ------------------------------------------------------------------
    # Fuel redemptions
    # ------------------------------------------------------------------
    def create_fuel_redemption(self, payload: dict, headers=None):
        return self._request("POST", "/fuel-redemptions", payload, headers)

    def get_fuel_redemption(self, redemption_id: str, headers=None):
        return self._request("GET", f"/fuel-redemptions/{redemption_id}", headers=headers)

    def list_fuel_redemptions(self, headers=None, params: Optional[dict] = None):
        return self._request("GET", "/fuel-redemptions", headers=headers, params=params)

    def complete_fuel_redemption(self, redemption_id: str, payload: dict, headers=None):
        return self._request(
            "POST", f"/fuel-redemptions/{redemption_id}/complete", payload, headers
        )

    def void_fuel_redemption(self, redemption_id: str, headers=None):
        return self._request("POST", f"/fuel-redemptions/{redemption_id}/void", {}, headers)

    # ------------------------------------------------------------------
    # Settlement batches
    # ------------------------------------------------------------------
    def create_settlement_batch(self, payload: dict, headers=None):
        return self._request("POST", "/settlement-batches", payload, headers)

    def get_settlement_batch(self, batch_id: str, headers=None):
        return self._request("GET", f"/settlement-batches/{batch_id}", headers=headers)

    def list_settlement_batches(self, headers=None, params: Optional[dict] = None):
        return self._request("GET", "/settlement-batches", headers=headers, params=params)

    def submit_settlement_batch(self, batch_id: str, headers=None):
        return self._request("POST", f"/settlement-batches/{batch_id}/submit", {}, headers)

    def approve_settlement_batch(self, batch_id: str, headers=None):
        return self._request("POST", f"/settlement-batches/{batch_id}/approve", {}, headers)

    def reject_settlement_batch(self, batch_id: str, headers=None):
        return self._request("POST", f"/settlement-batches/{batch_id}/reject", {}, headers)

    # ------------------------------------------------------------------
    # Point disputes
    # ------------------------------------------------------------------
    def create_point_dispute(self, payload: dict, headers=None):
        return self._request("POST", "/point-disputes", payload, headers)

    def get_point_dispute(self, dispute_id: str, headers=None):
        return self._request("GET", f"/point-disputes/{dispute_id}", headers=headers)

    def list_point_disputes(self, headers=None, params: Optional[dict] = None):
        return self._request("GET", "/point-disputes", headers=headers, params=params)

    def investigate_point_dispute(self, dispute_id: str, headers=None):
        return self._request("POST", f"/point-disputes/{dispute_id}/investigate", {}, headers)

    def propose_dispute_adjustment(self, dispute_id: str, payload: dict, headers=None):
        return self._request(
            "POST", f"/point-disputes/{dispute_id}/propose-adjustment", payload, headers
        )

    def approve_dispute_adjustment(self, dispute_id: str, headers=None):
        return self._request(
            "POST", f"/point-disputes/{dispute_id}/approve-adjustment", {}, headers
        )

    def deny_point_dispute(self, dispute_id: str, headers=None):
        return self._request("POST", f"/point-disputes/{dispute_id}/deny", {}, headers)

    # ------------------------------------------------------------------
    # Fraud signals
    # ------------------------------------------------------------------
    def create_fraud_signal(self, payload: dict, headers=None):
        return self._request("POST", "/fraud-signals", payload, headers)

    def clear_fraud_signal(self, signal_id: str, headers=None):
        return self._request("POST", f"/fraud-signals/{signal_id}/clear", {}, headers)


api_client = ApiClient()
