"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Customer ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customer_orders(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/customers/{customer_id}/framing-orders", headers=headers, params=params
        )

    # ---- Workbench ----
    def create_workbench(self, payload, headers):
        return self._request("POST", "/workbenches", payload, headers)

    def list_workbenches(self, headers, params=None):
        return self._request("GET", "/workbenches", headers=headers, params=params)

    def get_workbench(self, workbench_id, headers):
        return self._request("GET", f"/workbenches/{workbench_id}", headers=headers)

    def list_workbench_tasks(self, workbench_id, headers, params=None):
        return self._request(
            "GET", f"/workbenches/{workbench_id}/production-tasks", headers=headers, params=params
        )

    # ---- FramingOrder ----
    def create_order(self, payload, headers):
        return self._request("POST", "/framing-orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/framing-orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/framing-orders/{order_id}", headers=headers)

    def quote_order(self, order_id, headers):
        return self._request("POST", f"/framing-orders/{order_id}/quote", {}, headers)

    def reopen_intake(self, order_id, headers):
        return self._request("POST", f"/framing-orders/{order_id}/reopen-intake", {}, headers)

    def start_production(self, order_id, headers):
        return self._request("POST", f"/framing-orders/{order_id}/start-production", {}, headers)

    def mark_ready(self, order_id, headers):
        return self._request("POST", f"/framing-orders/{order_id}/mark-ready", {}, headers)

    def pickup_order(self, order_id, headers):
        return self._request("POST", f"/framing-orders/{order_id}/pickup", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/framing-orders/{order_id}/cancel", {}, headers)

    def reorder(self, order_id, payload, headers):
        return self._request("POST", f"/framing-orders/{order_id}/reorder", payload, headers)

    # ---- FrameLine ----
    def add_frame_line(self, order_id, payload, headers):
        return self._request("POST", f"/framing-orders/{order_id}/frame-lines", payload, headers)

    def list_frame_lines(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/framing-orders/{order_id}/frame-lines", headers=headers, params=params
        )

    def get_frame_line(self, line_id, headers):
        return self._request("GET", f"/frame-lines/{line_id}", headers=headers)

    def measure_frame_line(self, line_id, payload, headers):
        return self._request("POST", f"/frame-lines/{line_id}/measure", payload, headers)

    def void_frame_line(self, line_id, headers):
        return self._request("POST", f"/frame-lines/{line_id}/void", {}, headers)

    # ---- ProductionTask ----
    def create_task(self, payload, headers):
        return self._request("POST", "/production-tasks", payload, headers)

    def list_order_tasks(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/framing-orders/{order_id}/production-tasks", headers=headers, params=params
        )

    def get_task(self, task_id, headers):
        return self._request("GET", f"/production-tasks/{task_id}", headers=headers)

    def complete_task(self, task_id, headers):
        return self._request("POST", f"/production-tasks/{task_id}/complete", {}, headers)

    # ---- Payment ----
    def apply_payment(self, order_id, payload, headers):
        return self._request("POST", f"/framing-orders/{order_id}/payments", payload, headers)

    def list_payments(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/framing-orders/{order_id}/payments", headers=headers, params=params
        )

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    # ---- Notification ----
    def list_notifications(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/framing-orders/{order_id}/notifications", headers=headers, params=params
        )


api_client = ApiClient()
