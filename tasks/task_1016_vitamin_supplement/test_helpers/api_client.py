"""API client: one method per endpoint defined in the PRD (Section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Product ----
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    # ---- Lot ----
    def create_lot(self, product_id, payload, headers):
        return self._request("POST", f"/products/{product_id}/lots", payload, headers)

    def list_product_lots(self, product_id, headers, params=None):
        return self._request("GET", f"/products/{product_id}/lots", headers=headers, params=params)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/lots/{lot_id}", headers=headers)

    def set_lot_state(self, lot_id, payload, headers):
        return self._request("POST", f"/lots/{lot_id}/state", payload, headers)

    # ---- Customer ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def suspend_customer(self, customer_id, headers):
        return self._request("POST", f"/customers/{customer_id}/suspend", headers=headers)

    # ---- Practitioner ----
    def create_practitioner(self, payload, headers):
        return self._request("POST", "/practitioners", payload, headers)

    def get_practitioner(self, practitioner_id, headers):
        return self._request("GET", f"/practitioners/{practitioner_id}", headers=headers)

    # ---- Recommendation ----
    def create_recommendation(self, payload, headers):
        return self._request("POST", "/recommendations", payload, headers)

    def get_recommendation(self, recommendation_id, headers):
        return self._request("GET", f"/recommendations/{recommendation_id}", headers=headers)

    def list_recommendations(self, headers, params=None):
        return self._request("GET", "/recommendations", headers=headers, params=params)

    def revoke_recommendation(self, recommendation_id, headers):
        return self._request("POST", f"/recommendations/{recommendation_id}/revoke", headers=headers)

    # ---- Bundle ----
    def create_bundle(self, payload, headers):
        return self._request("POST", "/bundles", payload, headers)

    def get_bundle(self, bundle_id, headers):
        return self._request("GET", f"/bundles/{bundle_id}", headers=headers)

    # ---- Subscription ----
    def create_subscription(self, payload, headers):
        return self._request("POST", "/subscriptions", payload, headers)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/subscriptions/{subscription_id}", headers=headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/subscriptions", headers=headers, params=params)

    def set_subscription_state(self, subscription_id, payload, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/state", payload, headers)

    def generate_order(self, subscription_id, payload, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/generate-order", payload, headers)

    # ---- Order & OrderLine ----
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

    def get_order_line(self, order_line_id, headers):
        return self._request("GET", f"/order-lines/{order_line_id}", headers=headers)

    def list_order_lines_filtered(self, headers, params=None):
        return self._request("GET", "/order-lines", headers=headers, params=params)

    def place_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/place", headers=headers)

    def fulfill_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/fulfill", headers=headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", headers=headers)

    # ---- Return ----
    def create_return(self, payload, headers):
        return self._request("POST", "/returns", payload, headers)

    def get_return(self, return_id, headers):
        return self._request("GET", f"/returns/{return_id}", headers=headers)

    def list_returns(self, headers, params=None):
        return self._request("GET", "/returns", headers=headers, params=params)

    def set_return_state(self, return_id, payload, headers):
        return self._request("POST", f"/returns/{return_id}/state", payload, headers)

    # ---- Test-driving endpoints ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_expiry_sweep(self, headers):
        return self._request("POST", "/_jobs/run-expiry-sweep", headers=headers)

    def inject_loyalty_state(self, payload, headers):
        return self._request("POST", "/_inject/loyalty_state", payload, headers)


api_client = ApiClient()
