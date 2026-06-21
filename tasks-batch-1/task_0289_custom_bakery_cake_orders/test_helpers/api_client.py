"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; the base _request() performs the
HTTP call and returns a Response object. All paths use the bakery API surface.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- products ----------------------------------------------------------
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    # ---- options -----------------------------------------------------------
    def create_option(self, payload, headers):
        return self._request("POST", "/options", payload, headers)

    def get_option(self, option_id, headers):
        return self._request("GET", f"/options/{option_id}", headers=headers)

    def list_options(self, headers, params=None):
        return self._request("GET", "/options", headers=headers, params=params)

    # ---- production days ---------------------------------------------------
    def create_production_day(self, payload, headers):
        return self._request("POST", "/production-days", payload, headers)

    def get_production_day(self, pday_id, headers):
        return self._request("GET", f"/production-days/{pday_id}", headers=headers)

    def list_production_days(self, headers, params=None):
        return self._request("GET", "/production-days", headers=headers, params=params)

    def list_production_day_orders(self, pday_id, headers, params=None):
        return self._request("GET", f"/production-days/{pday_id}/orders", headers=headers, params=params)

    # ---- routes ------------------------------------------------------------
    def create_route(self, payload, headers):
        return self._request("POST", "/routes", payload, headers)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/routes/{route_id}", headers=headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/routes", headers=headers, params=params)

    def list_route_reservations(self, route_id, headers, params=None):
        return self._request("GET", f"/routes/{route_id}/reservations", headers=headers, params=params)

    # ---- customers ---------------------------------------------------------
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def adjust_credit(self, customer_id, payload, headers):
        return self._request("POST", f"/customers/{customer_id}/credit-adjustments", payload, headers)

    # ---- orders: core lifecycle -------------------------------------------
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def add_line(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/lines", payload, headers)

    def list_lines(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/lines", headers=headers, params=params)

    def edit_line(self, order_id, line_id, payload, headers):
        return self._request("PATCH", f"/orders/{order_id}/lines/{line_id}", payload, headers)

    def delete_line(self, order_id, line_id, headers):
        return self._request("DELETE", f"/orders/{order_id}/lines/{line_id}", headers=headers)

    def quote_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/quote", payload, headers)

    def cancel_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", payload, headers)

    # ---- orders: proofs ----------------------------------------------------
    def post_proof(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/proofs", payload, headers)

    def list_proofs(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/proofs", headers=headers, params=params)

    def approve_proof(self, order_id, proof_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/proofs/{proof_id}/approve", payload, headers)

    def request_changes(self, order_id, proof_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/proofs/{proof_id}/request-changes", payload, headers)

    # ---- orders: payments --------------------------------------------------
    def post_payment(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/payments", payload, headers)

    def post_balance_payment(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/balance-payment", payload, headers)

    def list_payments(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/payments", headers=headers, params=params)

    # ---- orders: slot reservations ----------------------------------------
    def create_slot(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/slot", payload, headers)

    def list_slots(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/slot", headers=headers, params=params)

    def commit_slot(self, order_id, reservation_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/slot/{reservation_id}/commit", payload, headers)

    def release_slot(self, order_id, reservation_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/slot/{reservation_id}/release", payload, headers)

    # ---- orders: production progression ------------------------------------
    def start_production(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/start-production", payload, headers)

    def mark_ready(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/mark-ready", payload, headers)

    def fulfill(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/fulfill", payload, headers)

    # ---- test-driving clock / overrides -----------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set", payload, headers)

    def mint_override(self, payload, headers):
        return self._request("POST", "/_overrides/mint", payload, headers)


api_client = ApiClient()
