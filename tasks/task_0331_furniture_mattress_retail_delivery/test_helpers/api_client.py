"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; the base _request() is inherited.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Customer ─────────────────────────────────────────────────────────
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customer_orders(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/orders",
                             headers=headers, params=params)

    def list_customer_financing_plans(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/financing-plans",
                             headers=headers, params=params)

    # ─── Product ──────────────────────────────────────────────────────────
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def list_product_order_lines(self, product_id, headers, params=None):
        return self._request("GET", f"/products/{product_id}/order-lines",
                             headers=headers, params=params)

    # ─── Order ────────────────────────────────────────────────────────────
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def list_order_lines(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/lines",
                             headers=headers, params=params)

    def list_order_financing_plans(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/financing-plans",
                             headers=headers, params=params)

    def list_order_delivery_stops(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/delivery-stops",
                             headers=headers, params=params)

    def list_order_return_requests(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/return-requests",
                             headers=headers, params=params)

    def confirm_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/confirm", headers=headers)

    def pay_in_full_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/pay-in-full", headers=headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", headers=headers)

    def close_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/close", headers=headers)

    # ─── OrderLine ────────────────────────────────────────────────────────
    def create_order_line(self, payload, headers):
        return self._request("POST", "/order-lines", payload, headers)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/order-lines/{line_id}", headers=headers)

    def delete_order_line(self, line_id, headers):
        return self._request("DELETE", f"/order-lines/{line_id}", headers=headers)

    def list_line_protection_plans(self, line_id, headers, params=None):
        return self._request("GET", f"/order-lines/{line_id}/protection-plans",
                             headers=headers, params=params)

    def list_line_return_requests(self, line_id, headers, params=None):
        return self._request("GET", f"/order-lines/{line_id}/return-requests",
                             headers=headers, params=params)

    # ─── FinancingPlan ────────────────────────────────────────────────────
    def create_financing_plan(self, payload, headers):
        return self._request("POST", "/financing-plans", payload, headers)

    def get_financing_plan(self, plan_id, headers):
        return self._request("GET", f"/financing-plans/{plan_id}", headers=headers)

    def approve_financing_plan(self, plan_id, headers):
        return self._request("POST", f"/financing-plans/{plan_id}/approve", headers=headers)

    def decline_financing_plan(self, plan_id, headers):
        return self._request("POST", f"/financing-plans/{plan_id}/decline", headers=headers)

    def mark_past_due_financing_plan(self, plan_id, headers):
        return self._request("POST", f"/financing-plans/{plan_id}/mark-past-due", headers=headers)

    def default_financing_plan(self, plan_id, headers):
        return self._request("POST", f"/financing-plans/{plan_id}/default", headers=headers)

    def create_payment(self, plan_id, payload, headers):
        return self._request("POST", f"/financing-plans/{plan_id}/payments", payload, headers)

    def list_payments(self, plan_id, headers, params=None):
        return self._request("GET", f"/financing-plans/{plan_id}/payments",
                             headers=headers, params=params)

    # ─── DeliveryRoute ────────────────────────────────────────────────────
    def create_delivery_route(self, payload, headers):
        return self._request("POST", "/delivery-routes", payload, headers)

    def get_delivery_route(self, route_id, headers):
        return self._request("GET", f"/delivery-routes/{route_id}", headers=headers)

    def list_route_stops(self, route_id, headers, params=None):
        return self._request("GET", f"/delivery-routes/{route_id}/stops",
                             headers=headers, params=params)

    def lock_delivery_route(self, route_id, headers):
        return self._request("POST", f"/delivery-routes/{route_id}/lock", headers=headers)

    def complete_delivery_route(self, route_id, headers):
        return self._request("POST", f"/delivery-routes/{route_id}/complete", headers=headers)

    # ─── DeliveryStop ─────────────────────────────────────────────────────
    def create_delivery_stop(self, payload, headers):
        return self._request("POST", "/delivery-stops", payload, headers)

    def get_delivery_stop(self, stop_id, headers):
        return self._request("GET", f"/delivery-stops/{stop_id}", headers=headers)

    def dispatch_delivery_stop(self, stop_id, headers):
        return self._request("POST", f"/delivery-stops/{stop_id}/dispatch", headers=headers)

    def complete_delivery_stop(self, stop_id, headers):
        return self._request("POST", f"/delivery-stops/{stop_id}/complete", headers=headers)

    def cancel_delivery_stop(self, stop_id, headers):
        return self._request("POST", f"/delivery-stops/{stop_id}/cancel", headers=headers)

    # ─── ProtectionPlan ───────────────────────────────────────────────────
    def create_protection_plan(self, payload, headers):
        return self._request("POST", "/protection-plans", payload, headers)

    def get_protection_plan(self, plan_id, headers):
        return self._request("GET", f"/protection-plans/{plan_id}", headers=headers)

    # ─── ReturnRequest ────────────────────────────────────────────────────
    def create_return_request(self, payload, headers):
        return self._request("POST", "/return-requests", payload, headers)

    def get_return_request(self, request_id, headers):
        return self._request("GET", f"/return-requests/{request_id}", headers=headers)

    def approve_return_request(self, request_id, headers):
        return self._request("POST", f"/return-requests/{request_id}/approve", headers=headers)

    def reject_return_request(self, request_id, headers):
        return self._request("POST", f"/return-requests/{request_id}/reject", headers=headers)

    def refund_return_request(self, request_id, headers):
        return self._request("POST", f"/return-requests/{request_id}/refund", headers=headers)

    # ─── Test clock ───────────────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
