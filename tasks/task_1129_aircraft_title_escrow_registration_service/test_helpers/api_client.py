"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Logical clock ────────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # ── Aircraft ─────────────────────────────────────────────────────
    def create_aircraft(self, payload, headers):
        return self._request("POST", "/api/aircraft", payload, headers)

    def get_aircraft(self, aircraft_id, headers):
        return self._request("GET", f"/api/aircraft/{aircraft_id}", headers=headers)

    def list_aircraft_trust_agreements(self, aircraft_id, headers, params=None):
        return self._request(
            "GET", f"/api/aircraft/{aircraft_id}/trust-agreements",
            headers=headers, params=params,
        )

    # ── Parties ──────────────────────────────────────────────────────
    def create_party(self, payload, headers):
        return self._request("POST", "/api/parties", payload, headers)

    def get_party(self, party_id, headers):
        return self._request("GET", f"/api/parties/{party_id}", headers=headers)

    # ── Escrow files ─────────────────────────────────────────────────
    def create_escrow_file(self, payload, headers):
        return self._request("POST", "/api/escrow-files", payload, headers)

    def get_escrow_file(self, file_id, headers):
        return self._request("GET", f"/api/escrow-files/{file_id}", headers=headers)

    def list_escrow_files(self, headers, params=None):
        return self._request("GET", "/api/escrow-files", headers=headers, params=params)

    def hold_escrow_file(self, file_id, headers):
        return self._request("POST", f"/api/escrow-files/{file_id}/hold", {}, headers)

    def resume_escrow_file(self, file_id, headers):
        return self._request("POST", f"/api/escrow-files/{file_id}/resume", {}, headers)

    def cancel_escrow_file(self, file_id, headers):
        return self._request("POST", f"/api/escrow-files/{file_id}/cancel", {}, headers)

    def close_escrow_file(self, file_id, payload, headers):
        return self._request("POST", f"/api/escrow-files/{file_id}/close", payload, headers)

    def get_escrow_file_statement(self, file_id, headers):
        return self._request("GET", f"/api/escrow-files/{file_id}/statement", headers=headers)

    # ── Title searches ───────────────────────────────────────────────
    def order_title_search(self, file_id, headers):
        return self._request("POST", f"/api/escrow-files/{file_id}/title-searches", {}, headers)

    def complete_title_search(self, search_id, payload, headers):
        return self._request("POST", f"/api/title-searches/{search_id}/complete", payload, headers)

    def refresh_title_search(self, search_id, headers):
        return self._request("POST", f"/api/title-searches/{search_id}/refresh", {}, headers)

    def list_title_searches(self, file_id, headers, params=None):
        return self._request(
            "GET", f"/api/escrow-files/{file_id}/title-searches",
            headers=headers, params=params,
        )

    # ── Liens ────────────────────────────────────────────────────────
    def list_liens(self, headers, params=None):
        return self._request("GET", "/api/liens", headers=headers, params=params)

    def get_lien(self, lien_id, headers):
        return self._request("GET", f"/api/liens/{lien_id}", headers=headers)

    def dispute_lien(self, lien_id, payload, headers):
        return self._request("POST", f"/api/liens/{lien_id}/dispute", payload, headers)

    def resolve_lien_dispute(self, lien_id, headers):
        return self._request("POST", f"/api/liens/{lien_id}/resolve-dispute", {}, headers)

    # ── Lien releases ────────────────────────────────────────────────
    def request_lien_release(self, lien_id, headers):
        return self._request("POST", f"/api/liens/{lien_id}/releases", {}, headers)

    def list_lien_releases(self, lien_id, headers, params=None):
        return self._request("GET", f"/api/liens/{lien_id}/releases", headers=headers, params=params)

    def quote_release(self, release_id, payload, headers):
        return self._request("POST", f"/api/releases/{release_id}/quote", payload, headers)

    def receive_release(self, release_id, headers):
        return self._request("POST", f"/api/releases/{release_id}/receive-release", {}, headers)

    def file_release(self, release_id, headers):
        return self._request("POST", f"/api/releases/{release_id}/file", {}, headers)

    def record_release(self, release_id, headers):
        return self._request("POST", f"/api/releases/{release_id}/record", {}, headers)

    def void_release(self, release_id, headers):
        return self._request("POST", f"/api/releases/{release_id}/void", {}, headers)

    # ── Deposits ─────────────────────────────────────────────────────
    def create_deposit(self, file_id, payload, headers):
        return self._request("POST", f"/api/escrow-files/{file_id}/deposits", payload, headers)

    def return_deposit(self, deposit_id, headers):
        return self._request("POST", f"/api/deposits/{deposit_id}/return", {}, headers)

    def list_deposits(self, headers, params=None):
        return self._request("GET", "/api/deposits", headers=headers, params=params)

    def get_deposit(self, deposit_id, headers):
        return self._request("GET", f"/api/deposits/{deposit_id}", headers=headers)

    # ── Disbursement instructions ────────────────────────────────────
    def create_disbursement(self, file_id, payload, headers):
        return self._request("POST", f"/api/escrow-files/{file_id}/disbursements", payload, headers)

    def approve_disbursement(self, disbursement_id, headers):
        return self._request("POST", f"/api/disbursements/{disbursement_id}/approve", {}, headers)

    def release_disbursement(self, disbursement_id, headers):
        return self._request("POST", f"/api/disbursements/{disbursement_id}/release", {}, headers)

    def void_disbursement(self, disbursement_id, headers):
        return self._request("POST", f"/api/disbursements/{disbursement_id}/void", {}, headers)

    def list_disbursements(self, headers, params=None):
        return self._request("GET", "/api/disbursements", headers=headers, params=params)

    def get_disbursement(self, disbursement_id, headers):
        return self._request("GET", f"/api/disbursements/{disbursement_id}", headers=headers)

    # ── Filings ──────────────────────────────────────────────────────
    def create_filing(self, file_id, payload, headers):
        return self._request("POST", f"/api/escrow-files/{file_id}/filings", payload, headers)

    def submit_filing(self, filing_id, headers):
        return self._request("POST", f"/api/filings/{filing_id}/submit", {}, headers)

    def accept_filing(self, filing_id, payload, headers):
        return self._request("POST", f"/api/filings/{filing_id}/accept", payload, headers)

    def reject_filing(self, filing_id, payload, headers):
        return self._request("POST", f"/api/filings/{filing_id}/reject", payload, headers)

    def resubmit_filing(self, filing_id, headers):
        return self._request("POST", f"/api/filings/{filing_id}/resubmit", {}, headers)

    def verify_filing(self, filing_id, payload, headers):
        return self._request("POST", f"/api/filings/{filing_id}/verify", payload, headers)

    def list_filings(self, headers, params=None):
        return self._request("GET", "/api/filings", headers=headers, params=params)

    def get_filing(self, filing_id, headers):
        return self._request("GET", f"/api/filings/{filing_id}", headers=headers)

    # ── Trust agreements ─────────────────────────────────────────────
    def create_trust_agreement(self, payload, headers):
        return self._request("POST", "/api/trust-agreements", payload, headers)

    def submit_trust_agreement(self, trust_id, headers):
        return self._request("POST", f"/api/trust-agreements/{trust_id}/submit", {}, headers)

    def accept_trust_agreement(self, trust_id, headers):
        return self._request("POST", f"/api/trust-agreements/{trust_id}/accept", {}, headers)

    def reject_trust_agreement(self, trust_id, headers):
        return self._request("POST", f"/api/trust-agreements/{trust_id}/reject", {}, headers)

    def revise_trust_agreement(self, trust_id, payload, headers):
        return self._request("POST", f"/api/trust-agreements/{trust_id}/revise", payload, headers)

    def list_trust_agreements(self, headers, params=None):
        return self._request("GET", "/api/trust-agreements", headers=headers, params=params)

    def get_trust_agreement(self, trust_id, headers):
        return self._request("GET", f"/api/trust-agreements/{trust_id}", headers=headers)

    # ── Closing documents ────────────────────────────────────────────
    def create_document(self, file_id, payload, headers):
        return self._request("POST", f"/api/escrow-files/{file_id}/documents", payload, headers)

    def send_document(self, document_id, headers):
        return self._request("POST", f"/api/documents/{document_id}/send", {}, headers)

    def sign_document(self, document_id, payload, headers):
        return self._request("POST", f"/api/documents/{document_id}/sign", payload, headers)

    def list_documents(self, file_id, headers, params=None):
        return self._request(
            "GET", f"/api/escrow-files/{file_id}/documents",
            headers=headers, params=params,
        )


api_client = ApiClient()
