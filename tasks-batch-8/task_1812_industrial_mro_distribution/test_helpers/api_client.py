"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- CustomerAccount ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/mro/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/mro/customers/{customer_id}", headers=headers)

    def update_customer(self, customer_id, payload, headers):
        return self._request("PUT", f"/mro/customers/{customer_id}", payload, headers)

    def list_customer_rebate_agreements(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/mro/customers/{customer_id}/rebate-agreements",
            headers=headers, params=params,
        )

    def list_customer_carts(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/mro/customers/{customer_id}/carts", headers=headers, params=params
        )

    # --- Item ---
    def create_item(self, payload, headers):
        return self._request("POST", "/mro/items", payload, headers)

    def get_item(self, item_id, headers):
        return self._request("GET", f"/mro/items/{item_id}", headers=headers)

    def list_item_stock_balances(self, item_id, headers, params=None):
        return self._request(
            "GET", f"/mro/items/{item_id}/stock-balances",
            headers=headers, params=params,
        )

    def list_item_order_lines(self, item_id, headers, params=None):
        return self._request(
            "GET", f"/mro/items/{item_id}/order-lines", headers=headers, params=params
        )

    # --- PriceMatrixRule ---
    def create_price_rule(self, payload, headers):
        return self._request("POST", "/mro/price-rules", payload, headers)

    def list_price_rules(self, headers, params=None):
        return self._request("GET", "/mro/price-rules", headers=headers, params=params)

    def get_price_rule(self, rule_id, headers):
        return self._request("GET", f"/mro/price-rules/{rule_id}", headers=headers)

    def update_price_rule(self, rule_id, payload, headers):
        return self._request("PUT", f"/mro/price-rules/{rule_id}", payload, headers)

    def activate_price_rule(self, rule_id, headers):
        return self._request(
            "POST", f"/mro/price-rules/{rule_id}/activate", {}, headers
        )

    # --- RebateAgreement ---
    def create_rebate_agreement(self, customer_id, payload, headers):
        return self._request(
            "POST", f"/mro/customers/{customer_id}/rebate-agreements", payload, headers
        )

    def get_rebate_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"/mro/rebate-agreements/{agreement_id}", headers=headers
        )

    def activate_rebate_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/mro/rebate-agreements/{agreement_id}/activate", {}, headers
        )

    def close_rebate_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/mro/rebate-agreements/{agreement_id}/close", {}, headers
        )

    def settle_rebate_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/mro/rebate-agreements/{agreement_id}/settle", {}, headers
        )

    # --- StockLocation / StockBalance ---
    def create_location(self, payload, headers):
        return self._request("POST", "/mro/locations", payload, headers)

    def get_location(self, location_id, headers):
        return self._request("GET", f"/mro/locations/{location_id}", headers=headers)

    def restock_location(self, location_id, payload, headers):
        return self._request(
            "POST", f"/mro/locations/{location_id}/restock", payload, headers
        )

    def list_location_stock_balances(self, location_id, headers, params=None):
        return self._request(
            "GET", f"/mro/locations/{location_id}/stock-balances",
            headers=headers, params=params,
        )

    # --- RequisitionCart (punch-out) ---
    def create_cart(self, payload, headers):
        return self._request("POST", "/mro/carts", payload, headers)

    def get_cart(self, cart_id, headers):
        return self._request("GET", f"/mro/carts/{cart_id}", headers=headers)

    def update_cart(self, cart_id, payload, headers):
        return self._request("PUT", f"/mro/carts/{cart_id}", payload, headers)

    def submit_cart(self, cart_id, headers):
        return self._request("POST", f"/mro/carts/{cart_id}/submit", {}, headers)

    def approve_cart(self, cart_id, headers):
        return self._request("POST", f"/mro/carts/{cart_id}/approve", {}, headers)

    def reject_cart(self, cart_id, payload, headers):
        return self._request("POST", f"/mro/carts/{cart_id}/reject", payload, headers)

    # --- SalesOrder ---
    def create_order(self, payload, headers):
        return self._request("POST", "/mro/orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/mro/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/mro/orders/{order_id}", headers=headers)

    def confirm_order(self, order_id, headers):
        return self._request("POST", f"/mro/orders/{order_id}/confirm", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/mro/orders/{order_id}/cancel", {}, headers)

    def mark_order_ready(self, order_id, headers):
        return self._request("POST", f"/mro/orders/{order_id}/mark-ready", {}, headers)

    def mark_order_fulfilled(self, order_id, headers):
        return self._request(
            "POST", f"/mro/orders/{order_id}/mark-fulfilled", {}, headers
        )

    def vendor_confirm_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/mro/orders/{order_id}/vendor-confirm", payload, headers
        )

    def complete_order(self, order_id, headers):
        return self._request("POST", f"/mro/orders/{order_id}/complete", {}, headers)

    def list_order_lines(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/mro/orders/{order_id}/lines", headers=headers, params=params
        )

    def list_order_returns(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/mro/orders/{order_id}/returns", headers=headers, params=params
        )

    # --- ReturnAuthorization ---
    def create_return(self, payload, headers):
        return self._request("POST", "/mro/returns", payload, headers)

    def get_return(self, return_id, headers):
        return self._request("GET", f"/mro/returns/{return_id}", headers=headers)

    def approve_return(self, return_id, headers):
        return self._request("POST", f"/mro/returns/{return_id}/approve", {}, headers)

    def reject_return(self, return_id, payload, headers):
        return self._request(
            "POST", f"/mro/returns/{return_id}/reject", payload, headers
        )

    def receive_return(self, return_id, headers):
        return self._request("POST", f"/mro/returns/{return_id}/receive", {}, headers)

    def credit_return(self, return_id, headers):
        return self._request("POST", f"/mro/returns/{return_id}/credit", {}, headers)

    # --- Test-driving logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
