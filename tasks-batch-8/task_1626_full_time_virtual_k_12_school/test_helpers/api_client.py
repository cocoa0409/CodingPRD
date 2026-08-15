"""API client: one method per endpoint defined in the PRD.

All resources are mounted under the /vks prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/vks/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Districts
    # ------------------------------------------------------------------
    def create_district(self, payload, headers):
        return self._request("POST", "/vks/districts", payload, headers)

    def get_district(self, district_id, headers):
        return self._request("GET", f"/vks/districts/{district_id}", headers=headers)

    def list_districts(self, headers, params=None):
        return self._request("GET", "/vks/districts", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Students
    # ------------------------------------------------------------------
    def create_student(self, payload, headers):
        return self._request("POST", "/vks/students", payload, headers)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/vks/students/{student_id}", headers=headers)

    def list_students(self, headers, params=None):
        return self._request("GET", "/vks/students", headers=headers, params=params)

    def verify_residency(self, student_id, headers):
        return self._request("POST", f"/vks/students/{student_id}/verify-residency",
                             {}, headers)

    def enroll_student(self, student_id, expected_student_version, headers):
        return self._request("POST", f"/vks/students/{student_id}/enroll",
                             {"expected_student_version": expected_student_version},
                             headers)

    def withdraw_student(self, student_id, withdrawal_reason, headers):
        return self._request("POST", f"/vks/students/{student_id}/withdraw",
                             {"withdrawal_reason": withdrawal_reason}, headers)

    def request_reenrollment(self, student_id, headers):
        return self._request("POST", f"/vks/students/{student_id}/request-reenrollment",
                             {}, headers)

    # ------------------------------------------------------------------
    # Enrollment terms
    # ------------------------------------------------------------------
    def list_enrollment_terms(self, student_id, headers, params=None):
        return self._request("GET", f"/vks/students/{student_id}/enrollment-terms",
                             headers=headers, params=params)

    def get_enrollment_term(self, term_id, headers):
        return self._request("GET", f"/vks/enrollment-terms/{term_id}", headers=headers)

    # ------------------------------------------------------------------
    # Device / internet stipends
    # ------------------------------------------------------------------
    def create_stipend(self, payload, headers):
        return self._request("POST", "/vks/stipends", payload, headers)

    def get_stipend(self, stipend_id, headers):
        return self._request("GET", f"/vks/stipends/{stipend_id}", headers=headers)

    def list_student_stipends(self, student_id, headers, params=None):
        return self._request("GET", f"/vks/students/{student_id}/stipends",
                             headers=headers, params=params)

    def issue_stipend(self, stipend_id, headers):
        return self._request("POST", f"/vks/stipends/{stipend_id}/issue", {}, headers)

    def mark_stipend_returned(self, stipend_id, headers):
        return self._request("POST", f"/vks/stipends/{stipend_id}/mark-returned",
                             {}, headers)

    # ------------------------------------------------------------------
    # Teachers
    # ------------------------------------------------------------------
    def create_teacher(self, payload, headers):
        return self._request("POST", "/vks/teachers", payload, headers)

    def get_teacher(self, teacher_id, headers):
        return self._request("GET", f"/vks/teachers/{teacher_id}", headers=headers)

    def list_teachers(self, headers, params=None):
        return self._request("GET", "/vks/teachers", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Teacher assignments
    # ------------------------------------------------------------------
    def create_teacher_assignment(self, payload, headers):
        return self._request("POST", "/vks/teacher-assignments", payload, headers)

    def get_teacher_assignment(self, assignment_id, headers):
        return self._request("GET", f"/vks/teacher-assignments/{assignment_id}",
                             headers=headers)

    def list_teacher_assignments(self, teacher_id, headers, params=None):
        return self._request("GET", f"/vks/teachers/{teacher_id}/teacher-assignments",
                             headers=headers, params=params)

    def list_student_teacher_assignments(self, student_id, headers, params=None):
        return self._request("GET", f"/vks/students/{student_id}/teacher-assignments",
                             headers=headers, params=params)

    def end_teacher_assignment(self, assignment_id, headers):
        return self._request("POST", f"/vks/teacher-assignments/{assignment_id}/end",
                             {}, headers)

    # ------------------------------------------------------------------
    # Attendance
    # ------------------------------------------------------------------
    def create_attendance(self, payload, headers):
        return self._request("POST", "/vks/attendance", payload, headers)

    def get_attendance(self, attendance_id, headers):
        return self._request("GET", f"/vks/attendance/{attendance_id}", headers=headers)

    def list_student_attendance(self, student_id, headers, params=None):
        return self._request("GET", f"/vks/students/{student_id}/attendance",
                             headers=headers, params=params)

    def excuse_attendance(self, attendance_id, excused_reason, headers):
        return self._request("POST", f"/vks/attendance/{attendance_id}/excuse",
                             {"excused_reason": excused_reason}, headers)

    # ------------------------------------------------------------------
    # Assessment windows
    # ------------------------------------------------------------------
    def create_assessment_window(self, payload, headers):
        return self._request("POST", "/vks/assessment-windows", payload, headers)

    def get_assessment_window(self, window_id, headers):
        return self._request("GET", f"/vks/assessment-windows/{window_id}",
                             headers=headers)

    def list_assessment_windows(self, headers, params=None):
        return self._request("GET", "/vks/assessment-windows", headers=headers,
                             params=params)

    # ------------------------------------------------------------------
    # Test sites
    # ------------------------------------------------------------------
    def create_test_site(self, payload, headers):
        return self._request("POST", "/vks/test-sites", payload, headers)

    def get_test_site(self, site_id, headers):
        return self._request("GET", f"/vks/test-sites/{site_id}", headers=headers)

    def list_test_sites(self, headers, params=None):
        return self._request("GET", "/vks/test-sites", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Proctor assignments
    # ------------------------------------------------------------------
    def create_proctor_assignment(self, payload, headers):
        return self._request("POST", "/vks/proctor-assignments", payload, headers)

    def get_proctor_assignment(self, assignment_id, headers):
        return self._request("GET", f"/vks/proctor-assignments/{assignment_id}",
                             headers=headers)

    def list_window_proctor_assignments(self, window_id, headers, params=None):
        return self._request(
            "GET", f"/vks/assessment-windows/{window_id}/proctor-assignments",
            headers=headers, params=params)

    def list_site_proctor_assignments(self, site_id, headers, params=None):
        return self._request("GET", f"/vks/test-sites/{site_id}/proctor-assignments",
                             headers=headers, params=params)

    def list_student_proctor_assignments(self, student_id, headers, params=None):
        return self._request("GET", f"/vks/students/{student_id}/proctor-assignments",
                             headers=headers, params=params)

    def mark_proctor_completed(self, assignment_id, headers):
        return self._request(
            "POST", f"/vks/proctor-assignments/{assignment_id}/mark-completed",
            {}, headers)

    def cancel_proctor_assignment(self, assignment_id, headers):
        return self._request("POST", f"/vks/proctor-assignments/{assignment_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Service deliveries
    # ------------------------------------------------------------------
    def create_service_delivery(self, payload, headers):
        return self._request("POST", "/vks/service-deliveries", payload, headers)

    def get_service_delivery(self, delivery_id, headers):
        return self._request("GET", f"/vks/service-deliveries/{delivery_id}",
                             headers=headers)

    def list_student_service_deliveries(self, student_id, headers, params=None):
        return self._request("GET", f"/vks/students/{student_id}/service-deliveries",
                             headers=headers, params=params)

    def list_provider_service_deliveries(self, teacher_id, headers, params=None):
        return self._request("GET", f"/vks/teachers/{teacher_id}/service-deliveries",
                             headers=headers, params=params)

    def mark_service_delivered(self, delivery_id, headers):
        return self._request(
            "POST", f"/vks/service-deliveries/{delivery_id}/mark-delivered",
            {}, headers)

    def mark_service_missed(self, delivery_id, headers):
        return self._request(
            "POST", f"/vks/service-deliveries/{delivery_id}/mark-missed", {}, headers)

    def cancel_service_delivery(self, delivery_id, headers):
        return self._request(
            "POST", f"/vks/service-deliveries/{delivery_id}/cancel", {}, headers)

    def reschedule_service_delivery(self, delivery_id, scheduled_at, headers):
        return self._request(
            "POST", f"/vks/service-deliveries/{delivery_id}/reschedule",
            {"scheduled_at": scheduled_at}, headers)


api_client = ApiClient()
