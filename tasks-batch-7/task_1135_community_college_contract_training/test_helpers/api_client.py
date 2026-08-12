"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/ct/_clock/set_current_utc", payload, headers)

    # --- Employer ---
    def create_employer(self, payload, headers):
        return self._request("POST", "/ct/employers", payload, headers)

    def get_employer(self, employer_id, headers):
        return self._request("GET", f"/ct/employers/{employer_id}", headers=headers)

    def list_employer_needs_assessments(self, employer_id, headers, params=None):
        return self._request("GET", f"/ct/employers/{employer_id}/needs-assessments", headers=headers, params=params)

    def list_employer_training_agreements(self, employer_id, headers, params=None):
        return self._request("GET", f"/ct/employers/{employer_id}/training-agreements", headers=headers, params=params)

    # --- NeedsAssessment ---
    def create_needs_assessment(self, employer_id, payload, headers):
        return self._request("POST", f"/ct/employers/{employer_id}/needs-assessments", payload, headers)

    def get_needs_assessment(self, assessment_id, headers):
        return self._request("GET", f"/ct/needs-assessments/{assessment_id}", headers=headers)

    def submit_needs_assessment(self, assessment_id, headers):
        return self._request("POST", f"/ct/needs-assessments/{assessment_id}/submit", {}, headers)

    def approve_needs_assessment(self, assessment_id, headers):
        return self._request("POST", f"/ct/needs-assessments/{assessment_id}/approve", {}, headers)

    def request_revision_needs_assessment(self, assessment_id, headers, payload=None):
        return self._request("POST", f"/ct/needs-assessments/{assessment_id}/request_revision", payload or {}, headers)

    # --- TrainingAgreement ---
    def create_training_agreement(self, employer_id, payload, headers):
        return self._request("POST", f"/ct/employers/{employer_id}/training-agreements", payload, headers)

    def get_training_agreement(self, agreement_id, headers):
        return self._request("GET", f"/ct/training-agreements/{agreement_id}", headers=headers)

    def list_training_agreements(self, headers, params=None):
        return self._request("GET", "/ct/training-agreements", headers=headers, params=params)

    def quote_training_agreement(self, agreement_id, headers):
        return self._request("POST", f"/ct/training-agreements/{agreement_id}/quote", {}, headers)

    def revise_training_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/ct/training-agreements/{agreement_id}/revise", payload, headers)

    def negotiate_training_agreement(self, agreement_id, headers):
        return self._request("POST", f"/ct/training-agreements/{agreement_id}/negotiate", {}, headers)

    def sign_training_agreement(self, agreement_id, headers):
        return self._request("POST", f"/ct/training-agreements/{agreement_id}/sign", {}, headers)

    def cancel_training_agreement(self, agreement_id, headers):
        return self._request("POST", f"/ct/training-agreements/{agreement_id}/cancel", {}, headers)

    def refresh_assessment_pin(self, agreement_id, headers):
        return self._request("POST", f"/ct/training-agreements/{agreement_id}/refresh_assessment_pin", {}, headers)

    def list_agreement_cohorts(self, agreement_id, headers, params=None):
        return self._request("GET", f"/ct/training-agreements/{agreement_id}/cohorts", headers=headers, params=params)

    def list_agreement_outcome_reports(self, agreement_id, headers, params=None):
        return self._request("GET", f"/ct/training-agreements/{agreement_id}/outcome-reports", headers=headers, params=params)

    # --- GrantProgram ---
    def create_grant_program(self, payload, headers):
        return self._request("POST", "/ct/grant-programs", payload, headers)

    def get_grant_program(self, program_id, headers):
        return self._request("GET", f"/ct/grant-programs/{program_id}", headers=headers)

    def suspend_grant_program(self, program_id, headers):
        return self._request("POST", f"/ct/grant-programs/{program_id}/suspend", {}, headers)

    def reopen_grant_program(self, program_id, headers):
        return self._request("POST", f"/ct/grant-programs/{program_id}/reopen", {}, headers)

    def close_grant_program(self, program_id, headers):
        return self._request("POST", f"/ct/grant-programs/{program_id}/close", {}, headers)

    # --- GrantApplication ---
    def create_grant_application(self, cohort_id, payload, headers):
        return self._request("POST", f"/ct/cohorts/{cohort_id}/grant-applications", payload, headers)

    def get_grant_application(self, application_id, headers):
        return self._request("GET", f"/ct/grant-applications/{application_id}", headers=headers)

    def list_grant_applications(self, headers, params=None):
        return self._request("GET", "/ct/grant-applications", headers=headers, params=params)

    def list_cohort_grant_applications(self, cohort_id, headers, params=None):
        return self._request("GET", f"/ct/cohorts/{cohort_id}/grant-applications", headers=headers, params=params)

    def submit_grant_application(self, application_id, headers):
        return self._request("POST", f"/ct/grant-applications/{application_id}/submit", {}, headers)

    def start_review_grant_application(self, application_id, headers):
        return self._request("POST", f"/ct/grant-applications/{application_id}/start_review", {}, headers)

    def return_grant_application(self, application_id, headers, payload=None):
        return self._request("POST", f"/ct/grant-applications/{application_id}/return", payload or {}, headers)

    def approve_grant_application(self, application_id, headers):
        return self._request("POST", f"/ct/grant-applications/{application_id}/approve", {}, headers)

    def deny_grant_application(self, application_id, headers, payload=None):
        return self._request("POST", f"/ct/grant-applications/{application_id}/deny", payload or {}, headers)

    def claim_grant_application(self, application_id, headers):
        return self._request("POST", f"/ct/grant-applications/{application_id}/claim", {}, headers)

    def mark_paid_grant_application(self, application_id, headers):
        return self._request("POST", f"/ct/grant-applications/{application_id}/mark_paid", {}, headers)

    # --- Instructor & Venue ---
    def create_instructor(self, payload, headers):
        return self._request("POST", "/ct/instructors", payload, headers)

    def get_instructor(self, instructor_id, headers):
        return self._request("GET", f"/ct/instructors/{instructor_id}", headers=headers)

    def deactivate_instructor(self, instructor_id, headers):
        return self._request("POST", f"/ct/instructors/{instructor_id}/deactivate", {}, headers)

    def reactivate_instructor(self, instructor_id, headers):
        return self._request("POST", f"/ct/instructors/{instructor_id}/reactivate", {}, headers)

    def create_venue(self, payload, headers):
        return self._request("POST", "/ct/venues", payload, headers)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/ct/venues/{venue_id}", headers=headers)

    # --- Cohort ---
    def create_cohort(self, agreement_id, payload, headers):
        return self._request("POST", f"/ct/training-agreements/{agreement_id}/cohorts", payload, headers)

    def get_cohort(self, cohort_id, headers):
        return self._request("GET", f"/ct/cohorts/{cohort_id}", headers=headers)

    def list_cohorts(self, headers, params=None):
        return self._request("GET", "/ct/cohorts", headers=headers, params=params)

    def launch_cohort(self, cohort_id, headers):
        return self._request("POST", f"/ct/cohorts/{cohort_id}/launch", {}, headers)

    def cancel_cohort(self, cohort_id, headers):
        return self._request("POST", f"/ct/cohorts/{cohort_id}/cancel", {}, headers)

    def issue_credentials(self, cohort_id, headers):
        return self._request("POST", f"/ct/cohorts/{cohort_id}/issue_credentials", {}, headers)

    def list_cohort_sessions(self, cohort_id, headers, params=None):
        return self._request("GET", f"/ct/cohorts/{cohort_id}/sessions", headers=headers, params=params)

    def list_cohort_participants(self, cohort_id, headers, params=None):
        return self._request("GET", f"/ct/cohorts/{cohort_id}/participants", headers=headers, params=params)

    def list_cohort_invoices(self, cohort_id, headers, params=None):
        return self._request("GET", f"/ct/cohorts/{cohort_id}/invoices", headers=headers, params=params)

    # --- Session ---
    def create_session(self, cohort_id, payload, headers):
        return self._request("POST", f"/ct/cohorts/{cohort_id}/sessions", payload, headers)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/ct/sessions/{session_id}", headers=headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/ct/sessions", headers=headers, params=params)

    def cancel_session(self, session_id, headers):
        return self._request("POST", f"/ct/sessions/{session_id}/cancel", {}, headers)

    def close_attendance(self, session_id, payload, headers):
        return self._request("POST", f"/ct/sessions/{session_id}/close_attendance", payload, headers)

    def list_session_instructor_assignments(self, session_id, headers, params=None):
        return self._request("GET", f"/ct/sessions/{session_id}/instructor-assignments", headers=headers, params=params)

    # --- InstructorAssignment ---
    def create_instructor_assignment(self, session_id, payload, headers):
        return self._request("POST", f"/ct/sessions/{session_id}/instructor-assignments", payload, headers)

    def get_instructor_assignment(self, assignment_id, headers):
        return self._request("GET", f"/ct/instructor-assignments/{assignment_id}", headers=headers)

    def list_instructor_assignments(self, headers, params=None):
        return self._request("GET", "/ct/instructor-assignments", headers=headers, params=params)

    def confirm_instructor_assignment(self, assignment_id, headers):
        return self._request("POST", f"/ct/instructor-assignments/{assignment_id}/confirm", {}, headers)

    def release_instructor_assignment(self, assignment_id, headers):
        return self._request("POST", f"/ct/instructor-assignments/{assignment_id}/release", {}, headers)

    # --- Participant ---
    def create_participant(self, cohort_id, payload, headers):
        return self._request("POST", f"/ct/cohorts/{cohort_id}/participants", payload, headers)

    def get_participant(self, participant_id, headers):
        return self._request("GET", f"/ct/participants/{participant_id}", headers=headers)

    def drop_participant(self, participant_id, headers):
        return self._request("POST", f"/ct/participants/{participant_id}/drop", {}, headers)

    # --- Invoice ---
    def create_invoice(self, cohort_id, payload, headers):
        return self._request("POST", f"/ct/cohorts/{cohort_id}/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/ct/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/ct/invoices", headers=headers, params=params)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/ct/invoices/{invoice_id}/issue", {}, headers)

    def mark_paid_invoice(self, invoice_id, headers):
        return self._request("POST", f"/ct/invoices/{invoice_id}/mark_paid", {}, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/ct/invoices/{invoice_id}/void", {}, headers)

    # --- OutcomeReport ---
    def create_outcome_report(self, agreement_id, payload, headers):
        return self._request("POST", f"/ct/training-agreements/{agreement_id}/outcome-reports", payload, headers)

    def get_outcome_report(self, report_id, headers):
        return self._request("GET", f"/ct/outcome-reports/{report_id}", headers=headers)

    def submit_outcome_report(self, report_id, headers):
        return self._request("POST", f"/ct/outcome-reports/{report_id}/submit", {}, headers)

    def accept_outcome_report(self, report_id, headers):
        return self._request("POST", f"/ct/outcome-reports/{report_id}/accept", {}, headers)


api_client = ApiClient()
