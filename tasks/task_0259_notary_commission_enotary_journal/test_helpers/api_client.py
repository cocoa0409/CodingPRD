"""API client: one method per endpoint defined in the PRD.

Subclasses GenericApiClient; the base _request() handles HTTP and the envelope.
Notary-driven endpoints are ownership-gated, so callers pass headers built from
the acting notary's id (see test_users.make_notary_headers).
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------- Clock (test-driving) ----------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def advance_clock(self, payload, headers):
        return self._request("POST", "/_clock/advance", payload, headers)

    # ---------------- Jurisdiction ----------------
    def create_jurisdiction(self, payload, headers):
        return self._request("POST", "/jurisdictions", payload, headers)

    def get_jurisdiction(self, jurisdiction_id, headers):
        return self._request("GET", f"/jurisdictions/{jurisdiction_id}", headers=headers)

    def list_jurisdictions(self, headers, params=None):
        return self._request("GET", "/jurisdictions", headers=headers, params=params)

    # ---------------- FeeSchedule ----------------
    def create_fee_schedule(self, jurisdiction_id, payload, headers):
        return self._request("POST", f"/jurisdictions/{jurisdiction_id}/fee-schedules", payload, headers)

    def list_fee_schedules_for_jurisdiction(self, jurisdiction_id, headers, params=None):
        return self._request("GET", f"/jurisdictions/{jurisdiction_id}/fee-schedules", headers=headers, params=params)

    def get_fee_schedule(self, fee_schedule_id, headers):
        return self._request("GET", f"/fee-schedules/{fee_schedule_id}", headers=headers)

    def list_fee_schedules(self, headers, params=None):
        return self._request("GET", "/fee-schedules", headers=headers, params=params)

    # ---------------- Notary ----------------
    def register_notary(self, payload, headers):
        return self._request("POST", "/notaries", payload, headers)

    def get_notary(self, notary_id, headers):
        return self._request("GET", f"/notaries/{notary_id}", headers=headers)

    def list_notaries(self, headers, params=None):
        return self._request("GET", "/notaries", headers=headers, params=params)

    def commission_notary(self, notary_id, headers):
        return self._request("POST", f"/notaries/{notary_id}/commission", {}, headers)

    def reject_notary(self, notary_id, headers):
        return self._request("POST", f"/notaries/{notary_id}/reject", {}, headers)

    def activate_notary(self, notary_id, headers):
        return self._request("POST", f"/notaries/{notary_id}/activate", {}, headers)

    def suspend_notary(self, notary_id, headers):
        return self._request("POST", f"/notaries/{notary_id}/suspend", {}, headers)

    def reinstate_notary(self, notary_id, headers):
        return self._request("POST", f"/notaries/{notary_id}/reinstate", {}, headers)

    def revoke_notary(self, notary_id, headers):
        return self._request("POST", f"/notaries/{notary_id}/revoke", {}, headers)

    def list_notary_audit_events(self, notary_id, headers, params=None):
        return self._request("GET", f"/notaries/{notary_id}/audit-events", headers=headers, params=params)

    def get_audit_event(self, audit_event_id, headers):
        return self._request("GET", f"/audit-events/{audit_event_id}", headers=headers)

    def list_audit_events(self, headers, params=None):
        return self._request("GET", "/audit-events", headers=headers, params=params)

    # ---------------- Bond ----------------
    def create_bond(self, payload, headers):
        return self._request("POST", "/bonds", payload, headers)

    def get_bond(self, bond_id, headers):
        return self._request("GET", f"/bonds/{bond_id}", headers=headers)

    def list_bonds(self, headers, params=None):
        return self._request("GET", "/bonds", headers=headers, params=params)

    def activate_bond(self, bond_id, headers):
        return self._request("POST", f"/bonds/{bond_id}/activate", {}, headers)

    # ---------------- Renewal ----------------
    def create_renewal(self, payload, headers):
        return self._request("POST", "/renewals", payload, headers)

    def get_renewal(self, renewal_id, headers):
        return self._request("GET", f"/renewals/{renewal_id}", headers=headers)

    def list_renewals(self, headers, params=None):
        return self._request("GET", "/renewals", headers=headers, params=params)

    def approve_renewal(self, renewal_id, headers):
        return self._request("POST", f"/renewals/{renewal_id}/approve", {}, headers)

    def deny_renewal(self, renewal_id, headers):
        return self._request("POST", f"/renewals/{renewal_id}/deny", {}, headers)

    # ---------------- Session ----------------
    def create_session(self, payload, headers):
        return self._request("POST", "/sessions", payload, headers)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/sessions/{session_id}", headers=headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/sessions", headers=headers, params=params)

    def add_signer(self, session_id, payload, headers):
        return self._request("POST", f"/sessions/{session_id}/signers", payload, headers)

    def list_signers_in_session(self, session_id, headers, params=None):
        return self._request("GET", f"/sessions/{session_id}/signers", headers=headers, params=params)

    def get_signer(self, signer_id, headers):
        return self._request("GET", f"/signers/{signer_id}", headers=headers)

    def list_signers(self, headers, params=None):
        return self._request("GET", "/signers", headers=headers, params=params)

    def add_document(self, session_id, payload, headers):
        return self._request("POST", f"/sessions/{session_id}/documents", payload, headers)

    def list_documents_in_session(self, session_id, headers, params=None):
        return self._request("GET", f"/sessions/{session_id}/documents", headers=headers, params=params)

    def get_document(self, document_id, headers):
        return self._request("GET", f"/documents/{document_id}", headers=headers)

    def list_documents(self, headers, params=None):
        return self._request("GET", "/documents", headers=headers, params=params)

    def begin_identity(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/begin-identity", {}, headers)

    def resolve_identity(self, session_id, payload, headers):
        return self._request("POST", f"/sessions/{session_id}/resolve-identity", payload, headers)

    def start_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/start", {}, headers)

    def notarize_document(self, session_id, document_id, payload, headers):
        return self._request("POST", f"/sessions/{session_id}/documents/{document_id}/notarize", payload, headers)

    def refuse_document(self, session_id, document_id, headers):
        return self._request("POST", f"/sessions/{session_id}/documents/{document_id}/refuse", {}, headers)

    def complete_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/complete", {}, headers)

    def terminate_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/terminate", {}, headers)

    # ---------------- JournalEntry ----------------
    def create_journal_entry(self, payload, headers):
        return self._request("POST", "/journal-entries", payload, headers)

    def get_journal_entry(self, entry_id, headers):
        return self._request("GET", f"/journal-entries/{entry_id}", headers=headers)

    def list_journal_entries(self, headers, params=None):
        return self._request("GET", "/journal-entries", headers=headers, params=params)

    def amend_journal_entry(self, entry_id, payload, headers):
        return self._request("POST", f"/journal-entries/{entry_id}/amend", payload, headers)

    def void_journal_entry(self, entry_id, headers):
        return self._request("POST", f"/journal-entries/{entry_id}/void", {}, headers)

    # ---------------- Complaint ----------------
    def create_complaint(self, payload, headers):
        return self._request("POST", "/complaints", payload, headers)

    def get_complaint(self, complaint_id, headers):
        return self._request("GET", f"/complaints/{complaint_id}", headers=headers)

    def list_complaints(self, headers, params=None):
        return self._request("GET", "/complaints", headers=headers, params=params)

    def open_review(self, complaint_id, headers):
        return self._request("POST", f"/complaints/{complaint_id}/open-review", {}, headers)

    def request_info(self, complaint_id, headers):
        return self._request("POST", f"/complaints/{complaint_id}/request-info", {}, headers)

    def resume_review(self, complaint_id, headers):
        return self._request("POST", f"/complaints/{complaint_id}/resume-review", {}, headers)

    def substantiate(self, complaint_id, headers):
        return self._request("POST", f"/complaints/{complaint_id}/substantiate", {}, headers)

    def dismiss(self, complaint_id, headers):
        return self._request("POST", f"/complaints/{complaint_id}/dismiss", {}, headers)

    def settle(self, complaint_id, headers):
        return self._request("POST", f"/complaints/{complaint_id}/settle", {}, headers)


api_client = ApiClient()
