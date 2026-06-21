"""API client: one method per endpoint defined in the PRD.

All paths are mounted under /v1 (the clock test-driving endpoint excepted).
Bodies and query params follow the §3/§4 endpoint narratives.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Store ───────────────────────────────────────
    def create_store(self, payload, headers):
        return self._request("POST", "/v1/stores", payload, headers)

    def list_stores(self, headers, params=None):
        return self._request("GET", "/v1/stores", headers=headers, params=params)

    def get_store(self, store_id, headers):
        return self._request("GET", f"/v1/stores/{store_id}", headers=headers)

    def close_store(self, store_id, headers):
        return self._request("POST", f"/v1/stores/{store_id}/close", {}, headers)

    # ─── Customer ────────────────────────────────────
    def create_customer(self, payload, headers):
        return self._request("POST", "/v1/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/v1/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/v1/customers/{customer_id}", headers=headers)

    def suspend_customer(self, customer_id, headers):
        return self._request("POST", f"/v1/customers/{customer_id}/suspend", {}, headers)

    def reinstate_customer(self, customer_id, headers):
        return self._request("POST", f"/v1/customers/{customer_id}/reinstate", {}, headers)

    # ─── Picker ──────────────────────────────────────
    def create_picker(self, payload, headers):
        return self._request("POST", "/v1/pickers", payload, headers)

    def list_pickers(self, headers, params=None):
        return self._request("GET", "/v1/pickers", headers=headers, params=params)

    def get_picker(self, picker_id, headers):
        return self._request("GET", f"/v1/pickers/{picker_id}", headers=headers)

    # ─── Product ─────────────────────────────────────
    def create_product(self, payload, headers):
        return self._request("POST", "/v1/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/v1/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/v1/products/{product_id}", headers=headers)

    def discontinue_product(self, product_id, headers):
        return self._request("POST", f"/v1/products/{product_id}/discontinue", {}, headers)

    # ─── FulfillmentSlot ─────────────────────────────
    def create_slot(self, payload, headers):
        return self._request("POST", "/v1/slots", payload, headers)

    def list_slots(self, headers, params=None):
        return self._request("GET", "/v1/slots", headers=headers, params=params)

    def get_slot(self, slot_id, headers):
        return self._request("GET", f"/v1/slots/{slot_id}", headers=headers)

    def close_slot(self, slot_id, headers):
        return self._request("POST", f"/v1/slots/{slot_id}/close", {}, headers)

    # ─── Order ───────────────────────────────────────
    def create_order(self, payload, headers):
        return self._request("POST", "/v1/orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/v1/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/v1/orders/{order_id}", headers=headers)

    def claim_order(self, order_id, payload, headers):
        return self._request("POST", f"/v1/orders/{order_id}/claim", payload, headers)

    def stage_order(self, order_id, headers):
        return self._request("POST", f"/v1/orders/{order_id}/stage", {}, headers)

    def capture_order(self, order_id, headers):
        return self._request("POST", f"/v1/orders/{order_id}/capture", {}, headers)

    def handoff_order(self, order_id, headers):
        return self._request("POST", f"/v1/orders/{order_id}/handoff", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/v1/orders/{order_id}/cancel", {}, headers)

    # ─── OrderLine ───────────────────────────────────
    def create_order_line(self, payload, headers):
        return self._request("POST", "/v1/order-lines", payload, headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/v1/order-lines", headers=headers, params=params)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/v1/order-lines/{line_id}", headers=headers)

    def pick_order_line(self, line_id, payload, headers):
        return self._request("POST", f"/v1/order-lines/{line_id}/pick", payload, headers)

    def out_of_stock_order_line(self, line_id, headers):
        return self._request("POST", f"/v1/order-lines/{line_id}/out-of-stock", {}, headers)

    # ─── Substitution ────────────────────────────────
    def create_substitution(self, payload, headers):
        return self._request("POST", "/v1/substitutions", payload, headers)

    def list_substitutions(self, headers, params=None):
        return self._request("GET", "/v1/substitutions", headers=headers, params=params)

    def get_substitution(self, sub_id, headers):
        return self._request("GET", f"/v1/substitutions/{sub_id}", headers=headers)

    def accept_substitution(self, sub_id, headers):
        return self._request("POST", f"/v1/substitutions/{sub_id}/accept", {}, headers)

    def reject_substitution(self, sub_id, headers):
        return self._request("POST", f"/v1/substitutions/{sub_id}/reject", {}, headers)

    # ─── Payment ─────────────────────────────────────
    def list_payments(self, headers, params=None):
        return self._request("GET", "/v1/payments", headers=headers, params=params)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/v1/payments/{payment_id}", headers=headers)

    # ─── Refund ──────────────────────────────────────
    def list_refunds(self, headers, params=None):
        return self._request("GET", "/v1/refunds", headers=headers, params=params)

    def get_refund(self, refund_id, headers):
        return self._request("GET", f"/v1/refunds/{refund_id}", headers=headers)

    # ─── AgeCheck ────────────────────────────────────
    def create_age_check(self, payload, headers):
        return self._request("POST", "/v1/age-checks", payload, headers)

    def list_age_checks(self, headers, params=None):
        return self._request("GET", "/v1/age-checks", headers=headers, params=params)

    def get_age_check(self, age_check_id, headers):
        return self._request("GET", f"/v1/age-checks/{age_check_id}", headers=headers)

    # ─── Test-driving clock ──────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
