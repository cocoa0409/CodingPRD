"""API client: one method per endpoint defined in PRD §4."""
from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601: str, headers: Dict):
        return self._request(
            "POST", "/fab/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- customers ---
    def create_customer(self, payload: Dict, headers: Dict):
        return self._request("POST", "/fab/customers", payload, headers)

    def list_customers(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/fab/customers", headers=headers, params=params)

    def get_customer(self, customer_id: str, headers: Dict):
        return self._request("GET", f"/fab/customers/{customer_id}", headers=headers)

    def suspend_customer(self, customer_id: str, headers: Dict):
        return self._request("POST", f"/fab/customers/{customer_id}/suspend", {}, headers)

    # --- material grades ---
    def create_material_grade(self, payload: Dict, headers: Dict):
        return self._request("POST", "/fab/material-grades", payload, headers)

    def list_material_grades(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/fab/material-grades", headers=headers, params=params)

    def get_material_grade(self, grade_id: str, headers: Dict):
        return self._request("GET", f"/fab/material-grades/{grade_id}", headers=headers)

    # --- sheet stock ---
    def create_sheet_stock(self, payload: Dict, headers: Dict):
        return self._request("POST", "/fab/sheet-stock", payload, headers)

    def list_sheet_stock(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/fab/sheet-stock", headers=headers, params=params)

    def get_sheet_stock(self, stock_id: str, headers: Dict):
        return self._request("GET", f"/fab/sheet-stock/{stock_id}", headers=headers)

    def scrap_sheet_stock(self, stock_id: str, headers: Dict):
        return self._request("POST", f"/fab/sheet-stock/{stock_id}/scrap", {}, headers)

    # --- machines ---
    def create_machine(self, payload: Dict, headers: Dict):
        return self._request("POST", "/fab/machines", payload, headers)

    def list_machines(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/fab/machines", headers=headers, params=params)

    def get_machine(self, machine_id: str, headers: Dict):
        return self._request("GET", f"/fab/machines/{machine_id}", headers=headers)

    def list_machine_routing_steps(self, machine_id: str, headers: Dict,
                                   params: Optional[Dict] = None):
        return self._request(
            "GET", f"/fab/machines/{machine_id}/routing-steps",
            headers=headers, params=params,
        )

    def set_machine_status(self, machine_id: str, status: str, headers: Dict):
        return self._request(
            "POST", f"/fab/machines/{machine_id}/status", {"status": status}, headers,
        )

    # --- outside vendors ---
    def create_outside_vendor(self, payload: Dict, headers: Dict):
        return self._request("POST", "/fab/outside-vendors", payload, headers)

    def list_outside_vendors(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/fab/outside-vendors", headers=headers, params=params)

    def get_outside_vendor(self, vendor_id: str, headers: Dict):
        return self._request("GET", f"/fab/outside-vendors/{vendor_id}", headers=headers)

    def list_vendor_routing_steps(self, vendor_id: str, headers: Dict,
                                  params: Optional[Dict] = None):
        return self._request(
            "GET", f"/fab/outside-vendors/{vendor_id}/routing-steps",
            headers=headers, params=params,
        )

    # --- quotes & lines ---
    def create_quote(self, payload: Dict, headers: Dict):
        return self._request("POST", "/fab/quotes", payload, headers)

    def list_quotes(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/fab/quotes", headers=headers, params=params)

    def get_quote(self, quote_id: str, headers: Dict):
        return self._request("GET", f"/fab/quotes/{quote_id}", headers=headers)

    def add_quote_line(self, quote_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/fab/quotes/{quote_id}/lines", payload, headers)

    def list_quote_lines(self, quote_id: str, headers: Dict,
                         params: Optional[Dict] = None):
        return self._request(
            "GET", f"/fab/quotes/{quote_id}/lines", headers=headers, params=params,
        )

    def get_quote_line(self, line_id: str, headers: Dict):
        return self._request("GET", f"/fab/quote-lines/{line_id}", headers=headers)

    def filter_quote_lines(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/fab/quote-lines", headers=headers, params=params)

    def price_quote(self, quote_id: str, expected_quote_version: int, headers: Dict):
        return self._request(
            "POST", f"/fab/quotes/{quote_id}/price",
            {"expected_quote_version": expected_quote_version}, headers,
        )

    def submit_quote(self, quote_id: str, headers: Dict):
        return self._request("POST", f"/fab/quotes/{quote_id}/submit", {}, headers)

    def revise_quote(self, quote_id: str, headers: Dict):
        return self._request("POST", f"/fab/quotes/{quote_id}/revise", {}, headers)

    def accept_quote(self, quote_id: str, headers: Dict):
        return self._request("POST", f"/fab/quotes/{quote_id}/accept", {}, headers)

    def reject_quote(self, quote_id: str, headers: Dict):
        return self._request("POST", f"/fab/quotes/{quote_id}/reject", {}, headers)

    # --- orders ---
    def list_orders(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/fab/orders", headers=headers, params=params)

    def get_order(self, order_id: str, headers: Dict):
        return self._request("GET", f"/fab/orders/{order_id}", headers=headers)

    def renest_order(self, order_id: str, headers: Dict):
        return self._request("POST", f"/fab/orders/{order_id}/renest", {}, headers)

    def release_order(self, order_id: str, headers: Dict):
        return self._request("POST", f"/fab/orders/{order_id}/release", {}, headers)

    def receive_outside(self, order_id: str, headers: Dict):
        return self._request(
            "POST", f"/fab/orders/{order_id}/receive-outside", {}, headers,
        )

    def hold_order(self, order_id: str, hold_reason: str, headers: Dict):
        return self._request(
            "POST", f"/fab/orders/{order_id}/hold", {"hold_reason": hold_reason}, headers,
        )

    def resume_order(self, order_id: str, headers: Dict):
        return self._request("POST", f"/fab/orders/{order_id}/resume", {}, headers)

    def cancel_order(self, order_id: str, headers: Dict):
        return self._request("POST", f"/fab/orders/{order_id}/cancel", {}, headers)

    def submit_inspection_report(self, order_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/fab/orders/{order_id}/inspection-reports", payload, headers,
        )

    def list_inspection_reports(self, order_id: str, headers: Dict,
                                params: Optional[Dict] = None):
        return self._request(
            "GET", f"/fab/orders/{order_id}/inspection-reports",
            headers=headers, params=params,
        )

    def pay_order(self, order_id: str, payload: Optional[Dict], headers: Dict):
        return self._request(
            "POST", f"/fab/orders/{order_id}/payment", payload or {}, headers,
        )

    # --- nest sheets & routing ---
    def list_order_nest_sheets(self, order_id: str, headers: Dict,
                               params: Optional[Dict] = None):
        return self._request(
            "GET", f"/fab/orders/{order_id}/nest-sheets", headers=headers, params=params,
        )

    def filter_nest_sheets(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/fab/nest-sheets", headers=headers, params=params)

    def get_nest_sheet(self, nest_sheet_id: str, headers: Dict):
        return self._request("GET", f"/fab/nest-sheets/{nest_sheet_id}", headers=headers)

    def list_order_routing_steps(self, order_id: str, headers: Dict,
                                 params: Optional[Dict] = None):
        return self._request(
            "GET", f"/fab/orders/{order_id}/routing-steps",
            headers=headers, params=params,
        )

    def filter_routing_steps(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/fab/routing-steps", headers=headers, params=params)

    def complete_routing_step(self, step_id: str, headers: Dict):
        return self._request("POST", f"/fab/routing-steps/{step_id}/complete", {}, headers)

    def skip_routing_step(self, step_id: str, headers: Dict):
        return self._request("POST", f"/fab/routing-steps/{step_id}/skip", {}, headers)

    # --- scrap credits ---
    def create_scrap_credit(self, payload: Dict, headers: Dict):
        return self._request("POST", "/fab/scrap-credits", payload, headers)

    def list_scrap_credits(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/fab/scrap-credits", headers=headers, params=params)

    def get_scrap_credit(self, credit_id: str, headers: Dict):
        return self._request("GET", f"/fab/scrap-credits/{credit_id}", headers=headers)

    def void_scrap_credit(self, credit_id: str, expected_customer_version: int,
                          headers: Dict):
        return self._request(
            "POST", f"/fab/scrap-credits/{credit_id}/void",
            {"expected_customer_version": expected_customer_version}, headers,
        )

    # --- audit ---
    def list_audit_events(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/fab/audit-events", headers=headers, params=params)


api_client = ApiClient()
