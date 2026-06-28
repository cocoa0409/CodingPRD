"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----- Customers / KYC -----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    def list_customer_compliance_screens(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/compliance-screens",
                             headers=headers, params=params)

    def list_customer_returned_items(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/returned-items",
                             headers=headers, params=params)

    def create_compliance_screen(self, payload, headers):
        return self._request("POST", "/compliance-screens", payload, headers)

    # ----- Fee schedules -----
    def create_fee_schedule(self, payload, headers):
        return self._request("POST", "/fee-schedules", payload, headers)

    def get_fee_schedule(self, schedule_id, headers):
        return self._request("GET", f"/fee-schedules/{schedule_id}", headers=headers)

    def list_fee_schedules(self, headers, params=None):
        return self._request("GET", "/fee-schedules", headers=headers, params=params)

    # ----- Cash drawers -----
    def create_cash_drawer(self, payload, headers):
        return self._request("POST", "/cash-drawers", payload, headers)

    def get_cash_drawer(self, drawer_id, headers):
        return self._request("GET", f"/cash-drawers/{drawer_id}", headers=headers)

    def list_drawer_transactions(self, drawer_id, headers, params=None):
        return self._request("GET", f"/cash-drawers/{drawer_id}/transactions",
                             headers=headers, params=params)

    def begin_reconcile_drawer(self, drawer_id, headers):
        return self._request("POST", f"/cash-drawers/{drawer_id}/begin-reconcile",
                             {}, headers)

    def close_drawer(self, drawer_id, payload, headers):
        return self._request("POST", f"/cash-drawers/{drawer_id}/close", payload, headers)

    # ----- Transactions -----
    def create_transaction(self, payload, headers):
        return self._request("POST", "/transactions", payload, headers)

    def get_transaction(self, transaction_id, headers):
        return self._request("GET", f"/transactions/{transaction_id}", headers=headers)

    def list_transactions(self, headers, params=None):
        return self._request("GET", "/transactions", headers=headers, params=params)

    def void_transaction(self, transaction_id, headers):
        return self._request("POST", f"/transactions/{transaction_id}/void", {}, headers)

    def return_transaction(self, transaction_id, payload, headers):
        return self._request("POST", f"/transactions/{transaction_id}/return", payload, headers)

    # ----- Check items -----
    def get_check_item(self, check_item_id, headers):
        return self._request("GET", f"/check-items/{check_item_id}", headers=headers)

    def list_transaction_check_items(self, transaction_id, headers, params=None):
        return self._request("GET", f"/transactions/{transaction_id}/check-items",
                             headers=headers, params=params)

    def release_check_item(self, check_item_id, headers):
        return self._request("POST", f"/check-items/{check_item_id}/release", {}, headers)

    def reject_check_item(self, check_item_id, headers):
        return self._request("POST", f"/check-items/{check_item_id}/reject", {}, headers)

    # ----- Product children (reverse reachability) -----
    def list_transaction_money_order(self, transaction_id, headers, params=None):
        return self._request("GET", f"/transactions/{transaction_id}/money-order",
                             headers=headers, params=params)

    def list_transaction_wire_transfer(self, transaction_id, headers, params=None):
        return self._request("GET", f"/transactions/{transaction_id}/wire-transfer",
                             headers=headers, params=params)

    def list_transaction_bill_payment(self, transaction_id, headers, params=None):
        return self._request("GET", f"/transactions/{transaction_id}/bill-payment",
                             headers=headers, params=params)

    def list_transaction_prepaid_card_load(self, transaction_id, headers, params=None):
        return self._request("GET", f"/transactions/{transaction_id}/prepaid-card-load",
                             headers=headers, params=params)

    # ----- Returned-item recovery -----
    def get_returned_item(self, returned_item_id, headers):
        return self._request("GET", f"/returned-items/{returned_item_id}", headers=headers)

    def list_returned_items(self, headers, params=None):
        return self._request("GET", "/returned-items", headers=headers, params=params)

    def recover_returned_item(self, returned_item_id, payload, headers):
        return self._request("POST", f"/returned-items/{returned_item_id}/recover",
                             payload, headers)

    def write_off_returned_item(self, returned_item_id, headers):
        return self._request("POST", f"/returned-items/{returned_item_id}/write-off",
                             {}, headers)

    # ----- Test-driving clock -----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
