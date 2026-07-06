"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----- Farm -----
    def create_farm(self, payload, headers):
        return self._request("POST", "/farms", payload, headers)

    def get_farm(self, farm_id, headers):
        return self._request("GET", f"/farms/{farm_id}", headers=headers)

    def list_farm_products(self, farm_id, headers, params=None):
        return self._request("GET", f"/farms/{farm_id}/products", headers=headers, params=params)

    # ----- Product -----
    def create_product(self, farm_id, payload, headers):
        return self._request("POST", f"/farms/{farm_id}/products", payload, headers)

    # ----- MarketCycle -----
    def create_cycle(self, payload, headers):
        return self._request("POST", "/market-cycles", payload, headers)

    def get_cycle(self, cycle_id, headers):
        return self._request("GET", f"/market-cycles/{cycle_id}", headers=headers)

    def open_cycle(self, cycle_id, headers):
        return self._request("POST", f"/market-cycles/{cycle_id}/open", {}, headers)

    def cutoff_cycle(self, cycle_id, headers):
        return self._request("POST", f"/market-cycles/{cycle_id}/cutoff", {}, headers)

    def settle_cycle(self, cycle_id, headers):
        return self._request("POST", f"/market-cycles/{cycle_id}/settle", {}, headers)

    # ----- Offering -----
    def create_offering(self, cycle_id, payload, headers):
        return self._request("POST", f"/market-cycles/{cycle_id}/offerings", payload, headers)

    def get_offering(self, offering_id, headers):
        return self._request("GET", f"/offerings/{offering_id}", headers=headers)

    def list_offerings(self, headers, params=None):
        return self._request("GET", "/offerings", headers=headers, params=params)

    # ----- PickupHub -----
    def create_hub(self, payload, headers):
        return self._request("POST", "/pickup-hubs", payload, headers)

    def get_hub(self, hub_id, headers):
        return self._request("GET", f"/pickup-hubs/{hub_id}", headers=headers)

    # ----- Customer -----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # ----- Subscription -----
    def create_subscription(self, customer_id, payload, headers):
        return self._request("POST", f"/customers/{customer_id}/subscriptions", payload, headers)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/subscriptions/{subscription_id}", headers=headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/subscriptions", headers=headers, params=params)

    def pause_subscription(self, subscription_id, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/pause", {}, headers)

    def resume_subscription(self, subscription_id, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/resume", {}, headers)

    def cancel_subscription(self, subscription_id, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/cancel", {}, headers)

    # ----- Order -----
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def add_line(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/lines", payload, headers)

    def checkout_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/checkout", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", {}, headers)

    def fulfill_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/fulfill", {}, headers)

    # ----- OrderLine -----
    def get_line(self, line_id, headers):
        return self._request("GET", f"/order-lines/{line_id}", headers=headers)

    def list_lines(self, headers, params=None):
        return self._request("GET", "/order-lines", headers=headers, params=params)

    def pack_line(self, line_id, payload, headers):
        return self._request("POST", f"/order-lines/{line_id}/pack", payload, headers)

    # ----- VendorSettlement -----
    def create_settlement(self, farm_id, payload, headers):
        return self._request("POST", f"/farms/{farm_id}/settlements", payload, headers)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/settlements/{settlement_id}", headers=headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", "/settlements", headers=headers, params=params)

    # ----- Logical clock (test-driving) -----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
