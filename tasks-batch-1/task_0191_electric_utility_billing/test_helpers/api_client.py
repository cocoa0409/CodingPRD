"""API client: one method per endpoint defined in the Electric Utility
Billing PRD (§4). The base _request() method is inherited from the
framework's GenericApiClient. GET methods take `params` for filtering and
pagination; action POSTs take an optional body payload.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Tariffs ----
    def create_tariff(self, payload, headers):
        return self._request("POST", "/tariffs", payload, headers)

    def activate_tariff(self, tariff_id, headers):
        return self._request("POST", f"/tariffs/{tariff_id}/activate", {}, headers)

    def retire_tariff(self, tariff_id, headers):
        return self._request("POST", f"/tariffs/{tariff_id}/retire", {}, headers)

    def get_tariff(self, tariff_id, headers):
        return self._request("GET", f"/tariffs/{tariff_id}", headers=headers)

    def list_tariffs(self, headers, params=None):
        return self._request("GET", "/tariffs", headers=headers, params=params)

    # ---- Accounts ----
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/accounts", headers=headers, params=params)

    def disconnect_notice(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/disconnect-notice", {}, headers)

    def reconnect_request(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/reconnect-request", {}, headers)

    # ---- Meters ----
    def create_meter(self, payload, headers):
        return self._request("POST", "/meters", payload, headers)

    def get_meter(self, meter_id, headers):
        return self._request("GET", f"/meters/{meter_id}", headers=headers)

    def list_meters(self, headers, params=None):
        return self._request("GET", "/meters", headers=headers, params=params)

    # ---- Meter reads (AMI import) ----
    def create_meter_read(self, payload, headers):
        return self._request("POST", "/meter-reads", payload, headers)

    def get_meter_read(self, read_id, headers):
        return self._request("GET", f"/meter-reads/{read_id}", headers=headers)

    def list_meter_reads(self, headers, params=None):
        return self._request("GET", "/meter-reads", headers=headers, params=params)

    # ---- Bills ----
    def create_bill(self, payload, headers):
        return self._request("POST", "/bills", payload, headers)

    def issue_bill(self, bill_id, payload, headers):
        return self._request("POST", f"/bills/{bill_id}/issue", payload, headers)

    def void_bill(self, bill_id, headers):
        return self._request("POST", f"/bills/{bill_id}/void", {}, headers)

    def get_bill(self, bill_id, headers):
        return self._request("GET", f"/bills/{bill_id}", headers=headers)

    def list_bills(self, headers, params=None):
        return self._request("GET", "/bills", headers=headers, params=params)

    # ---- Payments ----
    def create_payment(self, payload, headers):
        return self._request("POST", "/payments", payload, headers)

    def reverse_payment(self, payment_id, headers):
        return self._request("POST", f"/payments/{payment_id}/reverse", {}, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    # ---- Service orders ----
    def get_service_order(self, order_id, headers):
        return self._request("GET", f"/service-orders/{order_id}", headers=headers)

    def list_service_orders(self, headers, params=None):
        return self._request("GET", "/service-orders", headers=headers, params=params)

    def complete_service_order(self, order_id, headers):
        return self._request("POST", f"/service-orders/{order_id}/complete", {}, headers)

    def cancel_service_order(self, order_id, headers):
        return self._request("POST", f"/service-orders/{order_id}/cancel", {}, headers)

    # ---- Budget billing plans ----
    def create_budget_plan(self, payload, headers):
        return self._request("POST", "/budget-plans", payload, headers)

    def true_up_budget_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/budget-plans/{plan_id}/true-up", payload, headers)

    def cancel_budget_plan(self, plan_id, headers):
        return self._request("POST", f"/budget-plans/{plan_id}/cancel", {}, headers)

    def get_budget_plan(self, plan_id, headers):
        return self._request("GET", f"/budget-plans/{plan_id}", headers=headers)

    def list_budget_plans(self, headers, params=None):
        return self._request("GET", "/budget-plans", headers=headers, params=params)

    # ---- Assistance grants ----
    def create_assistance_grant(self, payload, headers):
        return self._request("POST", "/assistance-grants", payload, headers)

    def cancel_assistance_grant(self, grant_id, headers):
        return self._request("POST", f"/assistance-grants/{grant_id}/cancel", {}, headers)

    def get_assistance_grant(self, grant_id, headers):
        return self._request("GET", f"/assistance-grants/{grant_id}", headers=headers)

    def list_assistance_grants(self, headers, params=None):
        return self._request("GET", "/assistance-grants", headers=headers, params=params)

    # ---- System clock (test-driving) ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def get_clock(self, headers):
        return self._request("GET", "/_clock", headers=headers)


api_client = ApiClient()
