"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- State schedules ----
    def create_state_schedule(self, payload, headers):
        return self._request("POST", "/pawn/state-schedules", payload, headers)

    def list_state_schedules(self, headers, params=None):
        return self._request("GET", "/pawn/state-schedules", headers=headers, params=params)

    # ---- Shops ----
    def create_shop(self, payload, headers):
        return self._request("POST", "/pawn/shops", payload, headers)

    def get_shop(self, shop_id, headers):
        return self._request("GET", f"/pawn/shops/{shop_id}", headers=headers)

    def get_shop_drawer(self, shop_id, headers):
        return self._request("GET", f"/pawn/shops/{shop_id}/drawer", headers=headers)

    def list_shop_loans(self, shop_id, headers, params=None):
        return self._request("GET", f"/pawn/shops/{shop_id}/loans", headers=headers, params=params)

    def list_shop_inventory(self, shop_id, headers, params=None):
        return self._request("GET", f"/pawn/shops/{shop_id}/inventory", headers=headers, params=params)

    # ---- Storage bins ----
    def create_storage_bin(self, payload, headers):
        return self._request("POST", "/pawn/storage-bins", payload, headers)

    def get_storage_bin(self, bin_id, headers):
        return self._request("GET", f"/pawn/storage-bins/{bin_id}", headers=headers)

    def list_storage_bins(self, headers, params=None):
        return self._request("GET", "/pawn/storage-bins", headers=headers, params=params)

    def list_storage_bin_loans(self, bin_id, headers, params=None):
        return self._request("GET", f"/pawn/storage-bins/{bin_id}/loans", headers=headers, params=params)

    # ---- Customers ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/pawn/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/pawn/customers/{customer_id}", headers=headers)

    # ---- Pawn items ----
    def create_item(self, payload, headers):
        return self._request("POST", "/pawn/items", payload, headers)

    def get_item(self, item_id, headers):
        return self._request("GET", f"/pawn/items/{item_id}", headers=headers)

    def list_items(self, headers, params=None):
        return self._request("GET", "/pawn/items", headers=headers, params=params)

    def appraise_item(self, item_id, payload, headers):
        return self._request("POST", f"/pawn/items/{item_id}/appraise", payload, headers)

    def report_police_item(self, item_id, headers):
        return self._request("POST", f"/pawn/items/{item_id}/report-police", {}, headers)

    # ---- Loans ----
    def create_loan(self, payload, headers):
        return self._request("POST", "/pawn/loans", payload, headers)

    def list_loans(self, headers, params=None):
        return self._request("GET", "/pawn/loans", headers=headers, params=params)

    def get_loan(self, loan_id, headers):
        return self._request("GET", f"/pawn/loans/{loan_id}", headers=headers)

    def get_loan_payoff(self, loan_id, headers):
        return self._request("GET", f"/pawn/loans/{loan_id}/payoff", headers=headers)

    def list_loan_transactions(self, loan_id, headers, params=None):
        return self._request("GET", f"/pawn/loans/{loan_id}/transactions", headers=headers, params=params)

    def extend_loan(self, loan_id, payload, headers):
        return self._request("POST", f"/pawn/loans/{loan_id}/extend", payload, headers)

    def renew_loan(self, loan_id, payload, headers):
        return self._request("POST", f"/pawn/loans/{loan_id}/renew", payload, headers)

    def redeem_loan(self, loan_id, headers):
        return self._request("POST", f"/pawn/loans/{loan_id}/redeem", {}, headers)

    def forfeit_loan(self, loan_id, headers):
        return self._request("POST", f"/pawn/loans/{loan_id}/forfeit", {}, headers)

    def void_loan(self, loan_id, headers):
        return self._request("POST", f"/pawn/loans/{loan_id}/void", {}, headers)

    # ---- Inventory ----
    def get_inventory_item(self, inventory_id, headers):
        return self._request("GET", f"/pawn/inventory/{inventory_id}", headers=headers)

    def list_inventory(self, headers, params=None):
        return self._request("GET", "/pawn/inventory", headers=headers, params=params)

    def sell_inventory(self, inventory_id, payload, headers):
        return self._request("POST", f"/pawn/inventory/{inventory_id}/sell", payload, headers)

    def recall_inventory(self, inventory_id, headers):
        return self._request("POST", f"/pawn/inventory/{inventory_id}/recall", {}, headers)

    # ---- Layaway ----
    def create_layaway_plan(self, payload, headers):
        return self._request("POST", "/pawn/layaway-plans", payload, headers)

    def get_layaway_plan(self, plan_id, headers):
        return self._request("GET", f"/pawn/layaway-plans/{plan_id}", headers=headers)

    def list_layaway_plans(self, headers, params=None):
        return self._request("GET", "/pawn/layaway-plans", headers=headers, params=params)

    def list_layaway_installments(self, plan_id, headers, params=None):
        return self._request("GET", f"/pawn/layaway-plans/{plan_id}/installments", headers=headers, params=params)

    def post_layaway_installment(self, plan_id, payload, headers):
        return self._request("POST", f"/pawn/layaway-plans/{plan_id}/installments", payload, headers)

    def cancel_layaway_plan(self, plan_id, headers):
        return self._request("POST", f"/pawn/layaway-plans/{plan_id}/cancel", {}, headers)

    # ---- Police holds ----
    def create_police_hold(self, payload, headers):
        return self._request("POST", "/pawn/police-holds", payload, headers)

    def get_police_hold(self, hold_id, headers):
        return self._request("GET", f"/pawn/police-holds/{hold_id}", headers=headers)

    def list_police_holds(self, headers, params=None):
        return self._request("GET", "/pawn/police-holds", headers=headers, params=params)

    def release_police_hold(self, hold_id, headers):
        return self._request("POST", f"/pawn/police-holds/{hold_id}/release", {}, headers)

    def execute_police_hold(self, hold_id, headers):
        return self._request("POST", f"/pawn/police-holds/{hold_id}/execute", {}, headers)

    # ---- Clock (test-driving) ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/pawn/_clock/set_current_utc", payload, headers)

    def get_clock(self, headers):
        return self._request("GET", "/pawn/_clock", headers=headers)


api_client = ApiClient()
