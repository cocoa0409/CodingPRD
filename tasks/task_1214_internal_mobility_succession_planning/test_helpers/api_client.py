"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Employees -----------------------------------------------------------
    def create_employee(self, payload, headers):
        return self._request("POST", "/talent/employees", payload, headers)

    def list_employees(self, headers, params=None):
        return self._request("GET", "/talent/employees", headers=headers, params=params)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"/talent/employees/{employee_id}", headers=headers)

    def terminate_employee(self, employee_id, headers):
        return self._request("POST", f"/talent/employees/{employee_id}/terminate", {}, headers)

    # --- Critical roles --------------------------------------------------------
    def create_critical_role(self, payload, headers):
        return self._request("POST", "/talent/critical-roles", payload, headers)

    def list_critical_roles(self, headers, params=None):
        return self._request("GET", "/talent/critical-roles", headers=headers, params=params)

    def get_critical_role(self, role_id, headers):
        return self._request("GET", f"/talent/critical-roles/{role_id}", headers=headers)

    def patch_critical_role(self, role_id, payload, headers):
        return self._request("PATCH", f"/talent/critical-roles/{role_id}", payload, headers)

    def activate_critical_role(self, role_id, payload, headers):
        return self._request("POST", f"/talent/critical-roles/{role_id}/activate", payload, headers)

    def retire_critical_role(self, role_id, headers):
        return self._request("POST", f"/talent/critical-roles/{role_id}/retire", {}, headers)

    # --- Successor entries -------------------------------------------------------
    def create_successor(self, role_id, payload, headers):
        return self._request("POST", f"/talent/critical-roles/{role_id}/successors", payload, headers)

    def list_successors(self, headers, params=None):
        return self._request("GET", "/talent/successors", headers=headers, params=params)

    def get_successor(self, entry_id, headers):
        return self._request("GET", f"/talent/successors/{entry_id}", headers=headers)

    def patch_successor(self, entry_id, payload, headers):
        return self._request("PATCH", f"/talent/successors/{entry_id}", payload, headers)

    def remove_successor(self, entry_id, headers):
        return self._request("POST", f"/talent/successors/{entry_id}/remove", {}, headers)

    # --- Development plans ---------------------------------------------------------
    def create_development_plan(self, entry_id, payload, headers):
        return self._request("POST", f"/talent/successors/{entry_id}/development-plan", payload, headers)

    def get_development_plan(self, entry_id, headers):
        return self._request("GET", f"/talent/successors/{entry_id}/development-plan", headers=headers)

    def patch_development_plan(self, plan_id, payload, headers):
        return self._request("PATCH", f"/talent/development-plans/{plan_id}", payload, headers)

    # --- Vacancies -------------------------------------------------------------------
    def list_vacancies(self, headers, params=None):
        return self._request("GET", "/talent/vacancies", headers=headers, params=params)

    def get_vacancy(self, vacancy_id, headers):
        return self._request("GET", f"/talent/vacancies/{vacancy_id}", headers=headers)

    def fill_vacancy_from_slate(self, vacancy_id, headers):
        return self._request("POST", f"/talent/vacancies/{vacancy_id}/fill-from-slate", {}, headers)

    def close_vacancy(self, vacancy_id, payload, headers):
        return self._request("POST", f"/talent/vacancies/{vacancy_id}/close", payload, headers)

    # --- Internal postings --------------------------------------------------------------
    def create_posting(self, vacancy_id, payload, headers):
        return self._request("POST", f"/talent/vacancies/{vacancy_id}/postings", payload, headers)

    def list_postings(self, headers, params=None):
        return self._request("GET", "/talent/postings", headers=headers, params=params)

    def get_posting(self, posting_id, headers):
        return self._request("GET", f"/talent/postings/{posting_id}", headers=headers)

    def publish_posting(self, posting_id, headers):
        return self._request("POST", f"/talent/postings/{posting_id}/publish", {}, headers)

    def close_posting(self, posting_id, headers):
        return self._request("POST", f"/talent/postings/{posting_id}/close", {}, headers)

    # --- Posting applications --------------------------------------------------------------
    def create_application(self, posting_id, headers, payload=None):
        return self._request("POST", f"/talent/postings/{posting_id}/applications", payload or {}, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/talent/applications", headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/talent/applications/{application_id}", headers=headers)

    def consent_application(self, application_id, headers):
        return self._request("POST", f"/talent/applications/{application_id}/consent", {}, headers)

    def hold_application(self, application_id, payload, headers):
        return self._request("POST", f"/talent/applications/{application_id}/hold", payload, headers)

    def release_hold_application(self, application_id, headers):
        return self._request("POST", f"/talent/applications/{application_id}/release-hold", {}, headers)

    def withdraw_application(self, application_id, headers):
        return self._request("POST", f"/talent/applications/{application_id}/withdraw", {}, headers)

    def advance_application(self, application_id, payload, headers):
        return self._request("POST", f"/talent/applications/{application_id}/advance", payload, headers)

    def respond_offer(self, application_id, payload, headers):
        return self._request("POST", f"/talent/applications/{application_id}/respond-offer", payload, headers)

    def process_consent_deadlines(self, headers):
        return self._request("POST", "/talent/consent-deadlines/process", {}, headers)

    # --- Calibration sessions / entries --------------------------------------------------------
    def create_calibration_session(self, payload, headers):
        return self._request("POST", "/talent/calibration-sessions", payload, headers)

    def list_calibration_sessions(self, headers, params=None):
        return self._request("GET", "/talent/calibration-sessions", headers=headers, params=params)

    def get_calibration_session(self, session_id, headers):
        return self._request("GET", f"/talent/calibration-sessions/{session_id}", headers=headers)

    def start_calibration_session(self, session_id, headers):
        return self._request("POST", f"/talent/calibration-sessions/{session_id}/start", {}, headers)

    def finalize_calibration_session(self, session_id, headers):
        return self._request("POST", f"/talent/calibration-sessions/{session_id}/finalize", {}, headers)

    def create_calibration_entry(self, session_id, payload, headers):
        return self._request("POST", f"/talent/calibration-sessions/{session_id}/entries", payload, headers)

    def list_calibration_entries(self, headers, params=None):
        return self._request("GET", "/talent/calibration-entries", headers=headers, params=params)

    def get_calibration_entry(self, entry_id, headers):
        return self._request("GET", f"/talent/calibration-entries/{entry_id}", headers=headers)

    def challenge_calibration_entry(self, entry_id, headers):
        return self._request("POST", f"/talent/calibration-entries/{entry_id}/challenge", {}, headers)

    def revise_calibration_entry(self, entry_id, payload, headers):
        return self._request("POST", f"/talent/calibration-entries/{entry_id}/revise", payload, headers)

    def ratify_calibration_entry(self, entry_id, payload, headers):
        return self._request("POST", f"/talent/calibration-entries/{entry_id}/ratify", payload, headers)

    # --- HiPo program cycles / nominations ---------------------------------------------------------
    def create_hipo_cycle(self, payload, headers):
        return self._request("POST", "/talent/hipo-cycles", payload, headers)

    def list_hipo_cycles(self, headers, params=None):
        return self._request("GET", "/talent/hipo-cycles", headers=headers, params=params)

    def get_hipo_cycle(self, cycle_id, headers):
        return self._request("GET", f"/talent/hipo-cycles/{cycle_id}", headers=headers)

    def close_hipo_cycle(self, cycle_id, headers):
        return self._request("POST", f"/talent/hipo-cycles/{cycle_id}/close", {}, headers)

    def create_nomination(self, cycle_id, payload, headers):
        return self._request("POST", f"/talent/hipo-cycles/{cycle_id}/nominations", payload, headers)

    def list_nominations(self, headers, params=None):
        return self._request("GET", "/talent/hipo-nominations", headers=headers, params=params)

    def get_nomination(self, nomination_id, headers):
        return self._request("GET", f"/talent/hipo-nominations/{nomination_id}", headers=headers)

    def endorse_nomination(self, nomination_id, headers):
        return self._request("POST", f"/talent/hipo-nominations/{nomination_id}/endorse", {}, headers)

    def reject_nomination(self, nomination_id, headers):
        return self._request("POST", f"/talent/hipo-nominations/{nomination_id}/reject", {}, headers)

    def enroll_nomination(self, nomination_id, headers):
        return self._request("POST", f"/talent/hipo-nominations/{nomination_id}/enroll", {}, headers)

    def remove_nomination(self, nomination_id, headers):
        return self._request("POST", f"/talent/hipo-nominations/{nomination_id}/remove", {}, headers)

    def start_review_nomination(self, nomination_id, headers):
        return self._request("POST", f"/talent/hipo-nominations/{nomination_id}/start-review", {}, headers)

    def complete_review_nomination(self, nomination_id, payload, headers):
        return self._request("POST", f"/talent/hipo-nominations/{nomination_id}/complete-review", payload, headers)

    # --- Retention assessments -----------------------------------------------------------------------
    def create_retention_assessment(self, employee_id, payload, headers):
        return self._request("POST", f"/talent/employees/{employee_id}/retention-assessments", payload, headers)

    def list_retention_assessments(self, headers, params=None):
        return self._request("GET", "/talent/retention-assessments", headers=headers, params=params)

    def get_retention_assessment(self, assessment_id, headers):
        return self._request("GET", f"/talent/retention-assessments/{assessment_id}", headers=headers)

    def plan_action_retention_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"/talent/retention-assessments/{assessment_id}/plan-action", payload, headers)

    def escalate_retention_assessment(self, assessment_id, headers):
        return self._request("POST", f"/talent/retention-assessments/{assessment_id}/escalate", {}, headers)

    def close_retention_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"/talent/retention-assessments/{assessment_id}/close", payload, headers)

    # --- Diversity snapshots ----------------------------------------------------------------------------
    def create_diversity_snapshot(self, payload, headers):
        return self._request("POST", "/talent/diversity-snapshots", payload, headers)

    def list_diversity_snapshots(self, headers, params=None):
        return self._request("GET", "/talent/diversity-snapshots", headers=headers, params=params)

    def get_diversity_snapshot(self, snapshot_id, headers):
        return self._request("GET", f"/talent/diversity-snapshots/{snapshot_id}", headers=headers)

    # --- Logical clock -------------------------------------------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/talent/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
