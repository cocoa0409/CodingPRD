"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Products / Variants ----
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def create_variant(self, product_id, payload, headers):
        return self._request("POST", f"/products/{product_id}/variants", payload, headers)

    def list_product_variants(self, product_id, headers, params=None):
        return self._request("GET", f"/products/{product_id}/variants", headers=headers, params=params)

    def get_variant(self, variant_id, headers):
        return self._request("GET", f"/variants/{variant_id}", headers=headers)

    # ---- Customers / Fit / Loyalty ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def create_loyalty_adjustment(self, customer_id, payload, headers):
        return self._request("POST", f"/customers/{customer_id}/loyalty-adjustments", payload, headers)

    def list_loyalty_ledger(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/loyalty-ledger", headers=headers, params=params)

    def create_fit_profile(self, payload, headers):
        return self._request("POST", "/fit-profiles", payload, headers)

    def list_fit_profiles(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/fit-profiles", headers=headers, params=params)

    # ---- Orders ----
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def pay_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/pay", payload, headers)

    def cancel_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/orders/{order_id}/cancel", payload or {}, headers)

    def fulfill_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/orders/{order_id}/fulfill", payload or {}, headers)

    # ---- Rentals ----
    def get_rental(self, rental_id, headers):
        return self._request("GET", f"/rentals/{rental_id}", headers=headers)

    def list_rentals(self, headers, params=None):
        return self._request("GET", "/rentals", headers=headers, params=params)

    def activate_rental(self, rental_id, headers, payload=None):
        return self._request("POST", f"/rentals/{rental_id}/activate", payload or {}, headers)

    def return_rental(self, rental_id, headers, payload=None):
        return self._request("POST", f"/rentals/{rental_id}/return", payload or {}, headers)

    def convert_rental_to_buy(self, rental_id, headers, payload=None):
        return self._request("POST", f"/rentals/{rental_id}/convert-to-buy", payload or {}, headers)

    # ---- Subscriptions / Capsules ----
    def create_subscription(self, payload, headers):
        return self._request("POST", "/subscriptions", payload, headers)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/subscriptions/{subscription_id}", headers=headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/subscriptions", headers=headers, params=params)

    def pause_subscription(self, subscription_id, headers, payload=None):
        return self._request("POST", f"/subscriptions/{subscription_id}/pause", payload or {}, headers)

    def resume_subscription(self, subscription_id, headers, payload=None):
        return self._request("POST", f"/subscriptions/{subscription_id}/resume", payload or {}, headers)

    def cancel_subscription(self, subscription_id, headers, payload=None):
        return self._request("POST", f"/subscriptions/{subscription_id}/cancel", payload or {}, headers)

    def create_capsule(self, subscription_id, payload, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/capsules", payload, headers)

    def list_capsules(self, subscription_id, headers, params=None):
        return self._request("GET", f"/subscriptions/{subscription_id}/capsules", headers=headers, params=params)

    def ship_capsule(self, capsule_id, headers, payload=None):
        return self._request("POST", f"/capsules/{capsule_id}/ship", payload or {}, headers)

    # ---- Returns ----
    def create_return(self, payload, headers):
        return self._request("POST", "/returns", payload, headers)

    def get_return(self, return_id, headers):
        return self._request("GET", f"/returns/{return_id}", headers=headers)

    def list_returns(self, headers, params=None):
        return self._request("GET", "/returns", headers=headers, params=params)

    def approve_return(self, return_id, headers, payload=None):
        return self._request("POST", f"/returns/{return_id}/approve", payload or {}, headers)

    def reject_return(self, return_id, headers, payload=None):
        return self._request("POST", f"/returns/{return_id}/reject", payload or {}, headers)

    # ---- Logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
