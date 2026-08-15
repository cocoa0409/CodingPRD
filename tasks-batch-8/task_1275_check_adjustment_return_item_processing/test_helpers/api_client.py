"""API client: one method per endpoint defined in the PRD (§4 endpoint table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Depositor accounts -------------------------------------------------
    def create_account(self, payload, headers):
        return self._request("POST", "/bank/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/bank/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/bank/accounts", headers=headers, params=params)

    def update_account(self, account_id, payload, headers):
        return self._request("PATCH", f"/bank/accounts/{account_id}", payload, headers)

    def create_account_freeze(self, account_id, payload, headers):
        return self._request("POST", f"/bank/accounts/{account_id}/freezes", payload, headers)

    def list_account_freezes(self, account_id, headers, params=None):
        return self._request("GET", f"/bank/accounts/{account_id}/freezes", headers=headers, params=params)

    # --- Clearing banks -----------------------------------------------------
    def create_clearing_bank(self, payload, headers):
        return self._request("POST", "/bank/clearing-banks", payload, headers)

    def get_clearing_bank(self, bank_id, headers):
        return self._request("GET", f"/bank/clearing-banks/{bank_id}", headers=headers)

    def list_clearing_bank_claims(self, bank_id, headers, params=None):
        return self._request("GET", f"/bank/clearing-banks/{bank_id}/claims", headers=headers, params=params)

    # --- Check items --------------------------------------------------------
    def create_check_item(self, payload, headers):
        return self._request("POST", "/bank/check-items", payload, headers)

    def get_check_item(self, item_id, headers):
        return self._request("GET", f"/bank/check-items/{item_id}", headers=headers)

    def list_check_items(self, headers, params=None):
        return self._request("GET", "/bank/check-items", headers=headers, params=params)

    def present_check_item(self, item_id, headers):
        return self._request("POST", f"/bank/check-items/{item_id}/present", None, headers)

    def pay_check_item(self, item_id, headers):
        return self._request("POST", f"/bank/check-items/{item_id}/pay", None, headers)

    def represent_check_item(self, item_id, headers):
        return self._request("POST", f"/bank/check-items/{item_id}/represent", None, headers)

    # --- Return events ------------------------------------------------------
    def create_return_event(self, item_id, headers):
        return self._request("POST", f"/bank/check-items/{item_id}/return-events", None, headers)

    def list_return_events(self, item_id, headers, params=None):
        return self._request("GET", f"/bank/check-items/{item_id}/return-events", headers=headers, params=params)

    def code_return_event(self, event_id, payload, headers):
        return self._request("POST", f"/bank/return-events/{event_id}/code", payload, headers)

    # --- Hold decisions -----------------------------------------------------
    def create_hold_decision(self, item_id, payload, headers):
        return self._request("POST", f"/bank/check-items/{item_id}/hold-decisions", payload, headers)

    def list_hold_decisions(self, item_id, headers, params=None):
        return self._request("GET", f"/bank/check-items/{item_id}/hold-decisions", headers=headers, params=params)

    def decide_hold(self, hold_id, payload, headers):
        return self._request("POST", f"/bank/hold-decisions/{hold_id}/decide", payload, headers)

    # --- Adjustment cases ---------------------------------------------------
    def list_item_adjustment_cases(self, item_id, headers, params=None):
        return self._request("GET", f"/bank/check-items/{item_id}/adjustment-cases", headers=headers, params=params)

    def get_adjustment_case(self, case_id, headers):
        return self._request("GET", f"/bank/adjustment-cases/{case_id}", headers=headers)

    def list_adjustment_cases(self, headers, params=None):
        return self._request("GET", "/bank/adjustment-cases", headers=headers, params=params)

    def assign_adjustment_case(self, case_id, payload, headers):
        return self._request("POST", f"/bank/adjustment-cases/{case_id}/assign", payload, headers)

    def resolve_adjustment_case(self, case_id, payload, headers):
        return self._request("POST", f"/bank/adjustment-cases/{case_id}/resolve", payload, headers)

    def reopen_adjustment_case(self, case_id, payload, headers):
        return self._request("POST", f"/bank/adjustment-cases/{case_id}/reopen", payload, headers)

    def close_adjustment_case(self, case_id, headers):
        return self._request("POST", f"/bank/adjustment-cases/{case_id}/close", None, headers)

    # --- Adjustment claims --------------------------------------------------
    def create_adjustment_claim(self, case_id, payload, headers):
        return self._request("POST", f"/bank/adjustment-cases/{case_id}/claims", payload, headers)

    def list_case_claims(self, case_id, headers, params=None):
        return self._request("GET", f"/bank/adjustment-cases/{case_id}/claims", headers=headers, params=params)

    def submit_adjustment_claim(self, claim_id, headers):
        return self._request("POST", f"/bank/adjustment-claims/{claim_id}/submit", None, headers)

    def acknowledge_adjustment_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/bank/adjustment-claims/{claim_id}/acknowledge", payload, headers)

    def settle_adjustment_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/bank/adjustment-claims/{claim_id}/settle", payload, headers)

    def write_off_adjustment_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/bank/adjustment-claims/{claim_id}/write-off", payload, headers)

    # --- Warranty claims ----------------------------------------------------
    def create_warranty_claim(self, case_id, payload, headers):
        return self._request("POST", f"/bank/adjustment-cases/{case_id}/warranty-claims", payload, headers)

    def list_case_warranty_claims(self, case_id, headers, params=None):
        return self._request("GET", f"/bank/adjustment-cases/{case_id}/warranty-claims", headers=headers, params=params)

    def submit_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/bank/warranty-claims/{claim_id}/submit", None, headers)

    def settle_warranty_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/bank/warranty-claims/{claim_id}/settle", payload, headers)

    def write_off_warranty_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/bank/warranty-claims/{claim_id}/write-off", payload, headers)

    # --- Customer notifications ---------------------------------------------
    def get_notification(self, notification_id, headers):
        return self._request("GET", f"/bank/notifications/{notification_id}", headers=headers)

    def list_notifications(self, headers, params=None):
        return self._request("GET", "/bank/notifications", headers=headers, params=params)

    def deliver_notification(self, notification_id, headers):
        return self._request("POST", f"/bank/notifications/{notification_id}/deliver", None, headers)

    # --- Fee assessments ------------------------------------------------------
    def get_fee(self, fee_id, headers):
        return self._request("GET", f"/bank/fees/{fee_id}", headers=headers)

    def list_fees(self, headers, params=None):
        return self._request("GET", "/bank/fees", headers=headers, params=params)

    def waive_fee(self, fee_id, payload, headers):
        return self._request("POST", f"/bank/fees/{fee_id}/waive", payload, headers)

    # --- Recredit requests ----------------------------------------------------
    def create_recredit_request(self, payload, headers):
        return self._request("POST", "/bank/recredit-requests", payload, headers)

    def get_recredit_request(self, request_id, headers):
        return self._request("GET", f"/bank/recredit-requests/{request_id}", headers=headers)

    def list_recredit_requests(self, headers, params=None):
        return self._request("GET", "/bank/recredit-requests", headers=headers, params=params)

    def grant_provisional_credit(self, request_id, headers):
        return self._request("POST", f"/bank/recredit-requests/{request_id}/provisional-credit", None, headers)

    def finalize_recredit_request(self, request_id, payload, headers):
        return self._request("POST", f"/bank/recredit-requests/{request_id}/finalize", payload, headers)

    # --- Ledger ---------------------------------------------------------------
    def get_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/bank/ledger-entries/{entry_id}", headers=headers)

    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/bank/ledger-entries", headers=headers, params=params)

    # --- Ops sweep and logical clock ------------------------------------------
    def run_daily_ops(self, headers):
        return self._request("POST", "/bank/ops/run-daily", None, headers)

    def set_logical_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
