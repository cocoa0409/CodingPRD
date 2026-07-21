"""API client: one method per endpoint in the Down-Payment Assistance API.

All paths are under the /api/v1 prefix. Every method returns the raw
requests.Response so tests can assert status codes and envelopes.
"""
from prd_bench_local_runner.testing import GenericApiClient

P = "/api/v1"


class ApiClient(GenericApiClient):
    # ---- Program & IncomeLimit --------------------------------------------
    def create_program(self, payload, headers):
        return self._request("POST", f"{P}/programs", payload, headers)

    def close_program(self, program_id, headers):
        return self._request("POST", f"{P}/programs/{program_id}/close", {}, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"{P}/programs/{program_id}", headers=headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", f"{P}/programs", headers=headers, params=params)

    def create_income_limit(self, program_id, payload, headers):
        return self._request("POST", f"{P}/programs/{program_id}/income-limits", payload, headers)

    def list_income_limits(self, program_id, headers, params=None):
        return self._request("GET", f"{P}/programs/{program_id}/income-limits", headers=headers, params=params)

    def list_program_education_sessions(self, program_id, headers, params=None):
        return self._request("GET", f"{P}/programs/{program_id}/education-sessions", headers=headers, params=params)

    # ---- Applicant ---------------------------------------------------------
    def create_applicant(self, payload, headers=None):
        return self._request("POST", f"{P}/applicants", payload, headers)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"{P}/applicants/{applicant_id}", headers=headers)

    # ---- Property ----------------------------------------------------------
    def create_property(self, payload, headers):
        return self._request("POST", f"{P}/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"{P}/properties/{property_id}", headers=headers)

    def record_appraisal(self, property_id, payload, headers):
        return self._request("POST", f"{P}/properties/{property_id}/appraisal", payload, headers)

    # ---- Application -------------------------------------------------------
    def create_application(self, payload, headers):
        return self._request("POST", f"{P}/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"{P}/applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", f"{P}/applications", headers=headers, params=params)

    def submit_application(self, application_id, headers):
        return self._request("POST", f"{P}/applications/{application_id}/submit", {}, headers)

    def review_application(self, application_id, payload, headers):
        return self._request("POST", f"{P}/applications/{application_id}/review", payload, headers)

    def resubmit_application(self, application_id, headers):
        return self._request("POST", f"{P}/applications/{application_id}/resubmit", {}, headers)

    def withdraw_application(self, application_id, headers):
        return self._request("POST", f"{P}/applications/{application_id}/withdraw", {}, headers)

    # ---- Education: Session / Enrollment / Certificate --------------------
    def create_education_session(self, payload, headers):
        return self._request("POST", f"{P}/education-sessions", payload, headers)

    def get_education_session(self, session_id, headers):
        return self._request("GET", f"{P}/education-sessions/{session_id}", headers=headers)

    def create_enrollment(self, session_id, payload, headers):
        return self._request("POST", f"{P}/education-sessions/{session_id}/enrollments", payload, headers)

    def list_session_enrollments(self, session_id, headers, params=None):
        return self._request("GET", f"{P}/education-sessions/{session_id}/enrollments", headers=headers, params=params)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"{P}/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", f"{P}/enrollments", headers=headers, params=params)

    def attend_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"{P}/enrollments/{enrollment_id}/attend", {}, headers)

    def no_show_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"{P}/enrollments/{enrollment_id}/no-show", {}, headers)

    def cancel_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"{P}/enrollments/{enrollment_id}/cancel", {}, headers)

    def get_certificate(self, certificate_id, headers):
        return self._request("GET", f"{P}/certificates/{certificate_id}", headers=headers)

    def list_certificates(self, headers, params=None):
        return self._request("GET", f"{P}/certificates", headers=headers, params=params)

    # ---- Award -------------------------------------------------------------
    def create_award(self, application_id, payload, headers):
        return self._request("POST", f"{P}/applications/{application_id}/awards", payload, headers)

    def get_award(self, award_id, headers):
        return self._request("GET", f"{P}/awards/{award_id}", headers=headers)

    def list_awards(self, headers, params=None):
        return self._request("GET", f"{P}/awards", headers=headers, params=params)

    def approve_award(self, award_id, headers):
        return self._request("POST", f"{P}/awards/{award_id}/approve", {}, headers)

    def cancel_award(self, award_id, headers):
        return self._request("POST", f"{P}/awards/{award_id}/cancel", {}, headers)

    # ---- Funding -----------------------------------------------------------
    def create_funding_source(self, payload, headers):
        return self._request("POST", f"{P}/funding-sources", payload, headers)

    def get_funding_source(self, funding_source_id, headers):
        return self._request("GET", f"{P}/funding-sources/{funding_source_id}", headers=headers)

    def list_funding_sources(self, headers, params=None):
        return self._request("GET", f"{P}/funding-sources", headers=headers, params=params)

    def create_funding_allocation(self, payload, headers):
        return self._request("POST", f"{P}/funding-allocations", payload, headers)

    def get_funding_allocation(self, allocation_id, headers):
        return self._request("GET", f"{P}/funding-allocations/{allocation_id}", headers=headers)

    def list_funding_allocations(self, headers, params=None):
        return self._request("GET", f"{P}/funding-allocations", headers=headers, params=params)

    # ---- Closing -----------------------------------------------------------
    def schedule_closing(self, award_id, payload, headers):
        return self._request("POST", f"{P}/awards/{award_id}/closings", payload, headers)

    def get_closing(self, closing_id, headers):
        return self._request("GET", f"{P}/closings/{closing_id}", headers=headers)

    def list_closings(self, headers, params=None):
        return self._request("GET", f"{P}/closings", headers=headers, params=params)

    def closing_docs_pending(self, closing_id, headers):
        return self._request("POST", f"{P}/closings/{closing_id}/docs-pending", {}, headers)

    def complete_closing(self, closing_id, payload, headers):
        return self._request("POST", f"{P}/closings/{closing_id}/complete", payload, headers)

    def cancel_closing(self, closing_id, headers):
        return self._request("POST", f"{P}/closings/{closing_id}/cancel", {}, headers)

    # ---- Servicing ---------------------------------------------------------
    def get_servicing_account(self, servicing_id, headers):
        return self._request("GET", f"{P}/servicing-accounts/{servicing_id}", headers=headers)

    def list_servicing_accounts(self, headers, params=None):
        return self._request("GET", f"{P}/servicing-accounts", headers=headers, params=params)

    def report_sale(self, servicing_id, payload, headers):
        return self._request("POST", f"{P}/servicing-accounts/{servicing_id}/report-sale", payload, headers)

    def list_sale_events(self, servicing_id, headers, params=None):
        return self._request("GET", f"{P}/servicing-accounts/{servicing_id}/sale-events", headers=headers, params=params)

    def close_servicing(self, servicing_id, headers):
        return self._request("POST", f"{P}/servicing-accounts/{servicing_id}/close", {}, headers)

    def set_payment_status(self, servicing_id, payload, headers):
        return self._request("POST", f"{P}/servicing-accounts/{servicing_id}/payment-status", payload, headers)

    # ---- Reporting ---------------------------------------------------------
    def get_portfolio_summary(self, headers):
        return self._request("GET", f"{P}/reports/portfolio-summary", headers=headers)

    # ---- Test-driving: logical clock --------------------------------------
    def set_clock(self, to_iso8601, headers=None):
        return self._request("POST", f"{P}/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
