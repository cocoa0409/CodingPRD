"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ---- Creditor ----
    def create_creditor(self, payload, headers):
        return self._request("POST", "/creditors", payload, headers)

    def get_creditor(self, creditor_id, headers):
        return self._request("GET", f"/creditors/{creditor_id}", headers=headers)

    # ---- Consumer ----
    def create_consumer(self, payload, headers):
        return self._request("POST", "/consumers", payload, headers)

    def get_consumer(self, consumer_id, headers):
        return self._request("GET", f"/consumers/{consumer_id}", headers=headers)

    # ---- SkipTrace ----
    def create_skip_trace(self, payload, headers):
        return self._request("POST", "/skip-traces", payload, headers)

    def get_skip_trace(self, skip_trace_id, headers):
        return self._request("GET", f"/skip-traces/{skip_trace_id}", headers=headers)

    def list_skip_traces(self, headers, params=None):
        return self._request("GET", "/skip-traces", headers=headers, params=params)

    # ---- Account ----
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/accounts", headers=headers, params=params)

    def send_validation_notice(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/send-validation-notice",
                             {}, headers)

    def begin_work(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/begin-work", {}, headers)

    def cease_communication(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/cease-communication",
                             {}, headers)

    def recall_account(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/recall", payload, headers)

    def close_uncollectible(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/close-uncollectible",
                             {}, headers)

    # ---- CommunicationAttempt ----
    def create_communication_attempt(self, payload, headers):
        return self._request("POST", "/communication-attempts", payload, headers)

    def get_communication_attempt(self, attempt_id, headers):
        return self._request("GET", f"/communication-attempts/{attempt_id}", headers=headers)

    def list_communication_attempts(self, headers, params=None):
        return self._request("GET", "/communication-attempts", headers=headers, params=params)

    # ---- Dispute ----
    def create_dispute(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/disputes", payload, headers)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/disputes/{dispute_id}", headers=headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/disputes", headers=headers, params=params)

    def investigate_dispute(self, dispute_id, headers):
        return self._request("POST", f"/disputes/{dispute_id}/investigate", {}, headers)

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/disputes/{dispute_id}/resolve", payload, headers)

    def reopen_dispute(self, dispute_id, headers):
        return self._request("POST", f"/disputes/{dispute_id}/reopen", {}, headers)

    # ---- PaymentArrangement ----
    def create_arrangement(self, payload, headers):
        return self._request("POST", "/arrangements", payload, headers)

    def get_arrangement(self, arrangement_id, headers):
        return self._request("GET", f"/arrangements/{arrangement_id}", headers=headers)

    def list_arrangements(self, headers, params=None):
        return self._request("GET", "/arrangements", headers=headers, params=params)

    def payoff_quote(self, arrangement_id, headers, params=None):
        return self._request("GET", f"/arrangements/{arrangement_id}/payoff-quote",
                             headers=headers, params=params)

    def accept_arrangement(self, arrangement_id, headers):
        return self._request("POST", f"/arrangements/{arrangement_id}/accept", {}, headers)

    def counter_arrangement(self, arrangement_id, headers):
        return self._request("POST", f"/arrangements/{arrangement_id}/counter", {}, headers)

    def reject_arrangement(self, arrangement_id, headers):
        return self._request("POST", f"/arrangements/{arrangement_id}/reject", {}, headers)

    # ---- Payment ----
    def create_payment(self, payload, headers):
        return self._request("POST", "/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    def reverse_payment(self, payment_id, payload, headers):
        return self._request("POST", f"/payments/{payment_id}/reverse", payload, headers)

    # ---- BureauFurnishing ----
    def create_bureau_furnishing(self, payload, headers):
        return self._request("POST", "/bureau-furnishings", payload, headers)

    def get_bureau_furnishing(self, furnishing_id, headers):
        return self._request("GET", f"/bureau-furnishings/{furnishing_id}", headers=headers)

    def list_bureau_furnishings(self, headers, params=None):
        return self._request("GET", "/bureau-furnishings", headers=headers, params=params)

    # ---- BureauDispute ----
    def create_bureau_dispute(self, payload, headers):
        return self._request("POST", "/bureau-disputes", payload, headers)

    def get_bureau_dispute(self, bureau_dispute_id, headers):
        return self._request("GET", f"/bureau-disputes/{bureau_dispute_id}", headers=headers)

    def list_bureau_disputes(self, headers, params=None):
        return self._request("GET", "/bureau-disputes", headers=headers, params=params)

    def resolve_bureau_dispute(self, bureau_dispute_id, payload, headers):
        return self._request("POST", f"/bureau-disputes/{bureau_dispute_id}/resolve",
                             payload, headers)

    def reopen_bureau_dispute(self, bureau_dispute_id, headers):
        return self._request("POST", f"/bureau-disputes/{bureau_dispute_id}/reopen",
                             {}, headers)


api_client = ApiClient()
