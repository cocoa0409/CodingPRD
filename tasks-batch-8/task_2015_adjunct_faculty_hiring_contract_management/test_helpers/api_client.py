"""API client: one method per endpoint defined in PRD Section 4."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/adjunct-hr"


class ApiClient(GenericApiClient):
    # --- test-driving clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    # --- Department ---
    def create_department(self, payload, headers):
        return self._request("POST", f"{PREFIX}/departments", payload, headers)

    def get_department(self, department_id, headers):
        return self._request("GET", f"{PREFIX}/departments/{department_id}", headers=headers)

    def list_departments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/departments", headers=headers, params=params)

    def patch_department(self, department_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/departments/{department_id}", payload, headers)

    # --- TermConfig ---
    def create_term(self, payload, headers):
        return self._request("POST", f"{PREFIX}/terms", payload, headers)

    def get_term(self, term_id, headers):
        return self._request("GET", f"{PREFIX}/terms/{term_id}", headers=headers)

    def list_terms(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/terms", headers=headers, params=params)

    def open_term(self, term_id, headers):
        return self._request("POST", f"{PREFIX}/terms/{term_id}/open", {}, headers)

    def rollover_term(self, term_id, headers):
        return self._request("POST", f"{PREFIX}/terms/{term_id}/rollover", {}, headers)

    # --- RateSchedule ---
    def create_rate_schedule(self, payload, headers):
        return self._request("POST", f"{PREFIX}/rate-schedules", payload, headers)

    def get_rate_schedule(self, schedule_id, headers):
        return self._request("GET", f"{PREFIX}/rate-schedules/{schedule_id}", headers=headers)

    def list_rate_schedules(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/rate-schedules", headers=headers, params=params)

    def publish_rate_schedule(self, schedule_id, headers):
        return self._request("POST", f"{PREFIX}/rate-schedules/{schedule_id}/publish", {}, headers)

    def retire_rate_schedule(self, schedule_id, headers):
        return self._request("POST", f"{PREFIX}/rate-schedules/{schedule_id}/retire", {}, headers)

    # --- AdjunctPoolPosting ---
    def create_posting(self, payload, headers):
        return self._request("POST", f"{PREFIX}/postings", payload, headers)

    def get_posting(self, posting_id, headers):
        return self._request("GET", f"{PREFIX}/postings/{posting_id}", headers=headers)

    def list_postings(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/postings", headers=headers, params=params)

    def publish_posting(self, posting_id, headers):
        return self._request("POST", f"{PREFIX}/postings/{posting_id}/publish", {}, headers)

    def suspend_posting(self, posting_id, headers):
        return self._request("POST", f"{PREFIX}/postings/{posting_id}/suspend", {}, headers)

    def resume_posting(self, posting_id, headers):
        return self._request("POST", f"{PREFIX}/postings/{posting_id}/resume", {}, headers)

    def close_posting(self, posting_id, headers):
        return self._request("POST", f"{PREFIX}/postings/{posting_id}/close", {}, headers)

    def archive_posting(self, posting_id, headers):
        return self._request("POST", f"{PREFIX}/postings/{posting_id}/archive", {}, headers)

    def list_posting_applications(self, posting_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/postings/{posting_id}/applications", headers=headers, params=params)

    # --- AdjunctApplication ---
    def create_application(self, payload, headers):
        return self._request("POST", f"{PREFIX}/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"{PREFIX}/applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/applications", headers=headers, params=params)

    def start_review(self, application_id, headers):
        return self._request("POST", f"{PREFIX}/applications/{application_id}/start-review", {}, headers)

    def return_for_revision(self, application_id, headers):
        return self._request("POST", f"{PREFIX}/applications/{application_id}/return-for-revision", {}, headers)

    def resubmit_application(self, application_id, headers):
        return self._request("POST", f"{PREFIX}/applications/{application_id}/resubmit", {}, headers)

    def approve_application(self, application_id, headers):
        return self._request("POST", f"{PREFIX}/applications/{application_id}/approve", {}, headers)

    def reject_application(self, application_id, headers):
        return self._request("POST", f"{PREFIX}/applications/{application_id}/reject", {}, headers)

    def withdraw_application(self, application_id, headers):
        return self._request("POST", f"{PREFIX}/applications/{application_id}/withdraw", {}, headers)

    def list_application_credentials(self, application_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/applications/{application_id}/credentials", headers=headers, params=params)

    # --- CredentialVerification ---
    def create_credential(self, payload, headers):
        return self._request("POST", f"{PREFIX}/credentials", payload, headers)

    def get_credential(self, credential_id, headers):
        return self._request("GET", f"{PREFIX}/credentials/{credential_id}", headers=headers)

    def list_credentials(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/credentials", headers=headers, params=params)

    def verify_credential(self, credential_id, headers):
        return self._request("POST", f"{PREFIX}/credentials/{credential_id}/verify", {}, headers)

    def reject_credential(self, credential_id, headers):
        return self._request("POST", f"{PREFIX}/credentials/{credential_id}/reject", {}, headers)

    # --- AdjunctFaculty ---
    def get_faculty(self, faculty_id, headers):
        return self._request("GET", f"{PREFIX}/faculty/{faculty_id}", headers=headers)

    def list_faculty(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/faculty", headers=headers, params=params)

    def get_faculty_load(self, faculty_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/faculty/{faculty_id}/load", headers=headers, params=params)

    def reinstate_compliance(self, faculty_id, headers):
        return self._request("POST", f"{PREFIX}/faculty/{faculty_id}/reinstate-compliance", {}, headers)

    def list_faculty_contracts(self, faculty_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/faculty/{faculty_id}/contracts", headers=headers, params=params)

    def list_faculty_evaluations(self, faculty_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/faculty/{faculty_id}/evaluations", headers=headers, params=params)

    # --- CourseSection ---
    def create_section(self, payload, headers):
        return self._request("POST", f"{PREFIX}/sections", payload, headers)

    def get_section(self, section_id, headers):
        return self._request("GET", f"{PREFIX}/sections/{section_id}", headers=headers)

    def list_sections(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/sections", headers=headers, params=params)

    def patch_section(self, section_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/sections/{section_id}", payload, headers)

    def cancel_section(self, section_id, payload, headers):
        return self._request("POST", f"{PREFIX}/sections/{section_id}/cancel", payload, headers)

    def complete_section(self, section_id, headers):
        return self._request("POST", f"{PREFIX}/sections/{section_id}/complete", {}, headers)

    def list_section_contracts(self, section_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/sections/{section_id}/contracts", headers=headers, params=params)

    # --- Contract ---
    def create_contract(self, payload, headers):
        return self._request("POST", f"{PREFIX}/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"{PREFIX}/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/contracts", headers=headers, params=params)

    def void_contract(self, contract_id, headers):
        return self._request("POST", f"{PREFIX}/contracts/{contract_id}/void", {}, headers)

    def list_contract_payroll_entries(self, contract_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/contracts/{contract_id}/payroll-entries", headers=headers, params=params)

    # --- PayrollPeriod / PayrollEntry ---
    def create_payroll_period(self, payload, headers):
        return self._request("POST", f"{PREFIX}/payroll-periods", payload, headers)

    def get_payroll_period(self, period_id, headers):
        return self._request("GET", f"{PREFIX}/payroll-periods/{period_id}", headers=headers)

    def list_payroll_periods(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/payroll-periods", headers=headers, params=params)

    def lock_payroll_period(self, period_id, headers):
        return self._request("POST", f"{PREFIX}/payroll-periods/{period_id}/lock", {}, headers)

    def close_payroll_period(self, period_id, headers):
        return self._request("POST", f"{PREFIX}/payroll-periods/{period_id}/close", {}, headers)

    def list_period_payroll_entries(self, period_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/payroll-periods/{period_id}/payroll-entries", headers=headers, params=params)

    def list_payroll_entries(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/payroll-entries", headers=headers, params=params)

    def get_payroll_entry(self, entry_id, headers):
        return self._request("GET", f"{PREFIX}/payroll-entries/{entry_id}", headers=headers)

    # --- Evaluation / Retention ---
    def create_evaluation(self, payload, headers):
        return self._request("POST", f"{PREFIX}/evaluations", payload, headers)

    def get_evaluation(self, evaluation_id, headers):
        return self._request("GET", f"{PREFIX}/evaluations/{evaluation_id}", headers=headers)

    def list_evaluations(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/evaluations", headers=headers, params=params)

    def create_retention_entry(self, payload, headers):
        return self._request("POST", f"{PREFIX}/retention-entries", payload, headers)

    def get_retention_entry(self, entry_id, headers):
        return self._request("GET", f"{PREFIX}/retention-entries/{entry_id}", headers=headers)

    def list_retention_entries(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/retention-entries", headers=headers, params=params)

    def reappoint(self, entry_id, payload, headers):
        return self._request("POST", f"{PREFIX}/retention-entries/{entry_id}/reappoint", payload, headers)

    def mark_non_reappointed(self, entry_id, payload, headers):
        return self._request("POST", f"{PREFIX}/retention-entries/{entry_id}/mark-non-reappointed", payload, headers)


api_client = ApiClient()
