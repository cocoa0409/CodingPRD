"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Customers ────────────────────────────────────
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def suspend_customer(self, customer_id, headers):
        return self._request("POST", f"/customers/{customer_id}/suspend", {}, headers)

    def list_customer_allocation_claims(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/allocation-claims", headers=headers, params=params)

    def list_customer_loyalty_transactions(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/loyalty-transactions", headers=headers, params=params)

    # ─── Products / Variants / note finder ────────────
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    def create_variant(self, product_id, payload, headers):
        return self._request("POST", f"/products/{product_id}/variants", payload, headers)

    def list_product_variants(self, product_id, headers, params=None):
        return self._request("GET", f"/products/{product_id}/variants", headers=headers, params=params)

    def get_variant(self, variant_id, headers):
        return self._request("GET", f"/variants/{variant_id}", headers=headers)

    def list_variant_order_lines(self, variant_id, headers, params=None):
        return self._request("GET", f"/variants/{variant_id}/order-lines", headers=headers, params=params)

    # ─── Allocation windows / claims ──────────────────
    def create_allocation_window(self, product_id, payload, headers):
        return self._request("POST", f"/products/{product_id}/allocation-windows", payload, headers)

    def list_product_allocation_windows(self, product_id, headers, params=None):
        return self._request("GET", f"/products/{product_id}/allocation-windows", headers=headers, params=params)

    def get_allocation_window(self, window_id, headers):
        return self._request("GET", f"/allocation-windows/{window_id}", headers=headers)

    def create_claim(self, window_id, payload, headers):
        return self._request("POST", f"/allocation-windows/{window_id}/claims", payload, headers)

    def list_window_claims(self, window_id, headers, params=None):
        return self._request("GET", f"/allocation-windows/{window_id}/claims", headers=headers, params=params)

    # ─── Subscriptions / shipments ────────────────────
    def create_subscription(self, payload, headers):
        return self._request("POST", "/subscriptions", payload, headers)

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

    def create_shipment(self, subscription_id, payload, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/shipments", payload, headers)

    def list_subscription_shipments(self, subscription_id, headers, params=None):
        return self._request("GET", f"/subscriptions/{subscription_id}/shipments", headers=headers, params=params)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/shipments/{shipment_id}", headers=headers)

    def fulfill_shipment(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/fulfill", {}, headers)

    # ─── Orders / lines ───────────────────────────────
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def create_order_line(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/lines", payload, headers)

    def list_order_lines(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/lines", headers=headers, params=params)

    def place_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/place", payload, headers)

    def fulfill_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/fulfill", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", {}, headers)

    # ─── Returns ──────────────────────────────────────
    def create_return(self, payload, headers):
        return self._request("POST", "/returns", payload, headers)

    def get_return(self, return_id, headers):
        return self._request("GET", f"/returns/{return_id}", headers=headers)

    def list_returns(self, headers, params=None):
        return self._request("GET", "/returns", headers=headers, params=params)

    def approve_return(self, return_id, headers):
        return self._request("POST", f"/returns/{return_id}/approve", {}, headers)

    def reject_return(self, return_id, headers):
        return self._request("POST", f"/returns/{return_id}/reject", {}, headers)

    # ─── Test-driving clock ───────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
