"""API client: one method per endpoint defined in the PRD (§4).

Subclasses the framework GenericApiClient; the base _request() does envelope
handling, header injection, and HTTP transport.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- RateSchedule ----------------------------------------------------
    def create_rate_schedule(self, payload, headers):
        return self._request("POST", "/rate-schedules", payload, headers=headers)

    def get_rate_schedule(self, rate_schedule_id, headers):
        return self._request("GET", f"/rate-schedules/{rate_schedule_id}", headers=headers)

    # ---- Account ---------------------------------------------------------
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers=headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/accounts", headers=headers, params=params)

    # ---- Meter -----------------------------------------------------------
    def create_meter(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/meters", payload, headers=headers)

    def list_meters(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/meters", headers=headers, params=params)

    def get_meter(self, meter_id, headers):
        return self._request("GET", f"/meters/{meter_id}", headers=headers)

    # ---- MeterRead -------------------------------------------------------
    def create_read(self, meter_id, payload, headers):
        return self._request("POST", f"/meters/{meter_id}/reads", payload, headers=headers)

    def list_reads(self, meter_id, headers, params=None):
        return self._request("GET", f"/meters/{meter_id}/reads", headers=headers, params=params)

    # ---- BillingCycle ----------------------------------------------------
    def create_billing_cycle(self, payload, headers):
        return self._request("POST", "/billing-cycles", payload, headers=headers)

    def get_billing_cycle(self, cycle_id, headers):
        return self._request("GET", f"/billing-cycles/{cycle_id}", headers=headers)

    def close_billing_cycle(self, cycle_id, headers):
        return self._request("POST", f"/billing-cycles/{cycle_id}/close", {}, headers=headers)

    # ---- Bill ------------------------------------------------------------
    def create_bill(self, payload, headers):
        return self._request("POST", "/bills", payload, headers=headers)

    def get_bill(self, bill_id, headers):
        return self._request("GET", f"/bills/{bill_id}", headers=headers)

    def list_bills(self, headers, params=None):
        return self._request("GET", "/bills", headers=headers, params=params)

    def post_bill(self, bill_id, headers):
        return self._request("POST", f"/bills/{bill_id}/post", {}, headers=headers)

    def void_bill(self, bill_id, headers):
        return self._request("POST", f"/bills/{bill_id}/void", {}, headers=headers)

    # ---- BudgetBillingPlan ----------------------------------------------
    def create_budget_plan(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/budget-billing-plans", payload, headers=headers)

    def list_budget_plans(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/budget-billing-plans", headers=headers, params=params)

    def true_up_budget_plan(self, plan_id, headers):
        return self._request("POST", f"/budget-billing-plans/{plan_id}/true-up", {}, headers=headers)

    # ---- AssistanceEnrollment -------------------------------------------
    def create_assistance_enrollment(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/assistance-enrollments", payload, headers=headers)

    def list_assistance_enrollments(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/assistance-enrollments", headers=headers, params=params)

    def revoke_assistance_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/assistance-enrollments/{enrollment_id}/revoke", {}, headers=headers)

    # ---- LeakAdjustment --------------------------------------------------
    def create_leak_adjustment(self, payload, headers):
        return self._request("POST", "/leak-adjustments", payload, headers=headers)

    def get_leak_adjustment(self, leak_id, headers):
        return self._request("GET", f"/leak-adjustments/{leak_id}", headers=headers)

    def list_leak_adjustments(self, headers, params=None):
        return self._request("GET", "/leak-adjustments", headers=headers, params=params)

    def approve_leak_adjustment(self, leak_id, headers):
        return self._request("POST", f"/leak-adjustments/{leak_id}/approve", {}, headers=headers)

    def deny_leak_adjustment(self, leak_id, headers):
        return self._request("POST", f"/leak-adjustments/{leak_id}/deny", {}, headers=headers)

    # ---- ShutoffOrder ----------------------------------------------------
    def create_shutoff_order(self, payload, headers):
        return self._request("POST", "/shutoff-orders", payload, headers=headers)

    def get_shutoff_order(self, order_id, headers):
        return self._request("GET", f"/shutoff-orders/{order_id}", headers=headers)

    def list_shutoff_orders(self, headers, params=None):
        return self._request("GET", "/shutoff-orders", headers=headers, params=params)

    def execute_shutoff_order(self, order_id, headers):
        return self._request("POST", f"/shutoff-orders/{order_id}/execute", {}, headers=headers)

    def reconnect_shutoff_order(self, order_id, headers):
        return self._request("POST", f"/shutoff-orders/{order_id}/reconnect", {}, headers=headers)

    def cancel_shutoff_order(self, order_id, headers):
        return self._request("POST", f"/shutoff-orders/{order_id}/cancel", {}, headers=headers)

    # ---- Moratorium ------------------------------------------------------
    def create_moratorium(self, payload, headers):
        return self._request("POST", "/moratoriums", payload, headers=headers)

    def list_moratoriums(self, headers, params=None):
        return self._request("GET", "/moratoriums", headers=headers, params=params)

    # ---- Payment ---------------------------------------------------------
    def create_payment(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/payments", payload, headers=headers)

    def list_payments(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/payments", headers=headers, params=params)

    # ---- Test-driving clock ---------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers=headers)


api_client = ApiClient()
