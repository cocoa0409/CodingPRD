"""API client: one method per endpoint defined in the PRD (Section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Sellers / onboarding (PRD §3.1, §3.2) ----
    def create_seller(self, payload, headers):
        return self._request("POST", "/sellers", payload, headers)

    def get_seller(self, seller_id, headers):
        return self._request("GET", f"/sellers/{seller_id}", headers=headers)

    def list_sellers(self, headers, params=None):
        return self._request("GET", "/sellers", headers=headers, params=params)

    def submit_kyc(self, seller_id, headers):
        return self._request("POST", f"/sellers/{seller_id}/kyc/submit", {}, headers)

    def decide_kyc(self, seller_id, payload, headers):
        return self._request("POST", f"/sellers/{seller_id}/kyc/decision", payload, headers)

    def submit_w9(self, seller_id, headers):
        return self._request("POST", f"/sellers/{seller_id}/w9/submit", {}, headers)

    def approve_w9(self, seller_id, headers):
        return self._request("POST", f"/sellers/{seller_id}/w9/approve", {}, headers)

    def suspend_seller(self, seller_id, headers):
        return self._request("POST", f"/sellers/{seller_id}/suspend", {}, headers)

    def reinstate_seller(self, seller_id, headers):
        return self._request("POST", f"/sellers/{seller_id}/reinstate", {}, headers)

    def close_seller(self, seller_id, headers):
        return self._request("POST", f"/sellers/{seller_id}/close", {}, headers)

    # ---- Ledger entries (PRD §2.6) ----
    def list_seller_ledger_entries(self, seller_id, headers, params=None):
        return self._request("GET", f"/sellers/{seller_id}/ledger-entries", headers=headers, params=params)

    def list_seller_reserves(self, seller_id, headers, params=None):
        return self._request("GET", f"/sellers/{seller_id}/reserves", headers=headers, params=params)

    def get_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/ledger-entries/{entry_id}", headers=headers)

    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/ledger-entries", headers=headers, params=params)

    # ---- Payout methods (PRD §3.3) ----
    def create_payout_method(self, payload, headers):
        return self._request("POST", "/payout-methods", payload, headers)

    def get_payout_method(self, method_id, headers):
        return self._request("GET", f"/payout-methods/{method_id}", headers=headers)

    def list_payout_methods(self, headers, params=None):
        return self._request("GET", "/payout-methods", headers=headers, params=params)

    def verify_payout_method(self, method_id, payload, headers):
        return self._request("POST", f"/payout-methods/{method_id}/verify", payload, headers)

    # ---- Fee schedules (PRD §3.4) ----
    def create_fee_schedule(self, payload, headers):
        return self._request("POST", "/fee-schedules", payload, headers)

    def get_fee_schedule(self, schedule_id, headers):
        return self._request("GET", f"/fee-schedules/{schedule_id}", headers=headers)

    def list_fee_schedules(self, headers, params=None):
        return self._request("GET", "/fee-schedules", headers=headers, params=params)

    # ---- Orders (PRD §3.4) ----
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    # ---- Refunds (PRD §3.6) ----
    def create_refund(self, payload, headers):
        return self._request("POST", "/refunds", payload, headers)

    def get_refund(self, refund_id, headers):
        return self._request("GET", f"/refunds/{refund_id}", headers=headers)

    def list_refunds(self, headers, params=None):
        return self._request("GET", "/refunds", headers=headers, params=params)

    def apply_refund(self, refund_id, headers):
        return self._request("POST", f"/refunds/{refund_id}/apply", {}, headers)

    def void_refund(self, refund_id, headers):
        return self._request("POST", f"/refunds/{refund_id}/void", {}, headers)

    # ---- Chargebacks (PRD §3.7) ----
    def create_chargeback(self, payload, headers):
        return self._request("POST", "/chargebacks", payload, headers)

    def get_chargeback(self, chargeback_id, headers):
        return self._request("GET", f"/chargebacks/{chargeback_id}", headers=headers)

    def list_chargebacks(self, headers, params=None):
        return self._request("GET", "/chargebacks", headers=headers, params=params)

    def represent_chargeback(self, chargeback_id, headers):
        return self._request("POST", f"/chargebacks/{chargeback_id}/represent", {}, headers)

    def decide_chargeback(self, chargeback_id, payload, headers):
        return self._request("POST", f"/chargebacks/{chargeback_id}/decision", payload, headers)

    # ---- Disputes (PRD §3.8) ----
    def create_dispute(self, payload, headers):
        return self._request("POST", "/disputes", payload, headers)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/disputes/{dispute_id}", headers=headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/disputes", headers=headers, params=params)

    def open_review_dispute(self, dispute_id, headers):
        return self._request("POST", f"/disputes/{dispute_id}/open-review", {}, headers)

    def respond_dispute(self, dispute_id, headers):
        return self._request("POST", f"/disputes/{dispute_id}/respond", {}, headers)

    def decide_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/disputes/{dispute_id}/decision", payload, headers)

    # ---- Payouts (PRD §3.9) ----
    def create_payout(self, payload, headers):
        return self._request("POST", "/payouts", payload, headers)

    def get_payout(self, payout_id, headers):
        return self._request("GET", f"/payouts/{payout_id}", headers=headers)

    def list_payouts(self, headers, params=None):
        return self._request("GET", "/payouts", headers=headers, params=params)

    def release_payout(self, payout_id, payload, headers):
        return self._request("POST", f"/payouts/{payout_id}/release", payload, headers)

    def mark_failed_payout(self, payout_id, headers):
        return self._request("POST", f"/payouts/{payout_id}/mark-failed", {}, headers)

    def reverse_payout(self, payout_id, headers):
        return self._request("POST", f"/payouts/{payout_id}/reverse", {}, headers)

    # ---- Tax forms (1099-K) (PRD §3.11) ----
    def create_tax_form(self, payload, headers):
        return self._request("POST", "/tax-forms", payload, headers)

    def get_tax_form(self, form_id, headers):
        return self._request("GET", f"/tax-forms/{form_id}", headers=headers)

    def list_tax_forms(self, headers, params=None):
        return self._request("GET", "/tax-forms", headers=headers, params=params)

    def issue_tax_form(self, form_id, payload, headers):
        return self._request("POST", f"/tax-forms/{form_id}/issue", payload, headers)

    def correct_tax_form(self, form_id, headers):
        return self._request("POST", f"/tax-forms/{form_id}/correct", {}, headers)

    # ---- Balance statements (PRD §3.12) ----
    def create_balance_statement(self, payload, headers):
        return self._request("POST", "/balance-statements", payload, headers)

    def get_balance_statement(self, statement_id, headers):
        return self._request("GET", f"/balance-statements/{statement_id}", headers=headers)

    def list_balance_statements(self, headers, params=None):
        return self._request("GET", "/balance-statements", headers=headers, params=params)

    # ---- Logical clock (PRD §3.12) ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def advance_clock(self, payload, headers):
        return self._request("POST", "/_clock/advance", payload, headers)


api_client = ApiClient()
