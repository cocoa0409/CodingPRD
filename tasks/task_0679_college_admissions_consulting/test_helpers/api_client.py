"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------- Counselor ----------
    def create_counselor(self, payload, headers):
        return self._request("POST", "/counselors", payload, headers)

    def get_counselor(self, counselor_id, headers):
        return self._request("GET", f"/counselors/{counselor_id}", headers=headers)

    # ---------- Student ----------
    def create_student(self, payload, headers):
        return self._request("POST", "/students", payload, headers)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/students/{student_id}", headers=headers)

    def list_students(self, headers, params=None):
        return self._request("GET", "/students", headers=headers, params=params)

    def transition_student(self, student_id, payload, headers):
        return self._request("POST", f"/students/{student_id}/transition", payload, headers)

    # ---------- EngagementContract ----------
    def create_contract(self, payload, headers):
        return self._request("POST", "/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/contracts", headers=headers, params=params)

    def activate_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/activate", payload, headers)

    def close_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/close", headers=headers)

    def void_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/void", headers=headers)

    # ---------- BillingEntry ----------
    def create_billing_entry(self, payload, headers):
        return self._request("POST", "/billing-entries", payload, headers)

    def get_billing_entry(self, entry_id, headers):
        return self._request("GET", f"/billing-entries/{entry_id}", headers=headers)

    def list_billing_entries(self, headers, params=None):
        return self._request("GET", "/billing-entries", headers=headers, params=params)

    # ---------- SchoolListItem ----------
    def create_school_list_item(self, payload, headers):
        return self._request("POST", "/school-list-items", payload, headers)

    def get_school_list_item(self, item_id, headers):
        return self._request("GET", f"/school-list-items/{item_id}", headers=headers)

    def list_school_list_items(self, headers, params=None):
        return self._request("GET", "/school-list-items", headers=headers, params=params)

    def select_school_list_item(self, item_id, payload, headers):
        return self._request("POST", f"/school-list-items/{item_id}/select", payload, headers)

    def drop_school_list_item(self, item_id, headers):
        return self._request("POST", f"/school-list-items/{item_id}/drop", headers=headers)

    # ---------- Application ----------
    def create_application(self, payload, headers):
        return self._request("POST", "/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def start_prep_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/start-prep", headers=headers)

    def mark_ready_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/mark-ready", headers=headers)

    def submit_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/submit", headers=headers)

    def record_decision(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/record-decision", payload, headers)

    def appeal_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/appeal", headers=headers)

    # ---------- ApplicationTask ----------
    def create_application_task(self, payload, headers):
        return self._request("POST", "/application-tasks", payload, headers)

    def get_application_task(self, task_id, headers):
        return self._request("GET", f"/application-tasks/{task_id}", headers=headers)

    def list_application_tasks(self, headers, params=None):
        return self._request("GET", "/application-tasks", headers=headers, params=params)

    def transition_application_task(self, task_id, payload, headers):
        return self._request("POST", f"/application-tasks/{task_id}/transition", payload, headers)

    # ---------- Essay ----------
    def create_essay(self, payload, headers):
        return self._request("POST", "/essays", payload, headers)

    def get_essay(self, essay_id, headers):
        return self._request("GET", f"/essays/{essay_id}", headers=headers)

    def list_essays(self, headers, params=None):
        return self._request("GET", "/essays", headers=headers, params=params)

    def submit_essay_version(self, essay_id, payload, headers):
        return self._request("POST", f"/essays/{essay_id}/submit-version", payload, headers)

    def request_revision_essay(self, essay_id, headers):
        return self._request("POST", f"/essays/{essay_id}/request-revision", headers=headers)

    def resume_drafting_essay(self, essay_id, headers):
        return self._request("POST", f"/essays/{essay_id}/resume-drafting", headers=headers)

    def approve_essay(self, essay_id, headers):
        return self._request("POST", f"/essays/{essay_id}/approve", headers=headers)

    def abandon_essay(self, essay_id, headers):
        return self._request("POST", f"/essays/{essay_id}/abandon", headers=headers)

    # ---------- EssayVersion ----------
    def get_essay_version(self, version_id, headers):
        return self._request("GET", f"/essay-versions/{version_id}", headers=headers)

    def list_essay_versions(self, headers, params=None):
        return self._request("GET", "/essay-versions", headers=headers, params=params)

    # ---------- RecommendationRequest ----------
    def create_recommendation(self, payload, headers):
        return self._request("POST", "/recommendations", payload, headers)

    def get_recommendation(self, rec_id, headers):
        return self._request("GET", f"/recommendations/{rec_id}", headers=headers)

    def list_recommendations(self, headers, params=None):
        return self._request("GET", "/recommendations", headers=headers, params=params)

    def transition_recommendation(self, rec_id, payload, headers):
        return self._request("POST", f"/recommendations/{rec_id}/transition", payload, headers)

    # ---------- ActivityEntry ----------
    def create_activity(self, payload, headers):
        return self._request("POST", "/activities", payload, headers)

    def get_activity(self, activity_id, headers):
        return self._request("GET", f"/activities/{activity_id}", headers=headers)

    def list_activities(self, headers, params=None):
        return self._request("GET", "/activities", headers=headers, params=params)

    # ---------- ScholarshipAward ----------
    def create_scholarship(self, payload, headers):
        return self._request("POST", "/scholarships", payload, headers)

    def get_scholarship(self, award_id, headers):
        return self._request("GET", f"/scholarships/{award_id}", headers=headers)

    def list_scholarships(self, headers, params=None):
        return self._request("GET", "/scholarships", headers=headers, params=params)

    def transition_scholarship(self, award_id, payload, headers):
        return self._request("POST", f"/scholarships/{award_id}/transition", payload, headers)

    # ---------- Appointment ----------
    def create_appointment(self, payload, headers):
        return self._request("POST", "/appointments", payload, headers)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/appointments/{appointment_id}", headers=headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/appointments", headers=headers, params=params)

    def complete_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/complete", headers=headers)

    def cancel_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/cancel", headers=headers)

    # ---------- Logical clock (test-driving) ----------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
