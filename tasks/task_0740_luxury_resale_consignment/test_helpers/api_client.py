"""API client: one method per endpoint defined in the PRD (§4).

Subclasses the framework's GenericApiClient; the base _request() handles URL
composition, JSON bodies, query params, and returns the raw response so tests
can assert status codes and error envelopes.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Sellers ---
    def create_seller(self, payload, headers):
        return self._request("POST", "/consignment/sellers", payload, headers)

    def get_seller(self, seller_id, headers):
        return self._request("GET", f"/consignment/sellers/{seller_id}", headers=headers)

    # --- Buyers ---
    def create_buyer(self, payload, headers):
        return self._request("POST", "/consignment/buyers", payload, headers)

    def get_buyer(self, buyer_id, headers):
        return self._request("GET", f"/consignment/buyers/{buyer_id}", headers=headers)

    # --- Category policies ---
    def create_category_policy(self, payload, headers):
        return self._request("POST", "/consignment/category-policies", payload, headers)

    def get_category_policy(self, policy_id, headers):
        return self._request("GET", f"/consignment/category-policies/{policy_id}", headers=headers)

    # --- Consignment items ---
    def create_item(self, payload, headers):
        return self._request("POST", "/consignment/items", payload, headers)

    def list_items(self, headers, params=None):
        return self._request("GET", "/consignment/items", headers=headers, params=params)

    def get_item(self, item_id, headers):
        return self._request("GET", f"/consignment/items/{item_id}", headers=headers)

    def authenticate_item(self, item_id, payload, headers):
        return self._request("POST", f"/consignment/items/{item_id}/authenticate", payload, headers)

    # --- Listings ---
    def create_listing(self, payload, headers):
        return self._request("POST", "/consignment/listings", payload, headers)

    def list_listings(self, headers, params=None):
        return self._request("GET", "/consignment/listings", headers=headers, params=params)

    def get_listing(self, listing_id, headers):
        return self._request("GET", f"/consignment/listings/{listing_id}", headers=headers)

    def publish_listing(self, listing_id, headers):
        return self._request("POST", f"/consignment/listings/{listing_id}/publish", {}, headers)

    # --- Offers ---
    def create_offer(self, payload, headers):
        return self._request("POST", "/consignment/offers", payload, headers)

    def list_offers(self, headers, params=None):
        return self._request("GET", "/consignment/offers", headers=headers, params=params)

    def get_offer(self, offer_id, headers):
        return self._request("GET", f"/consignment/offers/{offer_id}", headers=headers)

    def counter_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/consignment/offers/{offer_id}/counter", payload, headers)

    def accept_offer(self, offer_id, headers):
        return self._request("POST", f"/consignment/offers/{offer_id}/accept", {}, headers)

    # --- Sales ---
    def create_sale(self, payload, headers):
        return self._request("POST", "/consignment/sales", payload, headers)

    def list_sales(self, headers, params=None):
        return self._request("GET", "/consignment/sales", headers=headers, params=params)

    def get_sale(self, sale_id, headers):
        return self._request("GET", f"/consignment/sales/{sale_id}", headers=headers)

    def capture_payment(self, sale_id, headers):
        return self._request("POST", f"/consignment/sales/{sale_id}/capture-payment", {}, headers)

    def ship_sale(self, sale_id, headers):
        return self._request("POST", f"/consignment/sales/{sale_id}/ship", {}, headers)

    def confirm_delivery(self, sale_id, headers):
        return self._request("POST", f"/consignment/sales/{sale_id}/confirm-delivery", {}, headers)

    def list_sale_payouts(self, sale_id, headers, params=None):
        return self._request("GET", f"/consignment/sales/{sale_id}/payouts", headers=headers, params=params)

    def list_sale_disputes(self, sale_id, headers, params=None):
        return self._request("GET", f"/consignment/sales/{sale_id}/disputes", headers=headers, params=params)

    # --- Payouts ---
    def release_payout(self, payout_id, headers):
        return self._request("POST", f"/consignment/payouts/{payout_id}/release", {}, headers)

    # --- Disputes ---
    def create_dispute(self, payload, headers):
        return self._request("POST", "/consignment/disputes", payload, headers)

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/consignment/disputes/{dispute_id}/resolve", payload, headers)

    # --- White-glove pickup resources ---
    def create_concierge(self, payload, headers):
        return self._request("POST", "/consignment/concierges", payload, headers)

    def create_vehicle(self, payload, headers):
        return self._request("POST", "/consignment/vehicles", payload, headers)

    def create_pickup(self, payload, headers):
        return self._request("POST", "/consignment/pickups", payload, headers)

    def list_pickups(self, headers, params=None):
        return self._request("GET", "/consignment/pickups", headers=headers, params=params)

    def get_pickup(self, pickup_id, headers):
        return self._request("GET", f"/consignment/pickups/{pickup_id}", headers=headers)

    def complete_pickup(self, pickup_id, headers):
        return self._request("POST", f"/consignment/pickups/{pickup_id}/complete", {}, headers)

    # --- Logical clock control ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
