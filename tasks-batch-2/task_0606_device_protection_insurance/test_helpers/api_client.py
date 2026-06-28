"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- reference data ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def create_plan(self, payload, headers):
        return self._request("POST", "/plans", payload, headers)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/plans/{plan_id}", headers=headers)

    def create_replacement_sku(self, payload, headers):
        return self._request("POST", "/replacement-skus", payload, headers)

    def get_replacement_sku(self, sku_id, headers):
        return self._request("GET", f"/replacement-skus/{sku_id}", headers=headers)

    # ---- enrollments ----
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def activate_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/activate", headers=headers)

    def suspend_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/suspend", headers=headers)

    def cancel_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/cancel", headers=headers)

    # ---- premium invoices ----
    def create_premium_invoice(self, payload, headers):
        return self._request("POST", "/premium-invoices", payload, headers)

    def list_premium_invoices(self, headers, params=None):
        return self._request("GET", "/premium-invoices", headers=headers, params=params)

    def get_premium_invoice(self, invoice_id, headers):
        return self._request("GET", f"/premium-invoices/{invoice_id}", headers=headers)

    def pay_premium_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/premium-invoices/{invoice_id}/pay", payload, headers)

    # ---- claims ----
    def create_claim(self, payload, headers):
        return self._request("POST", "/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def screen_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/screen", headers=headers)

    def approve_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/approve", payload, headers)

    def route_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/route", payload, headers)

    def deny_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/deny", payload, headers)

    def withdraw_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/withdraw", headers=headers)

    # ---- fraud screens ----
    def list_fraud_screens(self, headers, params=None):
        return self._request("GET", "/fraud-screens", headers=headers, params=params)

    def get_fraud_screen(self, fraud_screen_id, headers):
        return self._request("GET", f"/fraud-screens/{fraud_screen_id}", headers=headers)

    # ---- repair orders ----
    def list_repair_orders(self, headers, params=None):
        return self._request("GET", "/repair-orders", headers=headers, params=params)

    def get_repair_order(self, repair_order_id, headers):
        return self._request("GET", f"/repair-orders/{repair_order_id}", headers=headers)

    def complete_repair_order(self, repair_order_id, headers):
        return self._request("POST", f"/repair-orders/{repair_order_id}/complete", headers=headers)

    # ---- advanced exchanges ----
    def list_advanced_exchanges(self, headers, params=None):
        return self._request("GET", "/advanced-exchanges", headers=headers, params=params)

    def get_advanced_exchange(self, exchange_id, headers):
        return self._request("GET", f"/advanced-exchanges/{exchange_id}", headers=headers)

    def ship_advanced_exchange(self, exchange_id, payload, headers):
        return self._request("POST", f"/advanced-exchanges/{exchange_id}/ship", payload, headers)

    def deliver_advanced_exchange(self, exchange_id, headers):
        return self._request("POST", f"/advanced-exchanges/{exchange_id}/deliver", headers=headers)

    def close_advanced_exchange(self, exchange_id, headers):
        return self._request("POST", f"/advanced-exchanges/{exchange_id}/close", headers=headers)

    def cancel_advanced_exchange(self, exchange_id, headers):
        return self._request("POST", f"/advanced-exchanges/{exchange_id}/cancel", headers=headers)

    # ---- trade-ins ----
    def create_trade_in(self, payload, headers):
        return self._request("POST", "/trade-ins", payload, headers)

    def list_trade_ins(self, headers, params=None):
        return self._request("GET", "/trade-ins", headers=headers, params=params)

    def get_trade_in(self, trade_in_id, headers):
        return self._request("GET", f"/trade-ins/{trade_in_id}", headers=headers)

    def grade_trade_in(self, trade_in_id, headers):
        return self._request("POST", f"/trade-ins/{trade_in_id}/grade", headers=headers)

    def credit_trade_in(self, trade_in_id, headers):
        return self._request("POST", f"/trade-ins/{trade_in_id}/credit", headers=headers)

    def recycle_trade_in(self, trade_in_id, headers):
        return self._request("POST", f"/trade-ins/{trade_in_id}/recycle", headers=headers)

    # ---- clock / sweeps ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_return_sweep(self, headers):
        return self._request("POST", "/_clock/run_return_sweep", headers=headers)


api_client = ApiClient()
