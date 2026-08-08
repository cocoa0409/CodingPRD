"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Rate schedules ---
    def create_rate_schedule(self, payload, headers):
        return self._request("POST", "/rate-schedules", payload, headers)

    def get_rate_schedule(self, schedule_id, headers):
        return self._request("GET", f"/rate-schedules/{schedule_id}", headers=headers)

    # --- Accounts ---
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/accounts", headers=headers, params=params)

    def enroll_assistance(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/assistance", payload, headers)

    def finalize_account(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/finalize", payload, headers)

    # --- Meters ---
    def create_meter(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/meters", payload, headers)

    def list_meters(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/meters", headers=headers, params=params)

    def get_meter(self, meter_id, headers):
        return self._request("GET", f"/meters/{meter_id}", headers=headers)

    def create_reading(self, meter_id, payload, headers):
        return self._request("POST", f"/meters/{meter_id}/readings", payload, headers)

    def list_readings(self, meter_id, headers, params=None):
        return self._request("GET", f"/meters/{meter_id}/readings", headers=headers, params=params)

    # --- Bills ---
    def create_bill(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/bills", payload, headers)

    def get_bill(self, bill_id, headers):
        return self._request("GET", f"/bills/{bill_id}", headers=headers)

    def list_bills(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/bills", headers=headers, params=params)

    def mark_delinquent(self, bill_id, headers):
        return self._request("POST", f"/bills/{bill_id}/mark-delinquent", {}, headers)

    # --- Payments ---
    def create_payment(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/payments", payload, headers)

    def list_payments(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/payments", headers=headers, params=params)

    def reverse_payment(self, payment_id, headers):
        return self._request("POST", f"/payments/{payment_id}/reverse", {}, headers)

    # --- Budget billing ---
    def create_budget_plan(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/budget-billing-plan", payload, headers)

    def list_budget_plans(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/budget-billing-plan", headers=headers, params=params)

    def true_up_plan(self, plan_id, headers):
        return self._request("POST", f"/budget-billing-plans/{plan_id}/true-up", {}, headers)

    # --- Deposits ---
    def create_deposit(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/deposits", payload, headers)

    def list_deposits(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/deposits", headers=headers, params=params)

    # --- Payment arrangements ---
    def create_arrangement(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/payment-arrangements", payload, headers)

    def list_arrangements(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/payment-arrangements", headers=headers, params=params)

    def record_missed(self, arrangement_id, headers):
        return self._request("POST", f"/payment-arrangements/{arrangement_id}/record-missed", {}, headers)

    def reinstate_arrangement(self, arrangement_id, headers):
        return self._request("POST", f"/payment-arrangements/{arrangement_id}/reinstate", {}, headers)

    # --- Adjustments ---
    def create_adjustment(self, bill_id, payload, headers):
        return self._request("POST", f"/bills/{bill_id}/adjustments", payload, headers)

    def list_adjustments(self, bill_id, headers, params=None):
        return self._request("GET", f"/bills/{bill_id}/adjustments", headers=headers, params=params)

    def approve_adjustment(self, adjustment_id, headers):
        return self._request("POST", f"/adjustments/{adjustment_id}/approve", {}, headers)

    def reject_adjustment(self, adjustment_id, headers):
        return self._request("POST", f"/adjustments/{adjustment_id}/reject", {}, headers)

    # --- Shutoff orders ---
    def create_shutoff_order(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/shutoff-orders", payload, headers)

    def list_shutoff_orders(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/shutoff-orders", headers=headers, params=params)

    def execute_shutoff(self, shutoff_id, headers):
        return self._request("POST", f"/shutoff-orders/{shutoff_id}/execute", {}, headers)

    # --- Lien transfers ---
    def create_lien_transfer(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/lien-transfers", payload, headers)

    def list_lien_transfers(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/lien-transfers", headers=headers, params=params)

    def certify_lien(self, lien_id, headers):
        return self._request("POST", f"/lien-transfers/{lien_id}/certify", {}, headers)

    # --- Moratorium windows ---
    def create_moratorium_window(self, payload, headers):
        return self._request("POST", "/moratorium-windows", payload, headers)

    def list_account_moratorium_windows(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/moratorium-windows", headers=headers, params=params)

    def get_moratorium_window(self, window_id, headers):
        return self._request("GET", f"/moratorium-windows/{window_id}", headers=headers)

    # --- Logical clock (auth-exempt test driver) ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
