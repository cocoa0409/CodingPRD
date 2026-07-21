"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (administrative) ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # --- Product ---
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    # --- Sku ---
    def create_sku(self, product_id, payload, headers):
        return self._request("POST", f"/products/{product_id}/skus", payload, headers)

    def get_sku(self, sku_id, headers):
        return self._request("GET", f"/skus/{sku_id}", headers=headers)

    def list_skus(self, headers, params=None):
        return self._request("GET", "/skus", headers=headers, params=params)

    # --- Batch ---
    def create_batch(self, sku_id, payload, headers):
        return self._request("POST", f"/skus/{sku_id}/batches", payload, headers)

    def get_batch(self, batch_id, headers):
        return self._request("GET", f"/batches/{batch_id}", headers=headers)

    def list_batches(self, headers, params=None):
        return self._request("GET", "/batches", headers=headers, params=params)

    def label_batch(self, batch_id, headers):
        return self._request("POST", f"/batches/{batch_id}/label", {}, headers)

    def release_batch(self, batch_id, headers):
        return self._request("POST", f"/batches/{batch_id}/release", {}, headers)

    def recall_batch(self, batch_id, headers):
        return self._request("POST", f"/batches/{batch_id}/recall", {}, headers)

    # --- Drop ---
    def create_drop(self, payload, headers):
        return self._request("POST", "/drops", payload, headers)

    def get_drop(self, drop_id, headers):
        return self._request("GET", f"/drops/{drop_id}", headers=headers)

    # --- Bundle ---
    def create_bundle(self, payload, headers):
        return self._request("POST", "/bundles", payload, headers)

    def get_bundle(self, bundle_id, headers):
        return self._request("GET", f"/bundles/{bundle_id}", headers=headers)

    def activate_bundle(self, bundle_id, headers):
        return self._request("POST", f"/bundles/{bundle_id}/activate", {}, headers)

    # --- Customer ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def suspend_customer(self, customer_id, headers):
        return self._request("POST", f"/customers/{customer_id}/suspend", {}, headers)

    def grant_loyalty(self, customer_id, points, headers):
        return self._request("POST", f"/customers/{customer_id}/loyalty-grant", {"points": points}, headers)

    # --- Order / OrderLine ---
    def create_order(self, customer_id, payload, headers):
        return self._request("POST", f"/customers/{customer_id}/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def add_line(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/lines", payload, headers)

    def get_order_line(self, order_line_id, headers):
        return self._request("GET", f"/order-lines/{order_line_id}", headers=headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/order-lines", headers=headers, params=params)

    def checkout_order(self, order_id, expected_order_version, headers):
        return self._request(
            "POST", f"/orders/{order_id}/checkout",
            {"expected_order_version": expected_order_version}, headers,
        )

    def fulfill_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/fulfill", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", {}, headers)

    # --- Return ---
    def request_return(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/returns", payload, headers)

    def get_return(self, return_id, headers):
        return self._request("GET", f"/returns/{return_id}", headers=headers)

    def list_returns(self, headers, params=None):
        return self._request("GET", "/returns", headers=headers, params=params)

    def approve_return(self, return_id, headers):
        return self._request("POST", f"/returns/{return_id}/approve", {}, headers)

    def reject_return(self, return_id, headers):
        return self._request("POST", f"/returns/{return_id}/reject", {}, headers)

    def settle_return(self, return_id, headers):
        return self._request("POST", f"/returns/{return_id}/settle", {}, headers)

    # --- Subscription ---
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

    def renew_subscription(self, subscription_id, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/renew", {}, headers)


api_client = ApiClient()
