"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- accounts ---
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def verify_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/verify", {}, headers)

    # --- skus ---
    def create_sku(self, payload, headers):
        return self._request("POST", "/skus", payload, headers)

    def get_sku(self, sku_id, headers):
        return self._request("GET", f"/skus/{sku_id}", headers=headers)

    # --- authenticators ---
    def create_authenticator(self, payload, headers):
        return self._request("POST", "/authenticators", payload, headers)

    def get_authenticator(self, authenticator_id, headers):
        return self._request("GET", f"/authenticators/{authenticator_id}", headers=headers)

    # --- releases & raffle ---
    def create_release(self, payload, headers):
        return self._request("POST", "/releases", payload, headers)

    def get_release(self, release_id, headers):
        return self._request("GET", f"/releases/{release_id}", headers=headers)

    def list_releases(self, headers, params=None):
        return self._request("GET", "/releases", headers=headers, params=params)

    def open_release(self, release_id, headers):
        return self._request("POST", f"/releases/{release_id}/open", {}, headers)

    def draw_release(self, release_id, payload, headers):
        return self._request("POST", f"/releases/{release_id}/draw", payload, headers)

    def settle_release(self, release_id, headers):
        return self._request("POST", f"/releases/{release_id}/settle", {}, headers)

    def cancel_release(self, release_id, headers):
        return self._request("POST", f"/releases/{release_id}/cancel", {}, headers)

    def enter_release(self, release_id, headers):
        return self._request("POST", f"/releases/{release_id}/enter", {}, headers)

    # --- raffle entries ---
    def get_raffle_entry(self, entry_id, headers):
        return self._request("GET", f"/raffle-entries/{entry_id}", headers=headers)

    def list_raffle_entries(self, headers, params=None):
        return self._request("GET", "/raffle-entries", headers=headers, params=params)

    def claim_entry(self, entry_id, headers):
        return self._request("POST", f"/raffle-entries/{entry_id}/claim", {}, headers)

    # --- listings ---
    def create_listing(self, payload, headers):
        return self._request("POST", "/listings", payload, headers)

    def get_listing(self, listing_id, headers):
        return self._request("GET", f"/listings/{listing_id}", headers=headers)

    def list_listings(self, headers, params=None):
        return self._request("GET", "/listings", headers=headers, params=params)

    def reprice_listing(self, listing_id, payload, headers):
        return self._request("POST", f"/listings/{listing_id}/reprice", payload, headers)

    def buy_listing(self, listing_id, headers):
        return self._request("POST", f"/listings/{listing_id}/buy", {}, headers)

    def match_listing(self, listing_id, payload, headers):
        return self._request("POST", f"/listings/{listing_id}/match", payload, headers)

    # --- bids ---
    def create_bid(self, payload, headers):
        return self._request("POST", "/bids", payload, headers)

    def get_bid(self, bid_id, headers):
        return self._request("GET", f"/bids/{bid_id}", headers=headers)

    def list_bids(self, headers, params=None):
        return self._request("GET", "/bids", headers=headers, params=params)

    # --- orders ---
    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def ship_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/ship-to-buyer", {}, headers)

    def verify_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/verify", {}, headers)

    # --- consignment items ---
    def create_consignment_item(self, payload, headers):
        return self._request("POST", "/consignment-items", payload, headers)

    def get_consignment_item(self, item_id, headers):
        return self._request("GET", f"/consignment-items/{item_id}", headers=headers)

    def list_consignment_items(self, headers, params=None):
        return self._request("GET", "/consignment-items", headers=headers, params=params)

    def receive_consignment_item(self, item_id, headers):
        return self._request("POST", f"/consignment-items/{item_id}/receive", {}, headers)

    def schedule_inspection(self, item_id, payload, headers):
        return self._request(
            "POST", f"/consignment-items/{item_id}/schedule-inspection", payload, headers
        )

    def complete_inspection(self, item_id, payload, headers):
        return self._request(
            "POST", f"/consignment-items/{item_id}/complete-inspection", payload, headers
        )

    # --- disputes ---
    def create_dispute(self, payload, headers):
        return self._request("POST", "/disputes", payload, headers)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/disputes/{dispute_id}", headers=headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/disputes", headers=headers, params=params)

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/disputes/{dispute_id}/resolve", payload, headers)


api_client = ApiClient()
