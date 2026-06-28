"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Config / clock (PlatformAdmin) ───────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/dmv/_clock/set_current_utc", payload, headers)

    def advance_fee_period(self, headers, payload=None):
        return self._request("POST", "/dmv/_fee-periods/advance", payload or {}, headers)

    def inject_account_counters(self, payload, headers):
        return self._request("POST", "/dmv/_inject/account_counters", payload, headers)

    def inject_rejection_round(self, payload, headers):
        return self._request("POST", "/dmv/_inject/rejection_round", payload, headers)

    # ─── Fee schedules ────────────────────────────────────────────────
    def create_fee_schedule(self, payload, headers):
        return self._request("POST", "/dmv/fee-schedules", payload, headers)

    def list_fee_schedules(self, headers, params=None):
        return self._request("GET", "/dmv/fee-schedules", headers=headers, params=params)

    def get_fee_schedule(self, schedule_id, headers):
        return self._request("GET", f"/dmv/fee-schedules/{schedule_id}", headers=headers)

    # ─── Accounts ─────────────────────────────────────────────────────
    def create_account(self, payload, headers):
        return self._request("POST", "/dmv/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/dmv/accounts/{account_id}", headers=headers)

    def reinstate_account(self, account_id, headers, payload=None):
        return self._request("POST", f"/dmv/accounts/{account_id}/reinstate", payload or {}, headers)

    def create_payment(self, account_id, payload, headers):
        return self._request("POST", f"/dmv/accounts/{account_id}/payments", payload, headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/dmv/payments", headers=headers, params=params)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/dmv/payments/{payment_id}", headers=headers)

    # ─── Transactions ─────────────────────────────────────────────────
    def list_transactions(self, headers, params=None):
        return self._request("GET", "/dmv/transactions", headers=headers, params=params)

    def create_transaction(self, payload, headers):
        return self._request("POST", "/dmv/transactions", payload, headers)

    def get_transaction(self, transaction_id, headers):
        return self._request("GET", f"/dmv/transactions/{transaction_id}", headers=headers)

    def quote_transaction(self, transaction_id, payload, headers):
        return self._request("POST", f"/dmv/transactions/{transaction_id}/quote", payload, headers)

    def verify_documents(self, transaction_id, headers, payload=None):
        return self._request("POST", f"/dmv/transactions/{transaction_id}/verify-documents", payload or {}, headers)

    def submit_transaction(self, transaction_id, headers, payload=None):
        return self._request("POST", f"/dmv/transactions/{transaction_id}/submit", payload or {}, headers)

    def complete_transaction(self, transaction_id, headers, payload=None):
        return self._request("POST", f"/dmv/transactions/{transaction_id}/complete", payload or {}, headers)

    def cancel_transaction(self, transaction_id, headers, payload=None):
        return self._request("POST", f"/dmv/transactions/{transaction_id}/cancel", payload or {}, headers)

    def list_transaction_fee_quotes(self, transaction_id, headers, params=None):
        return self._request("GET", f"/dmv/transactions/{transaction_id}/fee-quotes", headers=headers, params=params)

    def list_transaction_documents(self, transaction_id, headers, params=None):
        return self._request("GET", f"/dmv/transactions/{transaction_id}/documents", headers=headers, params=params)

    def list_transaction_submissions(self, transaction_id, headers, params=None):
        return self._request("GET", f"/dmv/transactions/{transaction_id}/submissions", headers=headers, params=params)

    def list_transaction_lien_packets(self, transaction_id, headers, params=None):
        return self._request("GET", f"/dmv/transactions/{transaction_id}/lien-packets", headers=headers, params=params)

    # ─── Documents ────────────────────────────────────────────────────
    def create_document(self, payload, headers):
        return self._request("POST", "/dmv/documents", payload, headers)

    def get_document(self, document_id, headers):
        return self._request("GET", f"/dmv/documents/{document_id}", headers=headers)

    def verify_document(self, document_id, payload, headers):
        return self._request("POST", f"/dmv/documents/{document_id}/verify", payload, headers)

    # ─── Fee quotes ───────────────────────────────────────────────────
    def list_fee_quotes(self, headers, params=None):
        return self._request("GET", "/dmv/fee-quotes", headers=headers, params=params)

    def get_fee_quote(self, quote_id, headers):
        return self._request("GET", f"/dmv/fee-quotes/{quote_id}", headers=headers)

    # ─── Submissions & runner trips ───────────────────────────────────
    def list_submissions(self, headers, params=None):
        return self._request("GET", "/dmv/submissions", headers=headers, params=params)

    def get_submission(self, submission_id, headers):
        return self._request("GET", f"/dmv/submissions/{submission_id}", headers=headers)

    def submission_decision(self, submission_id, payload, headers):
        return self._request("POST", f"/dmv/submissions/{submission_id}/decision", payload, headers)

    def create_runner_trip(self, payload, headers):
        return self._request("POST", "/dmv/runner-trips", payload, headers)

    def get_runner_trip(self, trip_id, headers):
        return self._request("GET", f"/dmv/runner-trips/{trip_id}", headers=headers)

    def attach_leg(self, trip_id, payload, headers):
        return self._request("POST", f"/dmv/runner-trips/{trip_id}/legs", payload, headers)

    def list_trip_legs(self, trip_id, headers, params=None):
        return self._request("GET", f"/dmv/runner-trips/{trip_id}/legs", headers=headers, params=params)

    def dispatch_trip(self, trip_id, headers, payload=None):
        return self._request("POST", f"/dmv/runner-trips/{trip_id}/dispatch", payload or {}, headers)

    def return_trip(self, trip_id, headers, payload=None):
        return self._request("POST", f"/dmv/runner-trips/{trip_id}/return", payload or {}, headers)

    def close_trip(self, trip_id, headers, payload=None):
        return self._request("POST", f"/dmv/runner-trips/{trip_id}/close", payload or {}, headers)

    def list_runner_legs(self, headers, params=None):
        return self._request("GET", "/dmv/runner-legs", headers=headers, params=params)

    def get_runner_leg(self, leg_id, headers):
        return self._request("GET", f"/dmv/runner-legs/{leg_id}", headers=headers)

    # ─── Lien packets ─────────────────────────────────────────────────
    def create_lien_packet(self, payload, headers):
        return self._request("POST", "/dmv/lien-packets", payload, headers)

    def get_lien_packet(self, packet_id, headers):
        return self._request("GET", f"/dmv/lien-packets/{packet_id}", headers=headers)

    def perfect_lien_packet(self, packet_id, headers, payload=None):
        return self._request("POST", f"/dmv/lien-packets/{packet_id}/perfect", payload or {}, headers)

    def list_lien_packets(self, headers, params=None):
        return self._request("GET", "/dmv/lien-packets", headers=headers, params=params)


api_client = ApiClient()
