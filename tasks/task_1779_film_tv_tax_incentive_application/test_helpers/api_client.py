"""API client: one method per endpoint defined in the PRD.

All endpoints are mounted under the /api path prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Test-driving logical clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/api/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Jurisdiction programs
    # ------------------------------------------------------------------
    def create_jurisdiction_program(self, payload, headers):
        return self._request("POST", "/api/jurisdiction-programs", payload, headers)

    def list_jurisdiction_programs(self, headers, params=None):
        return self._request("GET", "/api/jurisdiction-programs", headers=headers, params=params)

    def get_jurisdiction_program(self, program_id, headers):
        return self._request("GET", f"/api/jurisdiction-programs/{program_id}", headers=headers)

    def amend_jurisdiction_program(self, program_id, payload, headers):
        return self._request("POST", f"/api/jurisdiction-programs/{program_id}/amend", payload, headers)

    def transition_jurisdiction_program(self, program_id, to_state, headers):
        return self._request("POST", f"/api/jurisdiction-programs/{program_id}/transition",
                             {"to_state": to_state}, headers)

    # ------------------------------------------------------------------
    # Production companies
    # ------------------------------------------------------------------
    def create_production_company(self, payload, headers):
        return self._request("POST", "/api/production-companies", payload, headers)

    def get_production_company(self, company_id, headers):
        return self._request("GET", f"/api/production-companies/{company_id}", headers=headers)

    # ------------------------------------------------------------------
    # Productions
    # ------------------------------------------------------------------
    def create_production(self, payload, headers):
        return self._request("POST", "/api/productions", payload, headers)

    def list_productions(self, headers, params=None):
        return self._request("GET", "/api/productions", headers=headers, params=params)

    def get_production(self, production_id, headers):
        return self._request("GET", f"/api/productions/{production_id}", headers=headers)

    # ------------------------------------------------------------------
    # Credit buyers
    # ------------------------------------------------------------------
    def create_credit_buyer(self, payload, headers):
        return self._request("POST", "/api/credit-buyers", payload, headers)

    def get_credit_buyer(self, buyer_id, headers):
        return self._request("GET", f"/api/credit-buyers/{buyer_id}", headers=headers)

    # ------------------------------------------------------------------
    # Incentive applications
    # ------------------------------------------------------------------
    def create_application(self, payload, headers):
        return self._request("POST", "/api/applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/api/applications", headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/api/applications/{application_id}", headers=headers)

    def submit_application(self, application_id, headers):
        return self._request("POST", f"/api/applications/{application_id}/submit", {}, headers)

    def withdraw_application(self, application_id, headers):
        return self._request("POST", f"/api/applications/{application_id}/withdraw", {}, headers)

    def claim_review(self, application_id, headers):
        return self._request("POST", f"/api/applications/{application_id}/claim-review", {}, headers)

    def request_corrections(self, application_id, headers, notes=None):
        payload = {} if notes is None else {"notes": notes}
        return self._request("POST", f"/api/applications/{application_id}/request-corrections",
                             payload, headers)

    def resubmit_application(self, application_id, headers):
        return self._request("POST", f"/api/applications/{application_id}/resubmit", {}, headers)

    def approve_application(self, application_id, headers):
        return self._request("POST", f"/api/applications/{application_id}/approve", {}, headers)

    def deny_application(self, application_id, headers, reason=None):
        payload = {} if reason is None else {"reason": reason}
        return self._request("POST", f"/api/applications/{application_id}/deny", payload, headers)

    def get_credit_estimate(self, application_id, headers, params=None):
        return self._request("GET", f"/api/applications/{application_id}/credit-estimate",
                             headers=headers, params=params)

    def get_cashflow_projection(self, application_id, headers, params=None):
        return self._request("GET", f"/api/applications/{application_id}/cashflow-projection",
                             headers=headers, params=params)

    def issue_credit(self, application_id, headers):
        return self._request("POST", f"/api/applications/{application_id}/issue-credit", {}, headers)

    # ------------------------------------------------------------------
    # Vendors
    # ------------------------------------------------------------------
    def create_vendor(self, payload, headers):
        return self._request("POST", "/api/vendors", payload, headers)

    def list_vendors(self, headers, params=None):
        return self._request("GET", "/api/vendors", headers=headers, params=params)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/api/vendors/{vendor_id}", headers=headers)

    def review_vendor_residency(self, vendor_id, payload, headers):
        return self._request("POST", f"/api/vendors/{vendor_id}/review-residency", payload, headers)

    # ------------------------------------------------------------------
    # Spend entries
    # ------------------------------------------------------------------
    def create_spend_entry(self, payload, headers):
        return self._request("POST", "/api/spend-entries", payload, headers)

    def list_spend_entries(self, headers, params=None):
        return self._request("GET", "/api/spend-entries", headers=headers, params=params)

    def get_spend_entry(self, entry_id, headers):
        return self._request("GET", f"/api/spend-entries/{entry_id}", headers=headers)

    def review_spend_entry(self, entry_id, payload, headers):
        return self._request("POST", f"/api/spend-entries/{entry_id}/review", payload, headers)

    # ------------------------------------------------------------------
    # Audit packages
    # ------------------------------------------------------------------
    def create_audit_package(self, payload, headers):
        return self._request("POST", "/api/audit-packages", payload, headers)

    def list_audit_packages(self, headers, params=None):
        return self._request("GET", "/api/audit-packages", headers=headers, params=params)

    def get_audit_package(self, package_id, headers):
        return self._request("GET", f"/api/audit-packages/{package_id}", headers=headers)

    def submit_audit_draft(self, package_id, documentation_complete, headers):
        return self._request("POST", f"/api/audit-packages/{package_id}/submit-draft",
                             {"documentation_complete": documentation_complete}, headers)

    def raise_audit_exceptions(self, package_id, exception_notes, headers):
        return self._request("POST", f"/api/audit-packages/{package_id}/raise-exceptions",
                             {"exception_notes": exception_notes}, headers)

    def attest_audit_package(self, package_id, payload, headers):
        return self._request("POST", f"/api/audit-packages/{package_id}/attest", payload, headers)

    def decide_audit_package(self, package_id, payload, headers):
        return self._request("POST", f"/api/audit-packages/{package_id}/decision", payload, headers)

    # ------------------------------------------------------------------
    # Credit certificates
    # ------------------------------------------------------------------
    def list_certificates(self, headers, params=None):
        return self._request("GET", "/api/certificates", headers=headers, params=params)

    def get_certificate(self, certificate_id, headers):
        return self._request("GET", f"/api/certificates/{certificate_id}", headers=headers)

    def redeem_certificate(self, certificate_id, redeem_amount_cents, headers):
        return self._request("POST", f"/api/certificates/{certificate_id}/redeem",
                             {"redeem_amount_cents": redeem_amount_cents}, headers)

    # ------------------------------------------------------------------
    # Credit transfers
    # ------------------------------------------------------------------
    def create_transfer(self, payload, headers):
        return self._request("POST", "/api/transfers", payload, headers)

    def list_transfers(self, headers, params=None):
        return self._request("GET", "/api/transfers", headers=headers, params=params)

    def get_transfer(self, transfer_id, headers):
        return self._request("GET", f"/api/transfers/{transfer_id}", headers=headers)

    def counter_transfer(self, transfer_id, new_price_cents, headers):
        return self._request("POST", f"/api/transfers/{transfer_id}/counter",
                             {"new_price_cents": new_price_cents}, headers)

    def accept_transfer(self, transfer_id, headers):
        return self._request("POST", f"/api/transfers/{transfer_id}/accept", {}, headers)

    def settle_transfer(self, transfer_id, headers):
        return self._request("POST", f"/api/transfers/{transfer_id}/settle", {}, headers)

    def cancel_transfer(self, transfer_id, headers, cancel_reason=None):
        payload = {} if cancel_reason is None else {"cancel_reason": cancel_reason}
        return self._request("POST", f"/api/transfers/{transfer_id}/cancel", payload, headers)

    # ------------------------------------------------------------------
    # Clawback cases
    # ------------------------------------------------------------------
    def create_clawback_case(self, payload, headers):
        return self._request("POST", "/api/clawback-cases", payload, headers)

    def list_clawback_cases(self, headers, params=None):
        return self._request("GET", "/api/clawback-cases", headers=headers, params=params)

    def get_clawback_case(self, case_id, headers):
        return self._request("GET", f"/api/clawback-cases/{case_id}", headers=headers)

    def send_clawback_notice(self, case_id, headers):
        return self._request("POST", f"/api/clawback-cases/{case_id}/send-notice", {}, headers)

    def appeal_clawback_case(self, case_id, headers, appeal_grounds=None):
        payload = {} if appeal_grounds is None else {"appeal_grounds": appeal_grounds}
        return self._request("POST", f"/api/clawback-cases/{case_id}/appeal", payload, headers)

    def resolve_clawback_case(self, case_id, payload, headers):
        return self._request("POST", f"/api/clawback-cases/{case_id}/resolve", payload, headers)


api_client = ApiClient()
