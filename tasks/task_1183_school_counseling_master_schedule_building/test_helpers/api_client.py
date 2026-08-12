"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Terms & posture -----------------------------------------------------
    def create_term(self, payload, headers):
        return self._request("POST", "/scheduling/terms", payload, headers)

    def list_terms(self, headers, params=None):
        return self._request("GET", "/scheduling/terms", headers=headers, params=params)

    def get_term(self, term_id, headers):
        return self._request("GET", f"/scheduling/terms/{term_id}", headers=headers)

    def close_collection(self, term_id, headers, payload=None):
        return self._request("POST", f"/scheduling/terms/{term_id}/close-collection", payload or {}, headers)

    def generate_sections(self, term_id, headers, payload=None):
        return self._request("POST", f"/scheduling/terms/{term_id}/generate-sections", payload or {}, headers)

    def publish_term(self, term_id, headers, payload=None):
        return self._request("POST", f"/scheduling/terms/{term_id}/publish", payload or {}, headers)

    def open_change_window(self, term_id, headers, payload=None):
        return self._request("POST", f"/scheduling/terms/{term_id}/open-change-window", payload or {}, headers)

    def close_change_window(self, term_id, headers, payload=None):
        return self._request("POST", f"/scheduling/terms/{term_id}/close-change-window", payload or {}, headers)

    def get_tally_preview(self, term_id, headers):
        return self._request("GET", f"/scheduling/terms/{term_id}/tally-preview", headers=headers)

    def create_rebalance_run(self, term_id, payload, headers):
        return self._request("POST", f"/scheduling/terms/{term_id}/rebalance-runs", payload, headers)

    def list_rebalance_runs(self, term_id, headers, params=None):
        return self._request("GET", f"/scheduling/terms/{term_id}/rebalance-runs", headers=headers, params=params)

    # --- Catalog ---------------------------------------------------------------
    def create_course(self, payload, headers):
        return self._request("POST", "/scheduling/courses", payload, headers)

    def list_courses(self, headers, params=None):
        return self._request("GET", "/scheduling/courses", headers=headers, params=params)

    def get_course(self, course_id, headers):
        return self._request("GET", f"/scheduling/courses/{course_id}", headers=headers)

    # --- People ------------------------------------------------------------------
    def create_counselor(self, payload, headers):
        return self._request("POST", "/scheduling/counselors", payload, headers)

    def get_counselor(self, counselor_id, headers):
        return self._request("GET", f"/scheduling/counselors/{counselor_id}", headers=headers)

    def list_counselor_students(self, counselor_id, headers, params=None):
        return self._request("GET", f"/scheduling/counselors/{counselor_id}/students", headers=headers, params=params)

    def get_counselor_utilization(self, counselor_id, headers, params=None):
        return self._request("GET", f"/scheduling/counselors/{counselor_id}/utilization", headers=headers, params=params)

    def create_teacher(self, payload, headers):
        return self._request("POST", "/scheduling/teachers", payload, headers)

    def get_teacher(self, teacher_id, headers):
        return self._request("GET", f"/scheduling/teachers/{teacher_id}", headers=headers)

    def create_qualification(self, teacher_id, payload, headers):
        return self._request("POST", f"/scheduling/teachers/{teacher_id}/qualifications", payload, headers)

    def list_teacher_qualifications(self, teacher_id, headers, params=None):
        return self._request("GET", f"/scheduling/teachers/{teacher_id}/qualifications", headers=headers, params=params)

    def create_room(self, payload, headers):
        return self._request("POST", "/scheduling/rooms", payload, headers)

    def get_room(self, room_id, headers):
        return self._request("GET", f"/scheduling/rooms/{room_id}", headers=headers)

    def create_student(self, payload, headers):
        return self._request("POST", "/scheduling/students", payload, headers)

    def list_students(self, headers, params=None):
        return self._request("GET", "/scheduling/students", headers=headers, params=params)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/scheduling/students/{student_id}", headers=headers)

    def get_student_schedule(self, student_id, headers, params=None):
        return self._request("GET", f"/scheduling/students/{student_id}/schedule", headers=headers, params=params)

    def get_student_credit_audit(self, student_id, headers, params=None):
        return self._request("GET", f"/scheduling/students/{student_id}/credit-audit", headers=headers, params=params)

    def get_student_credit_projection(self, student_id, headers, params=None):
        return self._request("GET", f"/scheduling/students/{student_id}/credit-projection", headers=headers, params=params)

    # --- Course requests -----------------------------------------------------------
    def create_course_request(self, payload, headers):
        return self._request("POST", "/scheduling/course-requests", payload, headers)

    def list_course_requests(self, headers, params=None):
        return self._request("GET", "/scheduling/course-requests", headers=headers, params=params)

    def get_course_request(self, request_id, headers):
        return self._request("GET", f"/scheduling/course-requests/{request_id}", headers=headers)

    def submit_course_request(self, request_id, headers, payload=None):
        return self._request("POST", f"/scheduling/course-requests/{request_id}/submit", payload or {}, headers)

    def unsubmit_course_request(self, request_id, headers, payload=None):
        return self._request("POST", f"/scheduling/course-requests/{request_id}/unsubmit", payload or {}, headers)

    def delete_course_request(self, request_id, headers):
        return self._request("DELETE", f"/scheduling/course-requests/{request_id}", headers=headers)

    # --- Sections --------------------------------------------------------------------
    def list_sections(self, headers, params=None):
        return self._request("GET", "/scheduling/sections", headers=headers, params=params)

    def get_section(self, section_id, headers):
        return self._request("GET", f"/scheduling/sections/{section_id}", headers=headers)

    def patch_section(self, section_id, payload, headers):
        return self._request("PATCH", f"/scheduling/sections/{section_id}", payload, headers)

    def cancel_section(self, section_id, headers, payload=None):
        return self._request("POST", f"/scheduling/sections/{section_id}/cancel", payload or {}, headers)

    def get_section_roster(self, section_id, headers, params=None):
        return self._request("GET", f"/scheduling/sections/{section_id}/roster", headers=headers, params=params)

    # --- Change requests ---------------------------------------------------------------
    def create_change_request(self, payload, headers):
        return self._request("POST", "/scheduling/change-requests", payload, headers)

    def list_change_requests(self, headers, params=None):
        return self._request("GET", "/scheduling/change-requests", headers=headers, params=params)

    def get_change_request(self, request_id, headers):
        return self._request("GET", f"/scheduling/change-requests/{request_id}", headers=headers)

    def claim_change_request(self, request_id, headers, payload=None):
        return self._request("POST", f"/scheduling/change-requests/{request_id}/claim", payload or {}, headers)

    def return_change_request_for_revision(self, request_id, payload, headers):
        return self._request("POST", f"/scheduling/change-requests/{request_id}/return-for-revision", payload, headers)

    def resubmit_change_request(self, request_id, headers, payload=None):
        return self._request("POST", f"/scheduling/change-requests/{request_id}/resubmit", payload or {}, headers)

    def decide_change_request(self, request_id, payload, headers):
        return self._request("POST", f"/scheduling/change-requests/{request_id}/decide", payload, headers)

    def execute_change_request(self, request_id, headers, payload=None):
        return self._request("POST", f"/scheduling/change-requests/{request_id}/execute", payload or {}, headers)

    def cancel_change_request(self, request_id, headers, payload=None):
        return self._request("POST", f"/scheduling/change-requests/{request_id}/cancel", payload or {}, headers)

    # --- Appointments --------------------------------------------------------------------
    def create_appointment(self, payload, headers):
        return self._request("POST", "/scheduling/appointments", payload, headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/scheduling/appointments", headers=headers, params=params)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/scheduling/appointments/{appointment_id}", headers=headers)

    def complete_appointment(self, appointment_id, headers, payload=None):
        return self._request("POST", f"/scheduling/appointments/{appointment_id}/complete", payload or {}, headers)

    def mark_no_show_appointment(self, appointment_id, headers, payload=None):
        return self._request("POST", f"/scheduling/appointments/{appointment_id}/mark-no-show", payload or {}, headers)

    def cancel_appointment(self, appointment_id, headers, payload=None):
        return self._request("POST", f"/scheduling/appointments/{appointment_id}/cancel", payload or {}, headers)

    # --- Recovery placements ---------------------------------------------------------------
    def create_recovery_placement(self, payload, headers):
        return self._request("POST", "/scheduling/recovery-placements", payload, headers)

    def list_recovery_placements(self, headers, params=None):
        return self._request("GET", "/scheduling/recovery-placements", headers=headers, params=params)

    def get_recovery_placement(self, placement_id, headers):
        return self._request("GET", f"/scheduling/recovery-placements/{placement_id}", headers=headers)

    def place_recovery_placement(self, placement_id, headers, payload=None):
        return self._request("POST", f"/scheduling/recovery-placements/{placement_id}/place", payload or {}, headers)

    def waive_recovery_placement(self, placement_id, payload, headers):
        return self._request("POST", f"/scheduling/recovery-placements/{placement_id}/waive", payload, headers)

    # --- Single-resource reads ---------------------------------------------------------------
    def get_schedule_entry(self, entry_id, headers):
        return self._request("GET", f"/scheduling/schedule-entries/{entry_id}", headers=headers)

    def list_schedule_entries(self, headers, params=None):
        return self._request("GET", "/scheduling/schedule-entries", headers=headers, params=params)

    def get_credit_audit(self, audit_id, headers):
        return self._request("GET", f"/scheduling/credit-audits/{audit_id}", headers=headers)

    def list_credit_audits(self, headers, params=None):
        return self._request("GET", "/scheduling/credit-audits", headers=headers, params=params)

    def get_qualification(self, qualification_id, headers):
        return self._request("GET", f"/scheduling/qualifications/{qualification_id}", headers=headers)

    def list_qualifications(self, headers, params=None):
        return self._request("GET", "/scheduling/qualifications", headers=headers, params=params)

    # --- Logical clock ---------------------------------------------------------------------------
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
