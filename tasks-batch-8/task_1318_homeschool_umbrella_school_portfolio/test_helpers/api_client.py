"""API client: one method per endpoint defined in the PRD (§4 endpoint table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Academic years ---
    def create_academic_year(self, payload, headers):
        return self._request("POST", "/academic-years", payload, headers)

    def get_academic_year(self, year_id, headers):
        return self._request("GET", f"/academic-years/{year_id}", headers=headers)

    def open_academic_year(self, year_id, headers):
        return self._request("POST", f"/academic-years/{year_id}/open", {}, headers)

    def close_academic_year(self, year_id, headers):
        return self._request("POST", f"/academic-years/{year_id}/close", {}, headers)

    def run_compliance_sweep(self, year_id, headers):
        return self._request("POST", f"/academic-years/{year_id}/run-compliance-sweep", {}, headers)

    def list_year_enrollments(self, year_id, headers, params=None):
        return self._request("GET", f"/academic-years/{year_id}/enrollments", headers=headers, params=params)

    def list_year_exam_sessions(self, year_id, headers, params=None):
        return self._request("GET", f"/academic-years/{year_id}/exam-sessions", headers=headers, params=params)

    def list_year_coop_classes(self, year_id, headers, params=None):
        return self._request("GET", f"/academic-years/{year_id}/coop-classes", headers=headers, params=params)

    def list_year_compliance_reports(self, year_id, headers, params=None):
        return self._request("GET", f"/academic-years/{year_id}/compliance-reports", headers=headers, params=params)

    # --- Families & students ---
    def create_family(self, payload, headers):
        return self._request("POST", "/families", payload, headers)

    def get_family(self, family_id, headers):
        return self._request("GET", f"/families/{family_id}", headers=headers)

    def list_family_students(self, family_id, headers, params=None):
        return self._request("GET", f"/families/{family_id}/students", headers=headers, params=params)

    def get_family_ledger(self, family_id, headers):
        return self._request("GET", f"/families/{family_id}/ledger", headers=headers)

    def create_ledger_payment(self, family_id, payload, headers):
        return self._request("POST", f"/families/{family_id}/ledger-payments", payload, headers)

    def create_student(self, family_id, payload, headers):
        return self._request("POST", f"/families/{family_id}/students", payload, headers)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/students/{student_id}", headers=headers)

    def list_student_enrollments(self, student_id, headers, params=None):
        return self._request("GET", f"/students/{student_id}/enrollments", headers=headers, params=params)

    def get_transcript(self, student_id, headers):
        return self._request("GET", f"/students/{student_id}/transcript", headers=headers)

    def list_student_graduation_applications(self, student_id, headers, params=None):
        return self._request("GET", f"/students/{student_id}/graduation-applications", headers=headers, params=params)

    # --- Enrollments ---
    def create_enrollment(self, student_id, payload, headers):
        return self._request("POST", f"/students/{student_id}/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def activate_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/activate", {}, headers)

    def withdraw_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/withdraw", payload, headers)

    def create_standing_override(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/standing-overrides", payload, headers)

    def clear_standing_override(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/standing-overrides/clear", {}, headers)

    def list_enrollment_notices(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/enrollments/{enrollment_id}/notices", headers=headers, params=params)

    def list_enrollment_curriculum_plans(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/enrollments/{enrollment_id}/curriculum-plans", headers=headers, params=params)

    def list_enrollment_attendance_entries(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/enrollments/{enrollment_id}/attendance-entries", headers=headers, params=params)

    def list_enrollment_portfolios(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/enrollments/{enrollment_id}/portfolios", headers=headers, params=params)

    def list_enrollment_course_credits(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/enrollments/{enrollment_id}/course-credits", headers=headers, params=params)

    def list_enrollment_test_registrations(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/enrollments/{enrollment_id}/test-registrations", headers=headers, params=params)

    def list_enrollment_coop_enrollments(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/enrollments/{enrollment_id}/coop-enrollments", headers=headers, params=params)

    # --- Notices of intent ---
    def create_notice(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/notices", payload, headers)

    def get_notice(self, notice_id, headers):
        return self._request("GET", f"/notices/{notice_id}", headers=headers)

    def file_notice(self, notice_id, headers):
        return self._request("POST", f"/notices/{notice_id}/file", {}, headers)

    def acknowledge_notice(self, notice_id, headers):
        return self._request("POST", f"/notices/{notice_id}/acknowledge", {}, headers)

    def return_notice(self, notice_id, payload, headers):
        return self._request("POST", f"/notices/{notice_id}/return", payload, headers)

    # --- Curriculum plans ---
    def create_curriculum_plan(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/curriculum-plans", payload, headers)

    def get_curriculum_plan(self, plan_id, headers):
        return self._request("GET", f"/curriculum-plans/{plan_id}", headers=headers)

    def submit_curriculum_plan(self, plan_id, headers):
        return self._request("POST", f"/curriculum-plans/{plan_id}/submit", {}, headers)

    def review_curriculum_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/curriculum-plans/{plan_id}/review", payload, headers)

    def amend_curriculum_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/curriculum-plans/{plan_id}/amend", payload, headers)

    # --- Attendance ---
    def create_attendance_entry(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/attendance-entries", payload, headers)

    def get_attendance_entry(self, entry_id, headers):
        return self._request("GET", f"/attendance-entries/{entry_id}", headers=headers)

    def patch_attendance_entry(self, entry_id, payload, headers):
        return self._request("PATCH", f"/attendance-entries/{entry_id}", payload, headers)

    def verify_attendance_entry(self, entry_id, headers):
        return self._request("POST", f"/attendance-entries/{entry_id}/verify", {}, headers)

    def void_attendance_entry(self, entry_id, headers):
        return self._request("POST", f"/attendance-entries/{entry_id}/void", {}, headers)

    # --- Portfolios & evaluations ---
    def create_portfolio(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/portfolios", {}, headers)

    def get_portfolio(self, portfolio_id, headers):
        return self._request("GET", f"/portfolios/{portfolio_id}", headers=headers)

    def submit_portfolio(self, portfolio_id, headers):
        return self._request("POST", f"/portfolios/{portfolio_id}/submit", {}, headers)

    def create_evaluation(self, portfolio_id, payload, headers):
        return self._request("POST", f"/portfolios/{portfolio_id}/evaluations", payload, headers)

    def list_evaluations(self, portfolio_id, headers, params=None):
        return self._request("GET", f"/portfolios/{portfolio_id}/evaluations", headers=headers, params=params)

    def get_evaluation(self, evaluation_id, headers):
        return self._request("GET", f"/evaluations/{evaluation_id}", headers=headers)

    # --- Exam sessions & registrations ---
    def create_exam_session(self, year_id, payload, headers):
        return self._request("POST", f"/academic-years/{year_id}/exam-sessions", payload, headers)

    def get_exam_session(self, session_id, headers):
        return self._request("GET", f"/exam-sessions/{session_id}", headers=headers)

    def open_exam_registration(self, session_id, headers):
        return self._request("POST", f"/exam-sessions/{session_id}/open-registration", {}, headers)

    def close_exam_registration(self, session_id, headers):
        return self._request("POST", f"/exam-sessions/{session_id}/close-registration", {}, headers)

    def administer_exam_session(self, session_id, headers):
        return self._request("POST", f"/exam-sessions/{session_id}/administer", {}, headers)

    def list_session_registrations(self, session_id, headers, params=None):
        return self._request("GET", f"/exam-sessions/{session_id}/registrations", headers=headers, params=params)

    def create_exam_registration(self, session_id, payload, headers):
        return self._request("POST", f"/exam-sessions/{session_id}/registrations", payload, headers)

    def get_test_registration(self, registration_id, headers):
        return self._request("GET", f"/test-registrations/{registration_id}", headers=headers)

    def cancel_test_registration(self, registration_id, headers):
        return self._request("POST", f"/test-registrations/{registration_id}/cancel", {}, headers)

    def record_attendance(self, registration_id, payload, headers):
        return self._request("POST", f"/test-registrations/{registration_id}/record-attendance", payload, headers)

    def record_score(self, registration_id, payload, headers):
        return self._request("POST", f"/test-registrations/{registration_id}/record-score", payload, headers)

    # --- Course credits ---
    def create_course_credit(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/course-credits", payload, headers)

    def get_course_credit(self, credit_id, headers):
        return self._request("GET", f"/course-credits/{credit_id}", headers=headers)

    def complete_course_credit(self, credit_id, payload, headers):
        return self._request("POST", f"/course-credits/{credit_id}/complete", payload, headers)

    def verify_course_credit(self, credit_id, payload, headers):
        return self._request("POST", f"/course-credits/{credit_id}/verify", payload, headers)

    def post_course_credit(self, credit_id, headers):
        return self._request("POST", f"/course-credits/{credit_id}/post", {}, headers)

    def revoke_course_credit(self, credit_id, payload, headers):
        return self._request("POST", f"/course-credits/{credit_id}/revoke", payload, headers)

    # --- Co-op classes & enrollments ---
    def create_coop_class(self, year_id, payload, headers):
        return self._request("POST", f"/academic-years/{year_id}/coop-classes", payload, headers)

    def get_coop_class(self, class_id, headers):
        return self._request("GET", f"/coop-classes/{class_id}", headers=headers)

    def open_coop_class(self, class_id, headers):
        return self._request("POST", f"/coop-classes/{class_id}/open", {}, headers)

    def cancel_coop_class(self, class_id, headers):
        return self._request("POST", f"/coop-classes/{class_id}/cancel", {}, headers)

    def list_coop_enrollments(self, class_id, headers, params=None):
        return self._request("GET", f"/coop-classes/{class_id}/enrollments", headers=headers, params=params)

    def create_coop_enrollment(self, class_id, payload, headers):
        return self._request("POST", f"/coop-classes/{class_id}/enrollments", payload, headers)

    def get_coop_enrollment(self, coop_enrollment_id, headers):
        return self._request("GET", f"/coop-enrollments/{coop_enrollment_id}", headers=headers)

    def drop_coop_enrollment(self, coop_enrollment_id, headers):
        return self._request("POST", f"/coop-enrollments/{coop_enrollment_id}/drop", {}, headers)

    # --- Graduation ---
    def create_graduation_application(self, student_id, payload, headers):
        return self._request("POST", f"/students/{student_id}/graduation-applications", payload, headers)

    def get_graduation_application(self, application_id, headers):
        return self._request("GET", f"/graduation-applications/{application_id}", headers=headers)

    def list_graduation_applications(self, headers, params=None):
        return self._request("GET", "/graduation-applications", headers=headers, params=params)

    def evaluate_graduation_application(self, application_id, payload, headers):
        return self._request("POST", f"/graduation-applications/{application_id}/evaluate", payload, headers)

    def issue_diploma(self, application_id, headers):
        return self._request("POST", f"/graduation-applications/{application_id}/issue-diploma", {}, headers)

    # --- Compliance reports ---
    def create_compliance_report(self, year_id, headers):
        return self._request("POST", f"/academic-years/{year_id}/compliance-reports", {}, headers)

    def get_compliance_report(self, report_id, headers):
        return self._request("GET", f"/compliance-reports/{report_id}", headers=headers)

    def submit_compliance_report(self, report_id, headers):
        return self._request("POST", f"/compliance-reports/{report_id}/submit", {}, headers)

    def accept_compliance_report(self, report_id, headers):
        return self._request("POST", f"/compliance-reports/{report_id}/accept", {}, headers)

    def reject_compliance_report(self, report_id, payload, headers):
        return self._request("POST", f"/compliance-reports/{report_id}/reject", payload, headers)

    # --- Test-driving clock ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
