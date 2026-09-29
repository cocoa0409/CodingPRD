"""API client: one method per endpoint defined in the PRD.

Every endpoint is mounted under the /cash-ops prefix, with the sole exception of
the logical-clock endpoint.
"""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/cash-ops"


class ApiClient(GenericApiClient):
    """Store Cash Office & Deposit Reconciliation API client."""

    # ---------------------------------------------------------------- clock
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def set_clock_raw(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --------------------------------------------------------------- stores
    def create_store(self, payload, headers):
        return self._request("POST", f"{PREFIX}/stores", payload, headers)

    def get_store(self, store_id, headers):
        return self._request("GET", f"{PREFIX}/stores/{store_id}", headers=headers)

    # ------------------------------------------------------------- cashiers
    def create_cashier(self, payload, headers):
        return self._request("POST", f"{PREFIX}/cashiers", payload, headers)

    def acknowledge_coaching(self, cashier_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/cashiers/{cashier_id}/acknowledge-coaching",
            payload,
            headers,
        )

    def get_cashier(self, cashier_id, headers):
        return self._request("GET", f"{PREFIX}/cashiers/{cashier_id}", headers=headers)

    def list_cashiers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/cashiers", headers=headers, params=params)

    # ---------------------------------------------------------------- safes
    def create_safe(self, payload, headers):
        return self._request("POST", f"{PREFIX}/safes", payload, headers)

    def create_open_request(self, safe_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/safes/{safe_id}/open-requests", payload, headers
        )

    def open_safe(self, safe_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/safes/{safe_id}/open", payload or {}, headers
        )

    def create_smart_deposit(self, safe_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/safes/{safe_id}/smart-deposits", payload, headers
        )

    def restore_posture(self, safe_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/safes/{safe_id}/restore-posture", payload, headers
        )

    def get_safe(self, safe_id, headers):
        return self._request("GET", f"{PREFIX}/safes/{safe_id}", headers=headers)

    def list_safes(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/safes", headers=headers, params=params)

    # ---------------------------------------------------- safe transactions
    def get_safe_transaction(self, txn_id, headers):
        return self._request(
            "GET", f"{PREFIX}/safe-transactions/{txn_id}", headers=headers
        )

    def list_safe_transactions(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/safe-transactions", headers=headers, params=params
        )

    # -------------------------------------------------------- sales journals
    def create_sales_journal(self, payload, headers):
        return self._request("POST", f"{PREFIX}/sales-journals", payload, headers)

    def post_tenders(self, journal_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/sales-journals/{journal_id}/post-tenders", payload, headers
        )

    def get_sales_journal(self, journal_id, headers):
        return self._request(
            "GET", f"{PREFIX}/sales-journals/{journal_id}", headers=headers
        )

    def list_sales_journals(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/sales-journals", headers=headers, params=params
        )

    # ------------------------------------------------------ card settlements
    def create_card_settlement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/card-settlements", payload, headers)

    def get_card_settlement(self, settlement_id, headers):
        return self._request(
            "GET", f"{PREFIX}/card-settlements/{settlement_id}", headers=headers
        )

    def list_card_settlements(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/card-settlements", headers=headers, params=params
        )

    # ---------------------------------------------------------- till sessions
    def create_till_session(self, payload, headers):
        return self._request("POST", f"{PREFIX}/till-sessions", payload, headers)

    def create_drop(self, session_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/till-sessions/{session_id}/drops", payload, headers
        )

    def close_till_session(self, session_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/till-sessions/{session_id}/close", payload, headers
        )

    def blind_count(self, session_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/till-sessions/{session_id}/blind-count", payload, headers
        )

    def recount(self, session_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/till-sessions/{session_id}/recount", payload, headers
        )

    def reconcile_till_session(self, session_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/till-sessions/{session_id}/reconcile",
            payload or {},
            headers,
        )

    def get_till_session(self, session_id, headers):
        return self._request(
            "GET", f"{PREFIX}/till-sessions/{session_id}", headers=headers
        )

    def list_till_sessions(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/till-sessions", headers=headers, params=params
        )

    # -------------------------------------------------------------- deposits
    def create_deposit(self, payload, headers):
        return self._request("POST", f"{PREFIX}/deposits", payload, headers)

    def seal_deposit(self, deposit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/deposits/{deposit_id}/seal", payload, headers
        )

    def void_deposit(self, deposit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/deposits/{deposit_id}/void", payload, headers
        )

    def schedule_pickup(self, deposit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/deposits/{deposit_id}/schedule-pickup", payload, headers
        )

    def pickup_deposit(self, deposit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/deposits/{deposit_id}/pickup", payload, headers
        )

    def reconcile_bank(self, deposit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/deposits/{deposit_id}/reconcile-bank", payload, headers
        )

    def get_deposit(self, deposit_id, headers):
        return self._request("GET", f"{PREFIX}/deposits/{deposit_id}", headers=headers)

    def list_deposits(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/deposits", headers=headers, params=params)

    # --------------------------------------------------- bank credit records
    def create_bank_credit_record(self, payload, headers):
        return self._request("POST", f"{PREFIX}/bank-credit-records", payload, headers)

    def get_bank_credit_record(self, record_id, headers):
        return self._request(
            "GET", f"{PREFIX}/bank-credit-records/{record_id}", headers=headers
        )

    def list_bank_credit_records(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/bank-credit-records", headers=headers, params=params
        )

    # -------------------------------------------------------- variance cases
    def create_attribution(self, case_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/variance-cases/{case_id}/attributions", payload, headers
        )

    def escalate_variance_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/variance-cases/{case_id}/escalate", payload, headers
        )

    def close_variance_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/variance-cases/{case_id}/close", payload, headers
        )

    def get_variance_case(self, case_id, headers):
        return self._request(
            "GET", f"{PREFIX}/variance-cases/{case_id}", headers=headers
        )

    def list_variance_cases(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/variance-cases", headers=headers, params=params
        )

    # --------------------------------------------------------- change orders
    def create_change_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/change-orders", payload, headers)

    def approve_change_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/change-orders/{order_id}/approve", payload, headers
        )

    def reject_change_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/change-orders/{order_id}/reject", payload, headers
        )

    def receive_change_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/change-orders/{order_id}/receive", payload, headers
        )

    def get_change_order(self, order_id, headers):
        return self._request(
            "GET", f"{PREFIX}/change-orders/{order_id}", headers=headers
        )

    def list_change_orders(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/change-orders", headers=headers, params=params
        )


api_client = ApiClient()
