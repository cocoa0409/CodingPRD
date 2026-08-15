"""API client: one method per endpoint defined in the PRD.

All resources are mounted under the /roadside prefix. Methods return the raw
requests.Response so tests can assert status codes and envelopes.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock and daily ops run
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/roadside/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def run_daily(self, headers):
        return self._request("POST", "/roadside/_ops/run_daily", {}, headers)

    # ------------------------------------------------------------------
    # Fleet accounts
    # ------------------------------------------------------------------
    def create_fleet_account(self, payload, headers):
        return self._request("POST", "/roadside/fleet-accounts", payload, headers)

    def get_fleet_account(self, fleet_account_id, headers):
        return self._request("GET", f"/roadside/fleet-accounts/{fleet_account_id}",
                             headers=headers)

    def list_fleet_accounts(self, headers, params=None):
        return self._request("GET", "/roadside/fleet-accounts", headers=headers,
                             params=params)

    def patch_fleet_account(self, fleet_account_id, payload, headers):
        return self._request("PATCH", f"/roadside/fleet-accounts/{fleet_account_id}",
                             payload, headers)

    def suspend_fleet_account(self, fleet_account_id, headers):
        return self._request("POST",
                             f"/roadside/fleet-accounts/{fleet_account_id}/suspend",
                             {}, headers)

    def reinstate_fleet_account(self, fleet_account_id, headers):
        return self._request("POST",
                             f"/roadside/fleet-accounts/{fleet_account_id}/reinstate",
                             {}, headers)

    def close_fleet_account(self, fleet_account_id, headers):
        return self._request("POST",
                             f"/roadside/fleet-accounts/{fleet_account_id}/close",
                             {}, headers)

    def post_spend_adjustment(self, fleet_account_id, payload, headers):
        return self._request(
            "POST", f"/roadside/fleet-accounts/{fleet_account_id}/spend-adjustments",
            payload, headers)

    # ------------------------------------------------------------------
    # Vehicles
    # ------------------------------------------------------------------
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/roadside/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/roadside/vehicles/{vehicle_id}",
                             headers=headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/roadside/vehicles", headers=headers,
                             params=params)

    def patch_vehicle(self, vehicle_id, payload, headers):
        return self._request("PATCH", f"/roadside/vehicles/{vehicle_id}",
                             payload, headers)

    # ------------------------------------------------------------------
    # Technicians
    # ------------------------------------------------------------------
    def create_technician(self, payload, headers):
        return self._request("POST", "/roadside/technicians", payload, headers)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"/roadside/technicians/{technician_id}",
                             headers=headers)

    def list_technicians(self, headers, params=None):
        return self._request("GET", "/roadside/technicians", headers=headers,
                             params=params)

    def set_technician_status(self, technician_id, payload, headers):
        return self._request("POST",
                             f"/roadside/technicians/{technician_id}/set-status",
                             payload, headers)

    # ------------------------------------------------------------------
    # Rate cards
    # ------------------------------------------------------------------
    def create_rate_card(self, payload, headers):
        return self._request("POST", "/roadside/rate-cards", payload, headers)

    def get_rate_card(self, rate_card_id, headers):
        return self._request("GET", f"/roadside/rate-cards/{rate_card_id}",
                             headers=headers)

    def list_rate_cards(self, headers, params=None):
        return self._request("GET", "/roadside/rate-cards", headers=headers,
                             params=params)

    # ------------------------------------------------------------------
    # Van stock
    # ------------------------------------------------------------------
    def create_van_stock_item(self, technician_id, payload, headers):
        return self._request("POST",
                             f"/roadside/technicians/{technician_id}/van-stock",
                             payload, headers)

    def get_van_stock_item(self, van_stock_item_id, headers):
        return self._request("GET", f"/roadside/van-stock/{van_stock_item_id}",
                             headers=headers)

    def list_van_stock_items(self, headers, params=None):
        return self._request("GET", "/roadside/van-stock", headers=headers,
                             params=params)

    def adjust_van_stock(self, van_stock_item_id, payload, headers):
        return self._request("POST",
                             f"/roadside/van-stock/{van_stock_item_id}/adjust",
                             payload, headers)

    # ------------------------------------------------------------------
    # Service calls
    # ------------------------------------------------------------------
    def create_service_call(self, payload, headers):
        return self._request("POST", "/roadside/service-calls", payload, headers)

    def get_service_call(self, service_call_id, headers):
        return self._request("GET", f"/roadside/service-calls/{service_call_id}",
                             headers=headers)

    def list_service_calls(self, headers, params=None):
        return self._request("GET", "/roadside/service-calls", headers=headers,
                             params=params)

    def triage_service_call(self, service_call_id, payload, headers):
        return self._request("POST",
                             f"/roadside/service-calls/{service_call_id}/triage",
                             payload, headers)

    def diagnose_service_call(self, service_call_id, payload, headers):
        return self._request("POST",
                             f"/roadside/service-calls/{service_call_id}/diagnose",
                             payload, headers)

    def start_repair(self, service_call_id, headers):
        return self._request("POST",
                             f"/roadside/service-calls/{service_call_id}/start-repair",
                             {}, headers)

    def complete_repair(self, service_call_id, payload, headers):
        return self._request(
            "POST", f"/roadside/service-calls/{service_call_id}/complete-repair",
            payload, headers)

    def cancel_service_call(self, service_call_id, payload, headers):
        return self._request("POST",
                             f"/roadside/service-calls/{service_call_id}/cancel",
                             payload, headers)

    def get_dispatch_suggestion(self, service_call_id, headers):
        return self._request(
            "GET",
            f"/roadside/service-calls/{service_call_id}/dispatch-suggestion",
            headers=headers)

    def list_service_call_events(self, service_call_id, headers, params=None):
        return self._request("GET",
                             f"/roadside/service-calls/{service_call_id}/events",
                             headers=headers, params=params)

    def get_call_event(self, call_event_id, headers):
        return self._request("GET", f"/roadside/call-events/{call_event_id}",
                             headers=headers)

    def list_call_events(self, headers, params=None):
        return self._request("GET", "/roadside/call-events", headers=headers,
                             params=params)

    # ------------------------------------------------------------------
    # Dispatches
    # ------------------------------------------------------------------
    def create_dispatch(self, service_call_id, payload, headers):
        return self._request(
            "POST", f"/roadside/service-calls/{service_call_id}/dispatches",
            payload, headers)

    def get_dispatch(self, dispatch_id, headers):
        return self._request("GET", f"/roadside/dispatches/{dispatch_id}",
                             headers=headers)

    def list_dispatches(self, headers, params=None):
        return self._request("GET", "/roadside/dispatches", headers=headers,
                             params=params)

    def accept_dispatch(self, dispatch_id, headers):
        return self._request("POST", f"/roadside/dispatches/{dispatch_id}/accept",
                             {}, headers)

    def reject_dispatch(self, dispatch_id, payload, headers):
        return self._request("POST", f"/roadside/dispatches/{dispatch_id}/reject",
                             payload, headers)

    def depart_dispatch(self, dispatch_id, headers):
        return self._request("POST", f"/roadside/dispatches/{dispatch_id}/depart",
                             {}, headers)

    def arrive_dispatch(self, dispatch_id, payload, headers):
        return self._request("POST", f"/roadside/dispatches/{dispatch_id}/arrive",
                             payload, headers)

    def complete_dispatch(self, dispatch_id, headers):
        return self._request("POST",
                             f"/roadside/dispatches/{dispatch_id}/complete",
                             {}, headers)

    def release_dispatch(self, dispatch_id, payload, headers):
        return self._request("POST", f"/roadside/dispatches/{dispatch_id}/release",
                             payload, headers)

    # ------------------------------------------------------------------
    # Work estimates
    # ------------------------------------------------------------------
    def create_estimate(self, service_call_id, payload, headers):
        return self._request(
            "POST", f"/roadside/service-calls/{service_call_id}/estimates",
            payload, headers)

    def get_estimate(self, estimate_id, headers):
        return self._request("GET", f"/roadside/estimates/{estimate_id}",
                             headers=headers)

    def list_estimates(self, headers, params=None):
        return self._request("GET", "/roadside/estimates", headers=headers,
                             params=params)

    def patch_estimate(self, estimate_id, payload, headers):
        return self._request("PATCH", f"/roadside/estimates/{estimate_id}",
                             payload, headers)

    def submit_estimate(self, estimate_id, headers):
        return self._request("POST", f"/roadside/estimates/{estimate_id}/submit",
                             {}, headers)

    def approve_estimate(self, estimate_id, payload, headers):
        return self._request("POST", f"/roadside/estimates/{estimate_id}/approve",
                             payload, headers)

    def reject_estimate(self, estimate_id, payload, headers):
        return self._request("POST", f"/roadside/estimates/{estimate_id}/reject",
                             payload, headers)

    # ------------------------------------------------------------------
    # Part usages
    # ------------------------------------------------------------------
    def create_part_usage(self, service_call_id, payload, headers):
        return self._request(
            "POST", f"/roadside/service-calls/{service_call_id}/part-usages",
            payload, headers)

    def get_part_usage(self, part_usage_id, headers):
        return self._request("GET", f"/roadside/part-usages/{part_usage_id}",
                             headers=headers)

    def list_part_usages(self, headers, params=None):
        return self._request("GET", "/roadside/part-usages", headers=headers,
                             params=params)

    def return_part_usage(self, part_usage_id, headers):
        return self._request("POST",
                             f"/roadside/part-usages/{part_usage_id}/return",
                             {}, headers)

    # ------------------------------------------------------------------
    # Tow orders
    # ------------------------------------------------------------------
    def create_tow_order(self, service_call_id, payload, headers):
        return self._request(
            "POST", f"/roadside/service-calls/{service_call_id}/tow-orders",
            payload, headers)

    def get_tow_order(self, tow_order_id, headers):
        return self._request("GET", f"/roadside/tow-orders/{tow_order_id}",
                             headers=headers)

    def list_tow_orders(self, headers, params=None):
        return self._request("GET", "/roadside/tow-orders", headers=headers,
                             params=params)

    def hook_tow_order(self, tow_order_id, headers):
        return self._request("POST", f"/roadside/tow-orders/{tow_order_id}/hook",
                             {}, headers)

    def deliver_tow_order(self, tow_order_id, headers):
        return self._request("POST",
                             f"/roadside/tow-orders/{tow_order_id}/deliver",
                             {}, headers)

    def cancel_tow_order(self, tow_order_id, headers):
        return self._request("POST",
                             f"/roadside/tow-orders/{tow_order_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Warranty claims
    # ------------------------------------------------------------------
    def create_warranty_claim(self, service_call_id, payload, headers):
        return self._request(
            "POST", f"/roadside/service-calls/{service_call_id}/warranty-claims",
            payload, headers)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/roadside/warranty-claims/{claim_id}",
                             headers=headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", "/roadside/warranty-claims", headers=headers,
                             params=params)

    def submit_warranty_claim(self, claim_id, headers):
        return self._request("POST",
                             f"/roadside/warranty-claims/{claim_id}/submit",
                             {}, headers)

    def decide_warranty_claim(self, claim_id, payload, headers):
        return self._request("POST",
                             f"/roadside/warranty-claims/{claim_id}/decide",
                             payload, headers)

    def appeal_warranty_claim(self, claim_id, headers):
        return self._request("POST",
                             f"/roadside/warranty-claims/{claim_id}/appeal",
                             {}, headers)

    def settle_warranty_claim(self, claim_id, payload, headers):
        return self._request("POST",
                             f"/roadside/warranty-claims/{claim_id}/settle",
                             payload, headers)

    # ------------------------------------------------------------------
    # Inspection defects
    # ------------------------------------------------------------------
    def create_inspection_defect(self, vehicle_id, payload, headers):
        return self._request(
            "POST", f"/roadside/vehicles/{vehicle_id}/inspection-defects",
            payload, headers)

    def get_inspection_defect(self, inspection_defect_id, headers):
        return self._request(
            "GET", f"/roadside/inspection-defects/{inspection_defect_id}",
            headers=headers)

    def list_inspection_defects(self, headers, params=None):
        return self._request("GET", "/roadside/inspection-defects",
                             headers=headers, params=params)

    def attach_defect_call(self, inspection_defect_id, payload, headers):
        return self._request(
            "POST",
            f"/roadside/inspection-defects/{inspection_defect_id}/attach-call",
            payload, headers)

    def mark_defect_corrected(self, inspection_defect_id, payload, headers):
        return self._request(
            "POST",
            f"/roadside/inspection-defects/{inspection_defect_id}/mark-corrected",
            payload, headers)

    def verify_defect(self, inspection_defect_id, payload, headers):
        return self._request(
            "POST", f"/roadside/inspection-defects/{inspection_defect_id}/verify",
            payload, headers)

    # ------------------------------------------------------------------
    # Invoices
    # ------------------------------------------------------------------
    def create_invoice(self, service_call_id, headers):
        return self._request(
            "POST", f"/roadside/service-calls/{service_call_id}/invoices",
            {}, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/roadside/invoices/{invoice_id}",
                             headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/roadside/invoices", headers=headers,
                             params=params)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/roadside/invoices/{invoice_id}/issue",
                             {}, headers)

    def void_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/roadside/invoices/{invoice_id}/void",
                             payload, headers)

    def writeoff_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/roadside/invoices/{invoice_id}/write-off",
                             payload, headers)

    # ------------------------------------------------------------------
    # Payments
    # ------------------------------------------------------------------
    def post_payment(self, invoice_id, payload, headers):
        return self._request("POST", f"/roadside/invoices/{invoice_id}/payments",
                             payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/roadside/payments/{payment_id}",
                             headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/roadside/payments", headers=headers,
                             params=params)

    def void_payment(self, payment_id, payload, headers):
        return self._request("POST", f"/roadside/payments/{payment_id}/void",
                             payload, headers)

    # ------------------------------------------------------------------
    # Repeat-failure cases
    # ------------------------------------------------------------------
    def create_repeat_failure_case(self, payload, headers):
        return self._request("POST", "/roadside/repeat-failure-cases", payload,
                             headers)

    def get_repeat_failure_case(self, repeat_failure_case_id, headers):
        return self._request(
            "GET", f"/roadside/repeat-failure-cases/{repeat_failure_case_id}",
            headers=headers)

    def list_repeat_failure_cases(self, headers, params=None):
        return self._request("GET", "/roadside/repeat-failure-cases",
                             headers=headers, params=params)

    def review_repeat_failure_case(self, repeat_failure_case_id, headers):
        return self._request(
            "POST",
            f"/roadside/repeat-failure-cases/{repeat_failure_case_id}/review",
            {}, headers)

    def decide_repeat_failure_case(self, repeat_failure_case_id, payload, headers):
        return self._request(
            "POST",
            f"/roadside/repeat-failure-cases/{repeat_failure_case_id}/decide",
            payload, headers)

    # ------------------------------------------------------------------
    # Restock requests
    # ------------------------------------------------------------------
    def get_restock_request(self, restock_request_id, headers):
        return self._request(
            "GET", f"/roadside/restock-requests/{restock_request_id}",
            headers=headers)

    def list_restock_requests(self, headers, params=None):
        return self._request("GET", "/roadside/restock-requests", headers=headers,
                             params=params)

    def approve_restock_request(self, restock_request_id, headers):
        return self._request(
            "POST", f"/roadside/restock-requests/{restock_request_id}/approve",
            {}, headers)

    def fulfill_restock_request(self, restock_request_id, payload, headers):
        return self._request(
            "POST", f"/roadside/restock-requests/{restock_request_id}/fulfill",
            payload, headers)

    def reject_restock_request(self, restock_request_id, payload, headers):
        return self._request(
            "POST", f"/roadside/restock-requests/{restock_request_id}/reject",
            payload, headers)


api_client = ApiClient()
