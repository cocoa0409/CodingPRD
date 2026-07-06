"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; only the domain endpoint methods are
generated here. The whole API is mounted under the ``/notary`` prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Logical clock ──────────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/notary/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ─── FeeSchedule ────────────────────────────────────────────────────
    def create_fee_schedule(self, payload, headers):
        return self._request("POST", "/notary/fee-schedules", payload, headers)

    def get_fee_schedule(self, fee_schedule_id, headers):
        return self._request("GET", f"/notary/fee-schedules/{fee_schedule_id}", headers=headers)

    def list_fee_schedules(self, headers, params=None):
        return self._request("GET", "/notary/fee-schedules", headers=headers, params=params)

    # ─── Account ────────────────────────────────────────────────────────
    def create_account(self, payload, headers):
        return self._request("POST", "/notary/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/notary/accounts/{account_id}", headers=headers)

    # ─── Notary ─────────────────────────────────────────────────────────
    def create_notary(self, payload, headers):
        return self._request("POST", "/notary/notaries", payload, headers)

    def get_notary(self, notary_id, headers):
        return self._request("GET", f"/notary/notaries/{notary_id}", headers=headers)

    def list_notaries(self, headers, params=None):
        return self._request("GET", "/notary/notaries", headers=headers, params=params)

    def suspend_notary(self, notary_id, headers):
        return self._request("POST", f"/notary/notaries/{notary_id}/suspend", {}, headers)

    def reinstate_notary(self, notary_id, headers):
        return self._request("POST", f"/notary/notaries/{notary_id}/reinstate", {}, headers)

    def expire_notary(self, notary_id, headers):
        return self._request("POST", f"/notary/notaries/{notary_id}/expire", {}, headers)

    # ─── Signer ─────────────────────────────────────────────────────────
    def create_signer(self, payload, headers):
        return self._request("POST", "/notary/signers", payload, headers)

    def get_signer(self, signer_id, headers):
        return self._request("GET", f"/notary/signers/{signer_id}", headers=headers)

    def list_signers(self, headers, params=None):
        return self._request("GET", "/notary/signers", headers=headers, params=params)

    # ─── SigningRequest ─────────────────────────────────────────────────
    def create_request(self, payload, headers):
        return self._request("POST", "/notary/requests", payload, headers)

    def get_request(self, request_id, headers):
        return self._request("GET", f"/notary/requests/{request_id}", headers=headers)

    def list_requests(self, headers, params=None):
        return self._request("GET", "/notary/requests", headers=headers, params=params)

    def quote_request(self, request_id, headers):
        return self._request("POST", f"/notary/requests/{request_id}/quote", {}, headers)

    def assign_request(self, request_id, payload, headers):
        return self._request("POST", f"/notary/requests/{request_id}/assign", payload, headers)

    def revise_request(self, request_id, headers):
        return self._request("POST", f"/notary/requests/{request_id}/revise", {}, headers)

    def start_session(self, request_id, headers):
        return self._request("POST", f"/notary/requests/{request_id}/start-session", {}, headers)

    def complete_request(self, request_id, payload, headers):
        return self._request("POST", f"/notary/requests/{request_id}/complete", payload, headers)

    def cancel_request(self, request_id, headers):
        return self._request("POST", f"/notary/requests/{request_id}/cancel", {}, headers)

    # ─── RequestDocument ────────────────────────────────────────────────
    def create_document(self, payload, headers):
        return self._request("POST", "/notary/documents", payload, headers)

    def get_document(self, document_id, headers):
        return self._request("GET", f"/notary/documents/{document_id}", headers=headers)

    def list_documents(self, headers, params=None):
        return self._request("GET", "/notary/documents", headers=headers, params=params)

    # ─── Assignment ─────────────────────────────────────────────────────
    def list_assignments(self, headers, params=None):
        return self._request("GET", "/notary/assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/notary/assignments/{assignment_id}", headers=headers)

    # ─── RonSession ─────────────────────────────────────────────────────
    def create_ron_session(self, payload, headers):
        return self._request("POST", "/notary/ron-sessions", payload, headers)

    def get_ron_session(self, session_id, headers):
        return self._request("GET", f"/notary/ron-sessions/{session_id}", headers=headers)

    def list_ron_sessions(self, headers, params=None):
        return self._request("GET", "/notary/ron-sessions", headers=headers, params=params)

    # ─── IdVerification ─────────────────────────────────────────────────
    def create_id_verification(self, payload, headers):
        return self._request("POST", "/notary/id-verifications", payload, headers)

    def get_id_verification(self, verification_id, headers):
        return self._request("GET", f"/notary/id-verifications/{verification_id}", headers=headers)

    def list_id_verifications(self, headers, params=None):
        return self._request("GET", "/notary/id-verifications", headers=headers, params=params)

    # ─── JournalEntry ───────────────────────────────────────────────────
    def create_journal_entry(self, payload, headers):
        return self._request("POST", "/notary/journal-entries", payload, headers)

    def void_journal_entry(self, entry_id, headers):
        return self._request("POST", f"/notary/journal-entries/{entry_id}/void", {}, headers)

    def get_journal_entry(self, entry_id, headers):
        return self._request("GET", f"/notary/journal-entries/{entry_id}", headers=headers)

    def list_journal_entries(self, headers, params=None):
        return self._request("GET", "/notary/journal-entries", headers=headers, params=params)

    # ─── ApostilleOrder ─────────────────────────────────────────────────
    def create_apostille_order(self, payload, headers):
        return self._request("POST", "/notary/apostille-orders", payload, headers)

    def get_apostille_order(self, order_id, headers):
        return self._request("GET", f"/notary/apostille-orders/{order_id}", headers=headers)

    def list_apostille_orders(self, headers, params=None):
        return self._request("GET", "/notary/apostille-orders", headers=headers, params=params)

    def route_apostille_order(self, order_id, headers):
        return self._request("POST", f"/notary/apostille-orders/{order_id}/route", {}, headers)

    def reject_apostille_order(self, order_id, headers):
        return self._request("POST", f"/notary/apostille-orders/{order_id}/reject", {}, headers)

    def authenticate_apostille_order(self, order_id, headers):
        return self._request("POST", f"/notary/apostille-orders/{order_id}/authenticate", {}, headers)

    def return_apostille_order(self, order_id, headers):
        return self._request("POST", f"/notary/apostille-orders/{order_id}/return", {}, headers)

    def resubmit_apostille_order(self, order_id, headers):
        return self._request("POST", f"/notary/apostille-orders/{order_id}/resubmit", {}, headers)

    # ─── LoanPackage ────────────────────────────────────────────────────
    def create_loan_package(self, payload, headers):
        return self._request("POST", "/notary/loan-packages", payload, headers)

    def get_loan_package(self, package_id, headers):
        return self._request("GET", f"/notary/loan-packages/{package_id}", headers=headers)

    def list_loan_packages(self, headers, params=None):
        return self._request("GET", "/notary/loan-packages", headers=headers, params=params)

    def scrub_loan_package(self, package_id, headers):
        return self._request("POST", f"/notary/loan-packages/{package_id}/scrub", {}, headers)

    def unscrub_loan_package(self, package_id, headers):
        return self._request("POST", f"/notary/loan-packages/{package_id}/unscrub", {}, headers)

    def fund_loan_package(self, package_id, payload, headers):
        return self._request("POST", f"/notary/loan-packages/{package_id}/fund", payload, headers)

    def cancel_loan_package(self, package_id, headers):
        return self._request("POST", f"/notary/loan-packages/{package_id}/cancel", {}, headers)

    # ─── RetentionRecord ────────────────────────────────────────────────
    def get_retention_record(self, record_id, headers):
        return self._request("GET", f"/notary/retention-records/{record_id}", headers=headers)

    def list_retention_records(self, headers, params=None):
        return self._request("GET", "/notary/retention-records", headers=headers, params=params)


api_client = ApiClient()
