"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clock (test-driving) ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set", payload, headers=headers)

    def get_clock(self, headers):
        return self._request("GET", "/_clock", headers=headers)

    def inject_ontime_count(self, payload, headers):
        return self._request("POST", "/_inject/account-ontime-count", payload, headers=headers)

    # ---- RateSchedule ----
    def create_rate_schedule(self, payload, headers):
        return self._request("POST", "/rate-schedules", payload, headers=headers)

    def get_rate_schedule(self, rate_schedule_id, headers):
        return self._request("GET", f"/rate-schedules/{rate_schedule_id}", headers=headers)

    # ---- PgaSchedule ----
    def create_pga_schedule(self, payload, headers):
        return self._request("POST", "/pga-schedules", payload, headers=headers)

    def get_pga_schedule(self, pga_schedule_id, headers):
        return self._request("GET", f"/pga-schedules/{pga_schedule_id}", headers=headers)

    # ---- Account ----
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/accounts", headers=headers, params=params)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def shutoff_notice(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/shutoff-notice", {}, headers=headers)

    def cancel_shutoff(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/cancel-shutoff", {}, headers=headers)

    def final_bill(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/final-bill", {}, headers=headers)

    # ---- PremiseMeter ----
    def create_meter(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/meters", payload, headers=headers)

    def list_meters(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/meters", headers=headers, params=params)

    def get_meter(self, meter_id, headers):
        return self._request("GET", f"/meters/{meter_id}", headers=headers)

    def remove_meter(self, meter_id, headers):
        return self._request("POST", f"/meters/{meter_id}/remove", {}, headers=headers)

    # ---- MeterRead ----
    def post_read(self, meter_id, payload, headers):
        return self._request("POST", f"/meters/{meter_id}/reads", payload, headers=headers)

    def list_meter_reads(self, headers, params=None):
        return self._request("GET", "/meter-reads", headers=headers, params=params)

    def get_meter_read(self, read_id, headers):
        return self._request("GET", f"/meter-reads/{read_id}", headers=headers)

    def void_read(self, meter_id, read_id, headers):
        return self._request("POST", f"/meters/{meter_id}/reads/{read_id}/void", {}, headers=headers)

    # ---- Bill ----
    def create_bill(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/bills", payload, headers=headers)

    def list_bills(self, headers, params=None):
        return self._request("GET", "/bills", headers=headers, params=params)

    def get_bill(self, bill_id, headers):
        return self._request("GET", f"/bills/{bill_id}", headers=headers)

    def issue_bill(self, account_id, bill_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/bills/{bill_id}/issue", payload, headers=headers)

    def void_bill(self, account_id, bill_id, headers):
        return self._request("POST", f"/accounts/{account_id}/bills/{bill_id}/void", {}, headers=headers)

    # ---- Payment ----
    def create_payment(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/payments", payload, headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    # ---- BudgetPlan ----
    def create_budget_plan(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/budget-plans", payload, headers=headers)

    def list_budget_plans(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/budget-plans", headers=headers, params=params)

    def true_up_budget_plan(self, account_id, plan_id, headers):
        return self._request("POST", f"/accounts/{account_id}/budget-plans/{plan_id}/true-up", {}, headers=headers)

    def cancel_budget_plan(self, account_id, plan_id, headers):
        return self._request("POST", f"/accounts/{account_id}/budget-plans/{plan_id}/cancel", {}, headers=headers)

    # ---- Deposit ----
    def create_deposit(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/deposits", payload, headers=headers)

    def list_deposits(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/deposits", headers=headers, params=params)

    def collect_deposit(self, account_id, deposit_id, headers):
        return self._request("POST", f"/accounts/{account_id}/deposits/{deposit_id}/collect", {}, headers=headers)

    def waive_deposit(self, account_id, deposit_id, headers):
        return self._request("POST", f"/accounts/{account_id}/deposits/{deposit_id}/waive", {}, headers=headers)

    def refund_deposit(self, account_id, deposit_id, headers):
        return self._request("POST", f"/accounts/{account_id}/deposits/{deposit_id}/refund", {}, headers=headers)

    # ---- LowIncomeCredit ----
    def create_low_income_credit(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/low-income-credits", payload, headers=headers)

    def list_low_income_credits(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/low-income-credits", headers=headers, params=params)

    def approve_low_income_credit(self, account_id, credit_id, headers):
        return self._request("POST", f"/accounts/{account_id}/low-income-credits/{credit_id}/approve", {}, headers=headers)

    def deny_low_income_credit(self, account_id, credit_id, headers):
        return self._request("POST", f"/accounts/{account_id}/low-income-credits/{credit_id}/deny", {}, headers=headers)

    def expire_low_income_credit(self, account_id, credit_id, headers):
        return self._request("POST", f"/accounts/{account_id}/low-income-credits/{credit_id}/expire", {}, headers=headers)

    # ---- ServiceOrder ----
    def create_service_order(self, payload, headers):
        return self._request("POST", "/service-orders", payload, headers=headers)

    def get_service_order(self, order_id, headers):
        return self._request("GET", f"/service-orders/{order_id}", headers=headers)

    def list_service_orders(self, headers, params=None):
        return self._request("GET", "/service-orders", headers=headers, params=params)

    def dispatch_service_order(self, order_id, headers):
        return self._request("POST", f"/service-orders/{order_id}/dispatch", {}, headers=headers)

    def complete_service_order(self, order_id, payload, headers):
        return self._request("POST", f"/service-orders/{order_id}/complete", payload, headers=headers)

    def cancel_service_order(self, order_id, headers):
        return self._request("POST", f"/service-orders/{order_id}/cancel", {}, headers=headers)

    # ---- EmergencyTicket ----
    def create_ticket(self, payload, headers):
        return self._request("POST", "/tickets", payload, headers=headers)

    def get_ticket(self, ticket_id, headers):
        return self._request("GET", f"/tickets/{ticket_id}", headers=headers)

    def list_tickets(self, headers, params=None):
        return self._request("GET", "/tickets", headers=headers, params=params)

    def dispatch_ticket(self, ticket_id, headers):
        return self._request("POST", f"/tickets/{ticket_id}/dispatch", {}, headers=headers)

    def make_safe_ticket(self, ticket_id, headers):
        return self._request("POST", f"/tickets/{ticket_id}/make-safe", {}, headers=headers)

    def resolve_ticket(self, ticket_id, headers):
        return self._request("POST", f"/tickets/{ticket_id}/resolve", {}, headers=headers)

    def cancel_ticket(self, ticket_id, headers):
        return self._request("POST", f"/tickets/{ticket_id}/cancel", {}, headers=headers)


api_client = ApiClient()
