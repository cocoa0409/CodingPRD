"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Issuers
    # ------------------------------------------------------------------
    def create_issuer(self, payload, headers):
        return self._request("POST", "/issuers", payload, headers)

    def get_issuer(self, issuer_id, headers):
        return self._request("GET", f"/issuers/{issuer_id}", headers=headers)

    def patch_issuer(self, issuer_id, payload, headers):
        return self._request("PATCH", f"/issuers/{issuer_id}", payload, headers)

    def create_freeze_window(self, issuer_id, payload, headers):
        return self._request("POST", f"/issuers/{issuer_id}/freeze-windows",
                             payload, headers)

    def list_freeze_windows(self, headers, params=None):
        return self._request("GET", "/freeze-windows", headers=headers, params=params)

    def list_issuer_freeze_windows(self, issuer_id, headers):
        return self._request("GET", f"/issuers/{issuer_id}/freeze-windows",
                             headers=headers)

    def get_record_date_report(self, issuer_id, declaration_id, headers):
        return self._request("GET", f"/issuers/{issuer_id}/record-date-report",
                             headers=headers, params={"declaration_id": declaration_id})

    def list_issuer_positions(self, issuer_id, headers):
        return self._request("GET", f"/issuers/{issuer_id}/positions", headers=headers)

    def list_issuer_certificates(self, issuer_id, headers):
        return self._request("GET", f"/issuers/{issuer_id}/certificates", headers=headers)

    def list_issuer_transfer_requests(self, issuer_id, headers):
        return self._request("GET", f"/issuers/{issuer_id}/transfer-requests",
                             headers=headers)

    # ------------------------------------------------------------------
    # Shareholder accounts
    # ------------------------------------------------------------------
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def patch_account(self, account_id, payload, headers):
        return self._request("PATCH", f"/accounts/{account_id}", payload, headers)

    def restrict_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/restrict", {}, headers)

    def release_restriction(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/release-restriction",
                             {}, headers)

    def get_statement(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}/statement", headers=headers)

    def create_position(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/positions", payload, headers)

    def list_account_positions(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}/positions", headers=headers)

    def list_account_certificates(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}/certificates", headers=headers)

    def list_account_transfer_requests(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}/transfer-requests",
                             headers=headers)

    # ------------------------------------------------------------------
    # Positions and certificates
    # ------------------------------------------------------------------
    def list_positions(self, headers, params=None):
        return self._request("GET", "/positions", headers=headers, params=params)

    def withdraw_certificate(self, position_id, payload, headers):
        return self._request("POST", f"/positions/{position_id}/certificate-withdrawals",
                             payload, headers)

    def list_certificates(self, headers, params=None):
        return self._request("GET", "/certificates", headers=headers, params=params)

    def convert_to_drs(self, certificate_id, headers):
        return self._request("POST", f"/certificates/{certificate_id}/convert-to-drs",
                             {}, headers)

    def report_lost(self, certificate_id, payload, headers):
        return self._request("POST", f"/certificates/{certificate_id}/report-lost",
                             payload, headers)

    def recover_certificate(self, certificate_id, headers):
        return self._request("POST", f"/certificates/{certificate_id}/recover",
                             {}, headers)

    # ------------------------------------------------------------------
    # Lost-certificate claims
    # ------------------------------------------------------------------
    def list_claims(self, headers, params=None):
        return self._request("GET", "/lost-certificate-claims", headers=headers,
                             params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/lost-certificate-claims/{claim_id}", headers=headers)

    def post_bond(self, claim_id, payload, headers):
        return self._request("POST", f"/lost-certificate-claims/{claim_id}/post-bond",
                             payload, headers)

    def approve_claim(self, claim_id, headers):
        return self._request("POST", f"/lost-certificate-claims/{claim_id}/approve",
                             {}, headers)

    def reject_claim(self, claim_id, headers):
        return self._request("POST", f"/lost-certificate-claims/{claim_id}/reject",
                             {}, headers)

    def issue_replacement(self, claim_id, headers):
        return self._request("POST",
                             f"/lost-certificate-claims/{claim_id}/issue-replacement",
                             {}, headers)

    # ------------------------------------------------------------------
    # Transfer requests
    # ------------------------------------------------------------------
    def create_transfer_request(self, payload, headers):
        return self._request("POST", "/transfer-requests", payload, headers)

    def list_transfer_requests(self, headers, params=None):
        return self._request("GET", "/transfer-requests", headers=headers, params=params)

    def get_transfer_request(self, transfer_id, headers):
        return self._request("GET", f"/transfer-requests/{transfer_id}", headers=headers)

    def submit_medallion(self, transfer_id, payload, headers):
        return self._request("POST",
                             f"/transfer-requests/{transfer_id}/submit-medallion",
                             payload, headers)

    def flag_transfer_deficient(self, transfer_id, payload, headers):
        return self._request("POST",
                             f"/transfer-requests/{transfer_id}/flag-deficient",
                             payload, headers)

    def cure_transfer_deficiency(self, transfer_id, headers):
        return self._request("POST",
                             f"/transfer-requests/{transfer_id}/cure-deficiency",
                             {}, headers)

    def approve_transfer_request(self, transfer_id, headers):
        return self._request("POST", f"/transfer-requests/{transfer_id}/approve",
                             {}, headers)

    def reject_transfer_request(self, transfer_id, headers):
        return self._request("POST", f"/transfer-requests/{transfer_id}/reject",
                             {}, headers)

    def cancel_transfer_request(self, transfer_id, headers):
        return self._request("POST", f"/transfer-requests/{transfer_id}/cancel",
                             {}, headers)

    def settle_transfer_request(self, transfer_id, headers):
        return self._request("POST", f"/transfer-requests/{transfer_id}/settle",
                             {}, headers)

    # ------------------------------------------------------------------
    # Dividend declarations and payments
    # ------------------------------------------------------------------
    def create_dividend_declaration(self, payload, headers):
        return self._request("POST", "/dividend-declarations", payload, headers)

    def list_dividend_declarations(self, headers, params=None):
        return self._request("GET", "/dividend-declarations", headers=headers,
                             params=params)

    def get_dividend_declaration(self, declaration_id, headers):
        return self._request("GET", f"/dividend-declarations/{declaration_id}",
                             headers=headers)

    def void_declaration(self, declaration_id, headers):
        return self._request("POST", f"/dividend-declarations/{declaration_id}/void",
                             {}, headers)

    def list_dividend_payments(self, headers, params=None):
        return self._request("GET", "/dividend-payments", headers=headers, params=params)

    def get_dividend_payment(self, payment_id, headers):
        return self._request("GET", f"/dividend-payments/{payment_id}", headers=headers)

    def cash_payment(self, payment_id, headers):
        return self._request("POST", f"/dividend-payments/{payment_id}/cash", {}, headers)

    def mark_payment_returned(self, payment_id, headers):
        return self._request("POST", f"/dividend-payments/{payment_id}/mark-returned",
                             {}, headers)

    def reissue_payment(self, payment_id, headers):
        return self._request("POST", f"/dividend-payments/{payment_id}/reissue",
                             {}, headers)

    # ------------------------------------------------------------------
    # Legend-removal requests
    # ------------------------------------------------------------------
    def create_legend_request(self, payload, headers):
        return self._request("POST", "/legend-removal-requests", payload, headers)

    def list_legend_requests(self, headers, params=None):
        return self._request("GET", "/legend-removal-requests", headers=headers,
                             params=params)

    def get_legend_request(self, request_id, headers):
        return self._request("GET", f"/legend-removal-requests/{request_id}",
                             headers=headers)

    def submit_opinion(self, request_id, payload, headers):
        return self._request("POST",
                             f"/legend-removal-requests/{request_id}/submit-opinion",
                             payload, headers)

    def flag_legend_deficient(self, request_id, payload, headers):
        return self._request("POST",
                             f"/legend-removal-requests/{request_id}/flag-deficient",
                             payload, headers)

    def approve_legend_request(self, request_id, headers):
        return self._request("POST", f"/legend-removal-requests/{request_id}/approve",
                             {}, headers)

    def reject_legend_request(self, request_id, headers):
        return self._request("POST", f"/legend-removal-requests/{request_id}/reject",
                             {}, headers)

    # ------------------------------------------------------------------
    # Dormancy and escheatment
    # ------------------------------------------------------------------
    def scan_escheatment(self, headers):
        return self._request("POST", "/escheatment/scan", {}, headers)

    def list_escheatment_cases(self, headers, params=None):
        return self._request("GET", "/escheatment-cases", headers=headers, params=params)

    def get_escheatment_case(self, case_id, headers):
        return self._request("GET", f"/escheatment-cases/{case_id}", headers=headers)

    def send_case_notice(self, case_id, headers):
        return self._request("POST", f"/escheatment-cases/{case_id}/send-notice",
                             {}, headers)

    def report_case(self, case_id, headers):
        return self._request("POST", f"/escheatment-cases/{case_id}/report", {}, headers)

    def remit_case(self, case_id, headers):
        return self._request("POST", f"/escheatment-cases/{case_id}/remit", {}, headers)

    def reactivate_case(self, case_id, headers):
        return self._request("POST", f"/escheatment-cases/{case_id}/reactivate",
                             {}, headers)

    # ------------------------------------------------------------------
    # Shareholder inquiries
    # ------------------------------------------------------------------
    def create_inquiry(self, payload, headers):
        return self._request("POST", "/inquiries", payload, headers)

    def list_inquiries(self, headers, params=None):
        return self._request("GET", "/inquiries", headers=headers, params=params)

    def get_inquiry(self, inquiry_id, headers):
        return self._request("GET", f"/inquiries/{inquiry_id}", headers=headers)

    def claim_inquiry(self, inquiry_id, headers):
        return self._request("POST", f"/inquiries/{inquiry_id}/claim", {}, headers)

    def answer_inquiry(self, inquiry_id, payload, headers):
        return self._request("POST", f"/inquiries/{inquiry_id}/answer", payload, headers)

    def close_inquiry(self, inquiry_id, headers):
        return self._request("POST", f"/inquiries/{inquiry_id}/close", {}, headers)

    # ------------------------------------------------------------------
    # Audit chain
    # ------------------------------------------------------------------
    def list_audit_events(self, headers, params=None):
        return self._request("GET", "/audit-events", headers=headers, params=params)


api_client = ApiClient()
