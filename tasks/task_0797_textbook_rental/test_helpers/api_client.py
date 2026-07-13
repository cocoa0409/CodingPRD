"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Catalog ---
    def create_catalog(self, payload, headers):
        return self._request("POST", "/catalog", payload, headers)

    def get_catalog(self, catalog_id, headers):
        return self._request("GET", f"/catalog/{catalog_id}", headers=headers)

    # --- Inventory units ---
    def create_inventory_unit(self, payload, headers):
        return self._request("POST", "/inventory-units", payload, headers)

    def get_inventory_unit(self, unit_id, headers):
        return self._request("GET", f"/inventory-units/{unit_id}", headers=headers)

    def list_inventory_units(self, headers, params=None):
        return self._request("GET", "/inventory-units", headers=headers, params=params)

    # --- Customers & wallet ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def create_wallet_adjustment(self, customer_id, payload, headers):
        return self._request("POST", f"/customers/{customer_id}/wallet/adjustments", payload, headers)

    def list_wallet_transactions(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/wallet-transactions", headers=headers, params=params)

    # --- Subscription plans & subscriptions ---
    def create_subscription_plan(self, payload, headers):
        return self._request("POST", "/subscription-plans", payload, headers)

    def create_subscription(self, customer_id, payload, headers):
        return self._request("POST", f"/customers/{customer_id}/subscription", payload, headers)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/subscriptions/{subscription_id}", headers=headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/subscriptions", headers=headers, params=params)

    def cancel_subscription(self, subscription_id, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/cancel", headers=headers)

    # --- Orders ---
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def pay_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/pay", headers=headers)

    def confirm_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/confirm", headers=headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", headers=headers)

    # --- Rentals ---
    def get_rental(self, rental_id, headers):
        return self._request("GET", f"/rentals/{rental_id}", headers=headers)

    def list_rentals(self, headers, params=None):
        return self._request("GET", "/rentals", headers=headers, params=params)

    def extend_rental(self, rental_id, headers):
        return self._request("POST", f"/rentals/{rental_id}/extend", headers=headers)

    def return_rental(self, rental_id, headers):
        return self._request("POST", f"/rentals/{rental_id}/return", headers=headers)

    def list_rental_return_shipments(self, rental_id, headers, params=None):
        return self._request("GET", f"/rentals/{rental_id}/return-shipments", headers=headers, params=params)

    # --- Return shipments ---
    def inspect_return_shipment(self, return_shipment_id, payload, headers):
        return self._request("POST", f"/return-shipments/{return_shipment_id}/inspect", payload, headers)

    # --- Buyback quotes ---
    def create_buyback_quote(self, payload, headers):
        return self._request("POST", "/buyback-quotes", payload, headers)

    def get_buyback_quote(self, quote_id, headers):
        return self._request("GET", f"/buyback-quotes/{quote_id}", headers=headers)

    def list_buyback_quotes(self, headers, params=None):
        return self._request("GET", "/buyback-quotes", headers=headers, params=params)

    def accept_buyback_quote(self, quote_id, headers):
        return self._request("POST", f"/buyback-quotes/{quote_id}/accept", headers=headers)

    def inspect_buyback_quote(self, quote_id, payload, headers):
        return self._request("POST", f"/buyback-quotes/{quote_id}/inspect", payload, headers)

    def respond_revision_buyback_quote(self, quote_id, payload, headers):
        return self._request("POST", f"/buyback-quotes/{quote_id}/respond-revision", payload, headers)


api_client = ApiClient()
