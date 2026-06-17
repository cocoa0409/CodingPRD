"""API client: one method per endpoint defined in the Trophy, Awards & Engraving PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----- Test clock -----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ----- Customer -----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customer_orders(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/customers/{customer_id}/orders", headers=headers, params=params
        )

    # ----- Catalog -----
    def create_catalog_product(self, payload, headers):
        return self._request("POST", "/catalog-products", payload, headers)

    def get_catalog_product(self, product_id, headers):
        return self._request("GET", f"/catalog-products/{product_id}", headers=headers)

    def update_catalog_product(self, product_id, payload, headers):
        return self._request(
            "PATCH", f"/catalog-products/{product_id}", payload, headers
        )

    # ----- Component -----
    def create_component(self, payload, headers):
        return self._request("POST", "/components", payload, headers)

    def get_component(self, component_id, headers):
        return self._request("GET", f"/components/{component_id}", headers=headers)

    def receive_component(self, component_id, payload, headers):
        return self._request(
            "POST", f"/components/{component_id}/receive", payload, headers
        )

    def list_line_component_allocations(self, line_id, headers, params=None):
        return self._request(
            "GET",
            f"/order-lines/{line_id}/component-allocations",
            headers=headers,
            params=params,
        )

    def list_component_allocations(self, headers, params=None):
        return self._request(
            "GET", "/component-allocations", headers=headers, params=params
        )

    def get_component_allocation(self, alloc_id, headers):
        return self._request(
            "GET", f"/component-allocations/{alloc_id}", headers=headers
        )

    # ----- RushPolicy -----
    def create_rush_policy(self, payload, headers):
        return self._request("POST", "/rush-policies", payload, headers)

    def get_rush_policy(self, policy_id, headers):
        return self._request("GET", f"/rush-policies/{policy_id}", headers=headers)

    # ----- PromoCode -----
    def create_promo_code(self, payload, headers):
        return self._request("POST", "/promo-codes", payload, headers)

    def get_promo_code(self, promo_id, headers):
        return self._request("GET", f"/promo-codes/{promo_id}", headers=headers)

    # ----- Order lifecycle -----
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def edit_order(self, order_id, payload, headers):
        return self._request("PUT", f"/orders/{order_id}", payload, headers)

    def add_line(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/lines", payload, headers)

    def list_order_lines_of_order(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/orders/{order_id}/lines", headers=headers, params=params
        )

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/order-lines/{line_id}", headers=headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/order-lines", headers=headers, params=params)

    def delete_order_line(self, line_id, headers):
        return self._request("DELETE", f"/order-lines/{line_id}", headers=headers)

    def price_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/price", {}, headers)

    def confirm_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/confirm", payload, headers)

    def reorder(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/reorder", payload, headers)

    def start_production(self, order_id, headers):
        return self._request(
            "POST", f"/orders/{order_id}/start-production", {}, headers
        )

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", {}, headers)

    # ----- Payments -----
    def create_payment(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/payments", payload, headers)

    def list_payments(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/orders/{order_id}/payments", headers=headers, params=params
        )

    # ----- Proofs -----
    def create_proof(self, line_id, payload, headers):
        return self._request(
            "POST", f"/order-lines/{line_id}/proofs", payload, headers
        )

    def list_proofs(self, line_id, headers, params=None):
        return self._request(
            "GET", f"/order-lines/{line_id}/proofs", headers=headers, params=params
        )

    def get_proof(self, proof_id, headers):
        return self._request("GET", f"/proofs/{proof_id}", headers=headers)

    def send_proof(self, line_id, proof_id, headers):
        return self._request(
            "POST", f"/order-lines/{line_id}/proofs/{proof_id}/send", {}, headers
        )

    def approve_proof(self, line_id, proof_id, headers):
        return self._request(
            "POST", f"/order-lines/{line_id}/proofs/{proof_id}/approve", {}, headers
        )

    def request_changes_proof(self, line_id, proof_id, headers):
        return self._request(
            "POST",
            f"/order-lines/{line_id}/proofs/{proof_id}/request-changes",
            {},
            headers,
        )

    def revise_proof(self, line_id, proof_id, payload, headers):
        return self._request(
            "POST", f"/order-lines/{line_id}/proofs/{proof_id}/revise", payload, headers
        )

    # ----- Production: line engrave/assemble -----
    def engrave_line(self, line_id, headers):
        return self._request("POST", f"/order-lines/{line_id}/engrave", {}, headers)

    def assemble_line(self, line_id, headers):
        return self._request("POST", f"/order-lines/{line_id}/assemble", {}, headers)

    # ----- Fulfillment -----
    def create_fulfillment(self, order_id, payload, headers):
        return self._request(
            "POST", f"/orders/{order_id}/fulfillments", payload, headers
        )

    def list_fulfillments(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/orders/{order_id}/fulfillments", headers=headers, params=params
        )

    def hand_off(self, order_id, fulfillment_id, headers):
        return self._request(
            "POST",
            f"/orders/{order_id}/fulfillments/{fulfillment_id}/hand-off",
            {},
            headers,
        )


api_client = ApiClient()
