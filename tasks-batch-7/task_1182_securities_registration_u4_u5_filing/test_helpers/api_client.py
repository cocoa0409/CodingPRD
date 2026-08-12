"""API client: one method per endpoint defined in PRD Section 4."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/registration-desk"


class ApiClient(GenericApiClient):
    # --- clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- firms ---
    def create_firm(self, payload, headers):
        return self._request("POST", f"{PREFIX}/firms", payload, headers)

    def get_firm(self, firm_id, headers):
        return self._request("GET", f"{PREFIX}/firms/{firm_id}", headers=headers)

    def list_firms(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/firms", headers=headers, params=params)

    def patch_firm(self, firm_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/firms/{firm_id}", payload, headers)

    # --- applicants ---
    def create_applicant(self, payload, headers):
        return self._request("POST", f"{PREFIX}/applicants", payload, headers)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"{PREFIX}/applicants/{applicant_id}", headers=headers)

    def list_applicants(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/applicants", headers=headers, params=params)

    # --- registration requests ---
    def create_registration_request(self, payload, headers):
        return self._request("POST", f"{PREFIX}/registration-requests", payload, headers)

    def get_registration_request(self, request_id, headers):
        return self._request(
            "GET", f"{PREFIX}/registration-requests/{request_id}", headers=headers
        )

    def list_registration_requests(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/registration-requests", headers=headers, params=params
        )

    def patch_registration_request(self, request_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/registration-requests/{request_id}", payload, headers
        )

    def submit_registration_request(self, request_id, headers):
        return self._request(
            "POST", f"{PREFIX}/registration-requests/{request_id}/submit",
            {}, headers,
        )

    def approve_registration_request(self, request_id, headers):
        return self._request(
            "POST", f"{PREFIX}/registration-requests/{request_id}/approve",
            {}, headers,
        )

    def return_deficient_registration_request(self, request_id, headers):
        return self._request(
            "POST", f"{PREFIX}/registration-requests/{request_id}/return-deficient",
            {}, headers,
        )

    def deny_registration_request(self, request_id, headers):
        return self._request(
            "POST", f"{PREFIX}/registration-requests/{request_id}/deny",
            {}, headers,
        )

    def withdraw_registration_request(self, request_id, headers):
        return self._request(
            "POST", f"{PREFIX}/registration-requests/{request_id}/withdraw",
            {}, headers,
        )

    def get_renewal_estimate(self, request_id, cycle_year, headers):
        return self._request(
            "GET",
            f"{PREFIX}/registration-requests/{request_id}/renewal-estimate",
            headers=headers,
            params={"cycle_year": cycle_year},
        )

    # --- jurisdiction selections ---
    def create_jurisdiction_selection(self, payload, headers):
        return self._request("POST", f"{PREFIX}/jurisdiction-selections", payload, headers)

    def list_jurisdiction_selections(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/jurisdiction-selections", headers=headers, params=params
        )

    def get_jurisdiction_selection(self, selection_id, headers):
        return self._request(
            "GET", f"{PREFIX}/jurisdiction-selections/{selection_id}", headers=headers
        )

    def relinquish_jurisdiction_selection(self, selection_id, headers):
        return self._request(
            "POST", f"{PREFIX}/jurisdiction-selections/{selection_id}/relinquish",
            {}, headers,
        )

    # --- fingerprint submissions ---
    def create_fingerprint_submission(self, payload, headers):
        return self._request("POST", f"{PREFIX}/fingerprint-submissions", payload, headers)

    def list_fingerprint_submissions(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/fingerprint-submissions", headers=headers, params=params
        )

    def get_fingerprint_submission(self, submission_id, headers):
        return self._request(
            "GET", f"{PREFIX}/fingerprint-submissions/{submission_id}", headers=headers
        )

    def process_fingerprint_submission(self, submission_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/fingerprint-submissions/{submission_id}/process",
            payload, headers,
        )

    # --- background disclosures ---
    def create_background_disclosure(self, payload, headers):
        return self._request("POST", f"{PREFIX}/background-disclosures", payload, headers)

    def list_background_disclosures(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/background-disclosures", headers=headers, params=params
        )

    def get_background_disclosure(self, disclosure_id, headers):
        return self._request(
            "GET", f"{PREFIX}/background-disclosures/{disclosure_id}", headers=headers
        )

    def review_background_disclosure(self, disclosure_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/background-disclosures/{disclosure_id}/review",
            payload, headers,
        )

    # --- exam requirements & windows ---
    def create_exam_requirement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/exam-requirements", payload, headers)

    def list_exam_requirements(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/exam-requirements", headers=headers, params=params
        )

    def get_exam_requirement(self, requirement_id, headers):
        return self._request(
            "GET", f"{PREFIX}/exam-requirements/{requirement_id}", headers=headers
        )

    def waive_exam_requirement(self, requirement_id, headers):
        return self._request(
            "POST", f"{PREFIX}/exam-requirements/{requirement_id}/waive",
            {}, headers,
        )

    def create_exam_window(self, payload, headers):
        return self._request("POST", f"{PREFIX}/exam-windows", payload, headers)

    def list_exam_windows(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/exam-windows", headers=headers, params=params)

    def get_exam_window(self, window_id, headers):
        return self._request("GET", f"{PREFIX}/exam-windows/{window_id}", headers=headers)

    def record_exam_result(self, window_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/exam-windows/{window_id}/record-result",
            payload, headers,
        )

    def cancel_exam_window(self, window_id, headers):
        return self._request(
            "POST", f"{PREFIX}/exam-windows/{window_id}/cancel", {}, headers
        )

    # --- disclosure events & amendments ---
    def create_disclosure_event(self, payload, headers):
        return self._request("POST", f"{PREFIX}/disclosure-events", payload, headers)

    def list_disclosure_events(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/disclosure-events", headers=headers, params=params)

    def get_disclosure_event(self, event_id, headers):
        return self._request(
            "GET", f"{PREFIX}/disclosure-events/{event_id}", headers=headers
        )

    def create_amendment_filing(self, payload, headers):
        return self._request("POST", f"{PREFIX}/amendment-filings", payload, headers)

    def list_amendment_filings(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/amendment-filings", headers=headers, params=params)

    def get_amendment_filing(self, filing_id, headers):
        return self._request(
            "GET", f"{PREFIX}/amendment-filings/{filing_id}", headers=headers
        )

    def accept_amendment_filing(self, filing_id, headers):
        return self._request(
            "POST", f"{PREFIX}/amendment-filings/{filing_id}/accept", {}, headers
        )

    def return_amendment_filing(self, filing_id, headers):
        return self._request(
            "POST", f"{PREFIX}/amendment-filings/{filing_id}/return", {}, headers
        )

    # --- termination filings (U5) ---
    def create_termination_filing(self, payload, headers):
        return self._request("POST", f"{PREFIX}/termination-filings", payload, headers)

    def list_termination_filings(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/termination-filings", headers=headers, params=params
        )

    def get_termination_filing(self, filing_id, headers):
        return self._request(
            "GET", f"{PREFIX}/termination-filings/{filing_id}", headers=headers
        )

    def open_amendment_termination_filing(self, filing_id, headers):
        return self._request(
            "POST", f"{PREFIX}/termination-filings/{filing_id}/open-amendment",
            {}, headers,
        )

    def close_amendment_termination_filing(self, filing_id, headers):
        return self._request(
            "POST", f"{PREFIX}/termination-filings/{filing_id}/close-amendment",
            {}, headers,
        )

    def close_termination_filing(self, filing_id, headers):
        return self._request(
            "POST", f"{PREFIX}/termination-filings/{filing_id}/close", {}, headers
        )

    # --- U5 comments ---
    def create_u5_comment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/u5-comments", payload, headers)

    def list_u5_comments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/u5-comments", headers=headers, params=params)

    def get_u5_comment(self, comment_id, headers):
        return self._request("GET", f"{PREFIX}/u5-comments/{comment_id}", headers=headers)

    # --- affiliation requests ---
    def create_affiliation_request(self, payload, headers):
        return self._request("POST", f"{PREFIX}/affiliation-requests", payload, headers)

    def list_affiliation_requests(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/affiliation-requests", headers=headers, params=params
        )

    def get_affiliation_request(self, affiliation_id, headers):
        return self._request(
            "GET", f"{PREFIX}/affiliation-requests/{affiliation_id}", headers=headers
        )

    def approve_affiliation_request(self, affiliation_id, headers):
        return self._request(
            "POST", f"{PREFIX}/affiliation-requests/{affiliation_id}/approve",
            {}, headers,
        )

    def deny_affiliation_request(self, affiliation_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/affiliation-requests/{affiliation_id}/deny",
            payload, headers,
        )

    def revoke_affiliation_request(self, affiliation_id, headers):
        return self._request(
            "POST", f"{PREFIX}/affiliation-requests/{affiliation_id}/revoke",
            {}, headers,
        )

    # --- renewal invoices ---
    def create_renewal_invoice(self, payload, headers):
        return self._request("POST", f"{PREFIX}/renewal-invoices", payload, headers)

    def list_renewal_invoices(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/renewal-invoices", headers=headers, params=params)

    def get_renewal_invoice(self, invoice_id, headers):
        return self._request(
            "GET", f"{PREFIX}/renewal-invoices/{invoice_id}", headers=headers
        )

    def pay_renewal_invoice(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/renewal-invoices/{invoice_id}/pay", payload, headers
        )

    def void_renewal_invoice(self, invoice_id, headers):
        return self._request(
            "POST", f"{PREFIX}/renewal-invoices/{invoice_id}/void", {}, headers
        )

    # --- regulatory inquiries ---
    def create_regulatory_inquiry(self, payload, headers):
        return self._request("POST", f"{PREFIX}/regulatory-inquiries", payload, headers)

    def list_regulatory_inquiries(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/regulatory-inquiries", headers=headers, params=params
        )

    def get_regulatory_inquiry(self, inquiry_id, headers):
        return self._request(
            "GET", f"{PREFIX}/regulatory-inquiries/{inquiry_id}", headers=headers
        )

    def route_regulatory_inquiry(self, inquiry_id, headers):
        return self._request(
            "POST", f"{PREFIX}/regulatory-inquiries/{inquiry_id}/route", {}, headers
        )

    def respond_regulatory_inquiry(self, inquiry_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/regulatory-inquiries/{inquiry_id}/respond",
            payload, headers,
        )

    def close_regulatory_inquiry(self, inquiry_id, headers):
        return self._request(
            "POST", f"{PREFIX}/regulatory-inquiries/{inquiry_id}/close", {}, headers
        )


api_client = ApiClient()
