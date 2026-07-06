"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clock (test-driving) ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/training/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ---- Program ----
    def create_program(self, payload, headers):
        return self._request("POST", "/training/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/training/programs/{program_id}", headers=headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/training/programs", headers=headers, params=params)

    def retire_program(self, program_id, headers):
        return self._request("POST", f"/training/programs/{program_id}/retire", {}, headers)

    # ---- ProgramVersion ----
    def create_program_version(self, payload, headers):
        return self._request("POST", "/training/program-versions", payload, headers)

    def get_program_version(self, pv_id, headers):
        return self._request("GET", f"/training/program-versions/{pv_id}", headers=headers)

    def list_program_versions(self, headers, params=None):
        return self._request("GET", "/training/program-versions", headers=headers, params=params)

    def submit_program_version(self, pv_id, headers):
        return self._request("POST", f"/training/program-versions/{pv_id}/submit", {}, headers)

    def request_changes_program_version(self, pv_id, headers):
        return self._request("POST", f"/training/program-versions/{pv_id}/request-changes", {}, headers)

    def approve_program_version(self, pv_id, headers):
        return self._request("POST", f"/training/program-versions/{pv_id}/approve", {}, headers)

    # ---- Facilitator ----
    def create_facilitator(self, payload, headers):
        return self._request("POST", "/training/facilitators", payload, headers)

    def get_facilitator(self, fac_id, headers):
        return self._request("GET", f"/training/facilitators/{fac_id}", headers=headers)

    def list_facilitators(self, headers, params=None):
        return self._request("GET", "/training/facilitators", headers=headers, params=params)

    def suspend_facilitator(self, fac_id, headers):
        return self._request("POST", f"/training/facilitators/{fac_id}/suspend", {}, headers)

    # ---- EnterpriseContract ----
    def create_contract(self, payload, headers):
        return self._request("POST", "/training/contracts", payload, headers)

    def get_contract(self, ctr_id, headers):
        return self._request("GET", f"/training/contracts/{ctr_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/training/contracts", headers=headers, params=params)

    def close_contract(self, ctr_id, headers):
        return self._request("POST", f"/training/contracts/{ctr_id}/close", {}, headers)

    # ---- Cohort ----
    def create_cohort(self, payload, headers):
        return self._request("POST", "/training/cohorts", payload, headers)

    def get_cohort(self, coh_id, headers):
        return self._request("GET", f"/training/cohorts/{coh_id}", headers=headers)

    def list_cohorts(self, headers, params=None):
        return self._request("GET", "/training/cohorts", headers=headers, params=params)

    def open_cohort(self, coh_id, headers):
        return self._request("POST", f"/training/cohorts/{coh_id}/open", {}, headers)

    def lock_cohort(self, coh_id, expected_cohort_version, headers):
        return self._request(
            "POST", f"/training/cohorts/{coh_id}/lock",
            {"expected_cohort_version": expected_cohort_version}, headers,
        )

    def start_cohort(self, coh_id, headers):
        return self._request("POST", f"/training/cohorts/{coh_id}/start", {}, headers)

    def deliver_cohort(self, coh_id, headers):
        return self._request("POST", f"/training/cohorts/{coh_id}/deliver", {}, headers)

    def close_cohort(self, coh_id, headers):
        return self._request("POST", f"/training/cohorts/{coh_id}/close", {}, headers)

    def cancel_cohort(self, coh_id, headers):
        return self._request("POST", f"/training/cohorts/{coh_id}/cancel", {}, headers)

    # ---- Session ----
    def create_session(self, coh_id, payload, headers):
        return self._request("POST", f"/training/cohorts/{coh_id}/sessions", payload, headers)

    def list_cohort_sessions(self, coh_id, headers, params=None):
        return self._request("GET", f"/training/cohorts/{coh_id}/sessions", headers=headers, params=params)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/training/sessions/{session_id}", headers=headers)

    # ---- SessionAssignment ----
    def create_session_assignment(self, session_id, payload, headers):
        return self._request("POST", f"/training/sessions/{session_id}/assignments", payload, headers)

    def list_session_assignments(self, session_id, headers, params=None):
        return self._request("GET", f"/training/sessions/{session_id}/assignments", headers=headers, params=params)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/training/assignments", headers=headers, params=params)

    # ---- Registration ----
    def create_registration(self, coh_id, payload, headers):
        return self._request("POST", f"/training/cohorts/{coh_id}/registrations", payload, headers)

    def list_cohort_registrations(self, coh_id, headers, params=None):
        return self._request("GET", f"/training/cohorts/{coh_id}/registrations", headers=headers, params=params)

    def get_registration(self, reg_id, headers):
        return self._request("GET", f"/training/registrations/{reg_id}", headers=headers)

    def list_registrations(self, headers, params=None):
        return self._request("GET", "/training/registrations", headers=headers, params=params)

    def confirm_registration(self, reg_id, headers):
        return self._request("POST", f"/training/registrations/{reg_id}/confirm", {}, headers)

    def withdraw_registration(self, reg_id, headers):
        return self._request("POST", f"/training/registrations/{reg_id}/withdraw", {}, headers)

    def mark_attendance(self, reg_id, headers):
        return self._request("POST", f"/training/registrations/{reg_id}/mark-attendance", {}, headers)

    # ---- Assessment ----
    def create_assessment(self, reg_id, payload, headers):
        return self._request("POST", f"/training/registrations/{reg_id}/assessments", payload, headers)

    def list_assessments(self, reg_id, headers, params=None):
        return self._request("GET", f"/training/registrations/{reg_id}/assessments", headers=headers, params=params)

    def get_assessment(self, asm_id, headers):
        return self._request("GET", f"/training/assessments/{asm_id}", headers=headers)

    def void_assessment(self, asm_id, headers):
        return self._request("POST", f"/training/assessments/{asm_id}/void", {}, headers)

    # ---- Certificate ----
    def issue_certificate(self, reg_id, payload, headers):
        return self._request("POST", f"/training/registrations/{reg_id}/certificate", payload, headers)

    def list_registration_certificates(self, reg_id, headers, params=None):
        return self._request("GET", f"/training/registrations/{reg_id}/certificates", headers=headers, params=params)

    def get_certificate(self, cert_id, headers):
        return self._request("GET", f"/training/certificates/{cert_id}", headers=headers)

    def list_certificates(self, headers, params=None):
        return self._request("GET", "/training/certificates", headers=headers, params=params)

    def revoke_certificate(self, cert_id, headers):
        return self._request("POST", f"/training/certificates/{cert_id}/revoke", {}, headers)

    # ---- Invoice ----
    def list_cohort_invoices(self, coh_id, headers, params=None):
        return self._request("GET", f"/training/cohorts/{coh_id}/invoices", headers=headers, params=params)

    def get_invoice(self, inv_id, headers):
        return self._request("GET", f"/training/invoices/{inv_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/training/invoices", headers=headers, params=params)

    # ---- Evaluation ----
    def create_evaluation(self, reg_id, payload, headers):
        return self._request("POST", f"/training/registrations/{reg_id}/evaluation", payload, headers)

    def list_registration_evaluations(self, reg_id, headers, params=None):
        return self._request("GET", f"/training/registrations/{reg_id}/evaluations", headers=headers, params=params)

    def list_evaluations(self, headers, params=None):
        return self._request("GET", "/training/evaluations", headers=headers, params=params)


api_client = ApiClient()
