"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Member ----
    def create_member(self, payload, headers=None):
        return self._request("POST", "/members", payload, headers=headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def suspend_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/suspend", {}, headers=headers)

    def reinstate_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/reinstate", {}, headers=headers)

    def patch_member(self, member_id, payload, headers):
        return self._request("PATCH", f"/members/{member_id}", payload, headers=headers)

    def get_savings_report(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}/savings-report", headers=headers)

    # ---- SavingsAccount ----
    def create_savings_account(self, payload, headers):
        return self._request("POST", "/savings-accounts", payload, headers=headers)

    def get_savings_account(self, account_id, headers):
        return self._request("GET", f"/savings-accounts/{account_id}", headers=headers)

    def list_savings_accounts(self, headers, params=None):
        return self._request("GET", "/savings-accounts", headers=headers, params=params)

    def close_savings_account(self, account_id, headers):
        return self._request("POST", f"/savings-accounts/{account_id}/close", {}, headers=headers)

    # ---- LinkedAccount ----
    def create_linked_account(self, payload, headers):
        return self._request("POST", "/linked-accounts", payload, headers=headers)

    def get_linked_account(self, account_id, headers):
        return self._request("GET", f"/linked-accounts/{account_id}", headers=headers)

    def list_linked_accounts(self, headers, params=None):
        return self._request("GET", "/linked-accounts", headers=headers, params=params)

    def unlink_account(self, account_id, headers):
        return self._request("POST", f"/linked-accounts/{account_id}/unlink", {}, headers=headers)

    # ---- RecurringCharge ----
    def create_recurring_charge(self, payload, headers):
        return self._request("POST", "/recurring-charges", payload, headers=headers)

    def get_recurring_charge(self, charge_id, headers):
        return self._request("GET", f"/recurring-charges/{charge_id}", headers=headers)

    def list_recurring_charges(self, headers, params=None):
        return self._request("GET", "/recurring-charges", headers=headers, params=params)

    def confirm_recurring_charge(self, charge_id, headers):
        return self._request("POST", f"/recurring-charges/{charge_id}/confirm", {}, headers=headers)

    def dismiss_recurring_charge(self, charge_id, headers):
        return self._request("POST", f"/recurring-charges/{charge_id}/dismiss", {}, headers=headers)

    # ---- Subscription ----
    def create_subscription(self, payload, headers):
        return self._request("POST", "/subscriptions", payload, headers=headers)

    def get_subscription(self, sub_id, headers):
        return self._request("GET", f"/subscriptions/{sub_id}", headers=headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/subscriptions", headers=headers, params=params)

    def request_cancel_subscription(self, sub_id, payload, headers):
        return self._request("POST", f"/subscriptions/{sub_id}/request-cancel", payload, headers=headers)

    def confirm_cancel_subscription(self, sub_id, headers):
        return self._request("POST", f"/subscriptions/{sub_id}/confirm-cancel", {}, headers=headers)

    def fail_cancel_subscription(self, sub_id, headers):
        return self._request("POST", f"/subscriptions/{sub_id}/fail-cancel", {}, headers=headers)

    # ---- ConciergeAgentProfile ----
    def create_concierge_agent(self, payload, headers):
        return self._request("POST", "/concierge-agents", payload, headers=headers)

    def get_concierge_agent(self, agent_id, headers):
        return self._request("GET", f"/concierge-agents/{agent_id}", headers=headers)

    def list_concierge_agents(self, headers, params=None):
        return self._request("GET", "/concierge-agents", headers=headers, params=params)

    # ---- NegotiationCase ----
    def create_negotiation_case(self, payload, headers):
        return self._request("POST", "/negotiation-cases", payload, headers=headers)

    def get_negotiation_case(self, case_id, headers):
        return self._request("GET", f"/negotiation-cases/{case_id}", headers=headers)

    def list_negotiation_cases(self, headers, params=None):
        return self._request("GET", "/negotiation-cases", headers=headers, params=params)

    def propose_negotiation(self, case_id, payload, headers):
        return self._request("POST", f"/negotiation-cases/{case_id}/propose", payload, headers=headers)

    def counter_negotiation(self, case_id, payload, headers):
        return self._request("POST", f"/negotiation-cases/{case_id}/counter", payload, headers=headers)

    def accept_negotiation(self, case_id, headers):
        return self._request("POST", f"/negotiation-cases/{case_id}/accept", {}, headers=headers)

    def abandon_negotiation(self, case_id, headers):
        return self._request("POST", f"/negotiation-cases/{case_id}/abandon", {}, headers=headers)

    def cancel_negotiation(self, case_id, headers):
        return self._request("POST", f"/negotiation-cases/{case_id}/cancel", {}, headers=headers)

    # ---- RefundClaim ----
    def create_refund_claim(self, payload, headers):
        return self._request("POST", "/refund-claims", payload, headers=headers)

    def get_refund_claim(self, claim_id, headers):
        return self._request("GET", f"/refund-claims/{claim_id}", headers=headers)

    def list_refund_claims(self, headers, params=None):
        return self._request("GET", "/refund-claims", headers=headers, params=params)

    def start_review_refund_claim(self, claim_id, headers):
        return self._request("POST", f"/refund-claims/{claim_id}/start-review", {}, headers=headers)

    def approve_refund_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/refund-claims/{claim_id}/approve", payload, headers=headers)

    def deny_refund_claim(self, claim_id, headers):
        return self._request("POST", f"/refund-claims/{claim_id}/deny", {}, headers=headers)

    def dispute_refund_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/refund-claims/{claim_id}/dispute", payload, headers=headers)

    # ---- SavingsLedgerEntry ----
    def get_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/savings-ledger-entries/{entry_id}", headers=headers)

    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/savings-ledger-entries", headers=headers, params=params)

    def transfer_ledger_entry(self, entry_id, headers):
        return self._request("POST", f"/savings-ledger-entries/{entry_id}/transfer", {}, headers=headers)

    def reverse_ledger_entry(self, entry_id, headers):
        return self._request("POST", f"/savings-ledger-entries/{entry_id}/reverse", {}, headers=headers)

    # ---- Clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers=headers)


api_client = ApiClient()
