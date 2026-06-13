"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Schools + clock ----
    def create_school(self, payload, headers):
        return self._request("POST", "/schools", payload, headers)

    def get_school(self, school_id, headers):
        return self._request("GET", f"/schools/{school_id}", headers=headers)

    def advance_clock(self, school_id, payload, headers):
        return self._request("POST", f"/schools/{school_id}/clock/advance", payload, headers)

    # ---- Students ----
    def create_student(self, payload, headers):
        return self._request("POST", "/students", payload, headers)

    def list_students(self, headers, params=None):
        return self._request("GET", "/students", headers=headers, params=params)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/students/{student_id}", headers=headers)

    def get_portal_summary(self, student_id, headers):
        return self._request("GET", f"/students/{student_id}/portal-summary", headers=headers)

    def link_guardian(self, student_id, payload, headers):
        return self._request("POST", f"/students/{student_id}/guardians", payload, headers)

    # ---- Enrollments ----
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/enrollments", payload, headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def withdraw_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/withdraw", payload, headers)

    def mark_no_show(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/mark-no-show", {}, headers)

    def list_daily_attendance(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/enrollments/{enrollment_id}/daily-attendance", headers=headers, params=params)

    # ---- Courses + sections ----
    def create_course(self, payload, headers):
        return self._request("POST", "/courses", payload, headers)

    def list_courses(self, headers, params=None):
        return self._request("GET", "/courses", headers=headers, params=params)

    def get_course(self, course_id, headers):
        return self._request("GET", f"/courses/{course_id}", headers=headers)

    def create_section(self, payload, headers):
        return self._request("POST", "/sections", payload, headers)

    def list_sections(self, headers, params=None):
        return self._request("GET", "/sections", headers=headers, params=params)

    def get_section(self, section_id, headers):
        return self._request("GET", f"/sections/{section_id}", headers=headers)

    def close_section(self, section_id, headers):
        return self._request("POST", f"/sections/{section_id}/close", {}, headers)

    def reopen_section(self, section_id, headers):
        return self._request("POST", f"/sections/{section_id}/reopen", {}, headers)

    def list_section_schedule_assignments(self, section_id, headers, params=None):
        return self._request("GET", f"/sections/{section_id}/schedule-assignments", headers=headers, params=params)

    # ---- Scheduling ----
    def create_schedule_assignment(self, payload, headers):
        return self._request("POST", "/schedule-assignments", payload, headers)

    def list_schedule_assignments(self, headers, params=None):
        return self._request("GET", "/schedule-assignments", headers=headers, params=params)

    def get_schedule_assignment(self, assignment_id, headers):
        return self._request("GET", f"/schedule-assignments/{assignment_id}", headers=headers)

    def drop_schedule_assignment(self, assignment_id, headers):
        return self._request("POST", f"/schedule-assignments/{assignment_id}/drop", {}, headers)

    # ---- Attendance ----
    def create_attendance_record(self, payload, headers):
        return self._request("POST", "/attendance-records", payload, headers)

    def list_attendance_records(self, headers, params=None):
        return self._request("GET", "/attendance-records", headers=headers, params=params)

    def get_attendance_record(self, record_id, headers):
        return self._request("GET", f"/attendance-records/{record_id}", headers=headers)

    def correct_attendance_record(self, record_id, payload, headers):
        return self._request("POST", f"/attendance-records/{record_id}/correct", payload, headers)

    # ---- Standards gradebook ----
    def create_standard_score(self, payload, headers):
        return self._request("POST", "/standard-scores", payload, headers)

    def list_standard_scores(self, headers, params=None):
        return self._request("GET", "/standard-scores", headers=headers, params=params)

    def get_standard_score(self, score_id, headers):
        return self._request("GET", f"/standard-scores/{score_id}", headers=headers)

    # ---- Report cards ----
    def create_report_card(self, payload, headers):
        return self._request("POST", "/report-cards", payload, headers)

    def list_report_cards(self, headers, params=None):
        return self._request("GET", "/report-cards", headers=headers, params=params)

    def get_report_card(self, report_card_id, headers):
        return self._request("GET", f"/report-cards/{report_card_id}", headers=headers)

    def finalize_report_card(self, report_card_id, payload, headers):
        return self._request("POST", f"/report-cards/{report_card_id}/finalize", payload, headers)

    def reopen_report_card(self, report_card_id, headers):
        return self._request("POST", f"/report-cards/{report_card_id}/reopen", {}, headers)

    # ---- Discipline ----
    def create_discipline_incident(self, payload, headers):
        return self._request("POST", "/discipline-incidents", payload, headers)

    def list_discipline_incidents(self, headers, params=None):
        return self._request("GET", "/discipline-incidents", headers=headers, params=params)

    def get_discipline_incident(self, incident_id, headers):
        return self._request("GET", f"/discipline-incidents/{incident_id}", headers=headers)

    def begin_review(self, incident_id, headers):
        return self._request("POST", f"/discipline-incidents/{incident_id}/begin-review", {}, headers)

    def adjudicate(self, incident_id, headers):
        return self._request("POST", f"/discipline-incidents/{incident_id}/adjudicate", {}, headers)

    def dismiss_incident(self, incident_id, headers):
        return self._request("POST", f"/discipline-incidents/{incident_id}/dismiss", {}, headers)

    def create_consequence(self, incident_id, payload, headers):
        return self._request("POST", f"/discipline-incidents/{incident_id}/consequences", payload, headers)

    def list_incident_consequences(self, incident_id, headers, params=None):
        return self._request("GET", f"/discipline-incidents/{incident_id}/consequences", headers=headers, params=params)

    def list_consequences(self, headers, params=None):
        return self._request("GET", "/discipline-consequences", headers=headers, params=params)

    def get_consequence(self, consequence_id, headers):
        return self._request("GET", f"/discipline-consequences/{consequence_id}", headers=headers)

    def rescind_consequence(self, consequence_id, headers):
        return self._request("POST", f"/discipline-consequences/{consequence_id}/rescind", {}, headers)

    # ---- ADA funding reports ----
    def create_ada_report(self, payload, headers):
        return self._request("POST", "/ada-funding-reports", payload, headers)

    def list_ada_reports(self, headers, params=None):
        return self._request("GET", "/ada-funding-reports", headers=headers, params=params)

    def get_ada_report(self, report_id, headers):
        return self._request("GET", f"/ada-funding-reports/{report_id}", headers=headers)

    def recompute_ada_report(self, report_id, headers):
        return self._request("POST", f"/ada-funding-reports/{report_id}/recompute", {}, headers)

    def certify_ada_report(self, report_id, payload, headers):
        return self._request("POST", f"/ada-funding-reports/{report_id}/certify", payload, headers)

    def reject_ada_report(self, report_id, headers):
        return self._request("POST", f"/ada-funding-reports/{report_id}/reject", {}, headers)


api_client = ApiClient()
