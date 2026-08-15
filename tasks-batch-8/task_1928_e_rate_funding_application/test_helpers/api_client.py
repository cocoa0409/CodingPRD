"""API client: one method per endpoint defined in the PRD (§4 routing table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD §2.4) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/erate/_clock/set_current_utc", payload, headers)

    # --- FundingCycle ---
    def create_funding_cycle(self, payload, headers):
        return self._request("POST", "/erate/funding-cycles", payload, headers)

    def list_funding_cycles(self, headers, params=None):
        return self._request("GET", "/erate/funding-cycles", headers=headers, params=params)

    def get_funding_cycle(self, cycle_id, headers):
        return self._request("GET", f"/erate/funding-cycles/{cycle_id}", headers=headers)

    # --- EligibleService ---
    def create_eligible_service(self, payload, headers):
        return self._request("POST", "/erate/eligible-services", payload, headers)

    def list_eligible_services(self, headers, params=None):
        return self._request("GET", "/erate/eligible-services", headers=headers, params=params)

    def get_eligible_service(self, service_id, headers):
        return self._request("GET", f"/erate/eligible-services/{service_id}", headers=headers)

    # --- Applicant ---
    def create_applicant(self, payload, headers):
        return self._request("POST", "/erate/applicants", payload, headers)

    def list_applicants(self, headers, params=None):
        return self._request("GET", "/erate/applicants", headers=headers, params=params)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"/erate/applicants/{applicant_id}", headers=headers)

    def get_budget_summary(self, applicant_id, headers, params=None):
        return self._request(
            "GET", f"/erate/applicants/{applicant_id}/budget-summary",
            headers=headers, params=params,
        )

    def set_audit_hold(self, applicant_id, payload, headers):
        return self._request(
            "POST", f"/erate/applicants/{applicant_id}/set-audit-hold", payload, headers
        )

    # --- NSLPSnapshot ---
    def create_nslp_snapshot(self, payload, headers):
        return self._request("POST", "/erate/nslp-snapshots", payload, headers)

    def list_nslp_snapshots(self, headers, params=None):
        return self._request("GET", "/erate/nslp-snapshots", headers=headers, params=params)

    def get_nslp_snapshot(self, snapshot_id, headers):
        return self._request("GET", f"/erate/nslp-snapshots/{snapshot_id}", headers=headers)

    # --- ApplicantUser ---
    def create_applicant_user(self, payload, headers):
        return self._request("POST", "/erate/applicant-users", payload, headers)

    def list_applicant_users(self, headers, params=None):
        return self._request("GET", "/erate/applicant-users", headers=headers, params=params)

    def get_applicant_user(self, user_id, headers):
        return self._request("GET", f"/erate/applicant-users/{user_id}", headers=headers)

    # --- ServiceProvider ---
    def create_service_provider(self, payload, headers):
        return self._request("POST", "/erate/service-providers", payload, headers)

    def list_service_providers(self, headers, params=None):
        return self._request("GET", "/erate/service-providers", headers=headers, params=params)

    def get_service_provider(self, provider_id, headers):
        return self._request("GET", f"/erate/service-providers/{provider_id}", headers=headers)

    # --- ProcurementPosting ---
    def create_procurement_posting(self, payload, headers):
        return self._request("POST", "/erate/procurement-postings", payload, headers)

    def list_procurement_postings(self, headers, params=None):
        return self._request("GET", "/erate/procurement-postings", headers=headers, params=params)

    def get_procurement_posting(self, posting_id, headers):
        return self._request("GET", f"/erate/procurement-postings/{posting_id}", headers=headers)

    def publish_posting(self, posting_id, headers):
        return self._request(
            "POST", f"/erate/procurement-postings/{posting_id}/publish", {}, headers
        )

    def close_posting_window(self, posting_id, headers):
        return self._request(
            "POST", f"/erate/procurement-postings/{posting_id}/close-window", {}, headers
        )

    def cancel_posting(self, posting_id, headers):
        return self._request(
            "POST", f"/erate/procurement-postings/{posting_id}/cancel", {}, headers
        )

    def select_winner(self, posting_id, headers):
        return self._request(
            "POST", f"/erate/procurement-postings/{posting_id}/select-winner", {}, headers
        )

    # --- Bid ---
    def create_bid(self, payload, headers):
        return self._request("POST", "/erate/bids", payload, headers)

    def list_bids(self, headers, params=None):
        return self._request("GET", "/erate/bids", headers=headers, params=params)

    def get_bid(self, bid_id, headers):
        return self._request("GET", f"/erate/bids/{bid_id}", headers=headers)

    def qualify_bid(self, bid_id, headers):
        return self._request("POST", f"/erate/bids/{bid_id}/qualify", {}, headers)

    def disqualify_bid(self, bid_id, payload, headers):
        return self._request("POST", f"/erate/bids/{bid_id}/disqualify", payload, headers)

    # --- Contract ---
    def create_contract(self, payload, headers):
        return self._request("POST", "/erate/contracts", payload, headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/erate/contracts", headers=headers, params=params)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/erate/contracts/{contract_id}", headers=headers)

    def certify_contract(self, contract_id, headers):
        return self._request("POST", f"/erate/contracts/{contract_id}/certify", {}, headers)

    def terminate_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/erate/contracts/{contract_id}/terminate", payload, headers)

    # --- FundingRequest ---
    def create_funding_request(self, payload, headers):
        return self._request("POST", "/erate/funding-requests", payload, headers)

    def list_funding_requests(self, headers, params=None):
        return self._request("GET", "/erate/funding-requests", headers=headers, params=params)

    def get_funding_request(self, request_id, headers):
        return self._request("GET", f"/erate/funding-requests/{request_id}", headers=headers)

    def certify_funding_request(self, request_id, headers):
        return self._request(
            "POST", f"/erate/funding-requests/{request_id}/certify", {}, headers
        )

    def begin_review(self, request_id, headers):
        return self._request(
            "POST", f"/erate/funding-requests/{request_id}/begin-review", {}, headers
        )

    def request_info(self, request_id, payload, headers):
        return self._request(
            "POST", f"/erate/funding-requests/{request_id}/request-info", payload, headers
        )

    def submit_pia_response(self, request_id, payload, headers):
        return self._request(
            "POST", f"/erate/funding-requests/{request_id}/pia-responses", payload, headers
        )

    def decide_funding_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/erate/funding-requests/{request_id}/decide", payload, headers
        )

    def record_service_start(self, request_id, headers):
        return self._request(
            "POST", f"/erate/funding-requests/{request_id}/service-start", {}, headers
        )

    # --- FundingRequestLine ---
    def create_funding_request_line(self, payload, headers):
        return self._request("POST", "/erate/funding-request-lines", payload, headers)

    def list_funding_request_lines(self, headers, params=None):
        return self._request("GET", "/erate/funding-request-lines", headers=headers, params=params)

    def get_funding_request_line(self, line_id, headers):
        return self._request("GET", f"/erate/funding-request-lines/{line_id}", headers=headers)

    # --- InvoiceSubmission ---
    def create_invoice_submission(self, payload, headers):
        return self._request("POST", "/erate/invoice-submissions", payload, headers)

    def list_invoice_submissions(self, headers, params=None):
        return self._request("GET", "/erate/invoice-submissions", headers=headers, params=params)

    def get_invoice_submission(self, invoice_id, headers):
        return self._request("GET", f"/erate/invoice-submissions/{invoice_id}", headers=headers)

    def begin_invoice_review(self, invoice_id, headers):
        return self._request(
            "POST", f"/erate/invoice-submissions/{invoice_id}/begin-review", {}, headers
        )

    def approve_invoice(self, invoice_id, headers):
        return self._request(
            "POST", f"/erate/invoice-submissions/{invoice_id}/approve", {}, headers
        )

    def pay_invoice(self, invoice_id, headers):
        return self._request(
            "POST", f"/erate/invoice-submissions/{invoice_id}/pay", {}, headers
        )

    def reject_invoice(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/erate/invoice-submissions/{invoice_id}/reject", payload, headers
        )

    def resubmit_invoice(self, invoice_id, headers):
        return self._request(
            "POST", f"/erate/invoice-submissions/{invoice_id}/resubmit", {}, headers
        )

    # --- ServiceSubstitution ---
    def create_service_substitution(self, payload, headers):
        return self._request("POST", "/erate/service-substitutions", payload, headers)

    def list_service_substitutions(self, headers, params=None):
        return self._request("GET", "/erate/service-substitutions", headers=headers, params=params)

    def get_service_substitution(self, substitution_id, headers):
        return self._request("GET", f"/erate/service-substitutions/{substitution_id}", headers=headers)

    def approve_substitution(self, substitution_id, headers):
        return self._request(
            "POST", f"/erate/service-substitutions/{substitution_id}/approve", {}, headers
        )

    def deny_substitution(self, substitution_id, payload, headers):
        return self._request(
            "POST", f"/erate/service-substitutions/{substitution_id}/deny", payload, headers
        )

    # --- Appeal ---
    def create_appeal(self, payload, headers):
        return self._request("POST", "/erate/appeals", payload, headers)

    def list_appeals(self, headers, params=None):
        return self._request("GET", "/erate/appeals", headers=headers, params=params)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/erate/appeals/{appeal_id}", headers=headers)

    def begin_appeal_review(self, appeal_id, headers):
        return self._request("POST", f"/erate/appeals/{appeal_id}/begin-review", {}, headers)

    def decide_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/erate/appeals/{appeal_id}/decide", payload, headers)

    # --- RetainedDocument ---
    def list_retained_documents(self, headers, params=None):
        return self._request("GET", "/erate/retained-documents", headers=headers, params=params)

    def get_retained_document(self, document_id, headers):
        return self._request("GET", f"/erate/retained-documents/{document_id}", headers=headers)

    def place_document_hold(self, document_id, payload, headers):
        return self._request(
            "POST", f"/erate/retained-documents/{document_id}/place-hold", payload, headers
        )

    def release_document_hold(self, document_id, headers):
        return self._request(
            "POST", f"/erate/retained-documents/{document_id}/release-hold", {}, headers
        )

    def purge_document(self, document_id, headers):
        return self._request(
            "POST", f"/erate/retained-documents/{document_id}/purge", {}, headers
        )


api_client = ApiClient()
