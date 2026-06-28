"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; the base _request() handles the
HTTP envelope. All paths are mounted under the /school prefix (PRD §2).
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----- Logical clock (PRD §2.9) -----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/school/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ----- Program -----
    def create_program(self, payload, headers):
        return self._request("POST", "/school/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/school/programs/{program_id}", headers=headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/school/programs", headers=headers, params=params)

    def get_placement_report(self, program_id, headers):
        return self._request(
            "GET", f"/school/programs/{program_id}/placement-report", headers=headers,
        )

    # ----- Student -----
    def create_student(self, payload, headers):
        return self._request("POST", "/school/students", payload, headers)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/school/students/{student_id}", headers=headers)

    # ----- Instructor -----
    def create_instructor(self, payload, headers):
        return self._request("POST", "/school/instructors", payload, headers)

    def get_instructor(self, instructor_id, headers):
        return self._request("GET", f"/school/instructors/{instructor_id}", headers=headers)

    # ----- Station -----
    def create_station(self, payload, headers):
        return self._request("POST", "/school/stations", payload, headers)

    def get_station(self, station_id, headers):
        return self._request("GET", f"/school/stations/{station_id}", headers=headers)

    def list_stations(self, headers, params=None):
        return self._request("GET", "/school/stations", headers=headers, params=params)

    # ----- Enrollment -----
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/school/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/school/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/school/enrollments", headers=headers, params=params)

    def patch_enrollment(self, enrollment_id, payload, headers):
        return self._request(
            "PATCH", f"/school/enrollments/{enrollment_id}", payload, headers,
        )

    def evaluate_sap(self, enrollment_id, headers):
        return self._request(
            "POST", f"/school/enrollments/{enrollment_id}/evaluate-sap", {}, headers,
        )

    def record_placement(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"/school/enrollments/{enrollment_id}/placement", payload, headers,
        )

    # ----- Attendance -----
    def create_attendance(self, payload, headers):
        return self._request("POST", "/school/attendance", payload, headers)

    def get_attendance(self, attendance_id, headers):
        return self._request("GET", f"/school/attendance/{attendance_id}", headers=headers)

    def list_attendance(self, headers, params=None):
        return self._request("GET", "/school/attendance", headers=headers, params=params)

    def approve_attendance(self, attendance_id, headers):
        return self._request(
            "POST", f"/school/attendance/{attendance_id}/approve", {}, headers,
        )

    def void_attendance(self, attendance_id, headers):
        return self._request(
            "POST", f"/school/attendance/{attendance_id}/void", {}, headers,
        )

    # ----- Clinic tickets -----
    def create_clinic_ticket(self, payload, headers):
        return self._request("POST", "/school/clinic-tickets", payload, headers)

    def get_clinic_ticket(self, ticket_id, headers):
        return self._request("GET", f"/school/clinic-tickets/{ticket_id}", headers=headers)

    def list_clinic_tickets(self, headers, params=None):
        return self._request("GET", "/school/clinic-tickets", headers=headers, params=params)

    def sign_off_clinic_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/school/clinic-tickets/{ticket_id}/sign-off", {}, headers,
        )

    def pay_clinic_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/school/clinic-tickets/{ticket_id}/pay", {}, headers,
        )

    def void_clinic_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/school/clinic-tickets/{ticket_id}/void", {}, headers,
        )

    # ----- Station assignments -----
    def create_station_assignment(self, payload, headers):
        return self._request("POST", "/school/station-assignments", payload, headers)

    def get_station_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/school/station-assignments/{assignment_id}", headers=headers,
        )

    def list_station_assignments(self, headers, params=None):
        return self._request(
            "GET", "/school/station-assignments", headers=headers, params=params,
        )

    def release_station_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/school/station-assignments/{assignment_id}/release", {}, headers,
        )

    # ----- Disbursements -----
    def create_disbursement(self, payload, headers):
        return self._request("POST", "/school/disbursements", payload, headers)

    def get_disbursement(self, disbursement_id, headers):
        return self._request("GET", f"/school/disbursements/{disbursement_id}", headers=headers)

    def list_disbursements(self, headers, params=None):
        return self._request("GET", "/school/disbursements", headers=headers, params=params)

    def post_disbursement(self, disbursement_id, expected_enrollment_version, headers):
        return self._request(
            "POST", f"/school/disbursements/{disbursement_id}/post",
            {"expected_enrollment_version": expected_enrollment_version}, headers,
        )

    def return_disbursement(self, disbursement_id, headers):
        return self._request(
            "POST", f"/school/disbursements/{disbursement_id}/return", {}, headers,
        )

    # ----- Exam applications -----
    def create_exam_application(self, payload, headers):
        return self._request("POST", "/school/exam-applications", payload, headers)

    def get_exam_application(self, application_id, headers):
        return self._request("GET", f"/school/exam-applications/{application_id}", headers=headers)

    def list_exam_applications(self, headers, params=None):
        return self._request("GET", "/school/exam-applications", headers=headers, params=params)

    def submit_exam_application(self, application_id, headers):
        return self._request(
            "POST", f"/school/exam-applications/{application_id}/submit", {}, headers,
        )

    def return_exam_application(self, application_id, headers):
        return self._request(
            "POST", f"/school/exam-applications/{application_id}/return", {}, headers,
        )

    def approve_exam_application(self, application_id, headers):
        return self._request(
            "POST", f"/school/exam-applications/{application_id}/approve", {}, headers,
        )

    def schedule_exam_application(self, application_id, headers):
        return self._request(
            "POST", f"/school/exam-applications/{application_id}/schedule", {}, headers,
        )

    def record_exam_result(self, application_id, result, headers):
        return self._request(
            "POST", f"/school/exam-applications/{application_id}/record-result",
            {"result": result}, headers,
        )

    # ----- Withdrawals -----
    def create_withdrawal(self, payload, headers):
        return self._request("POST", "/school/withdrawals", payload, headers)

    def get_withdrawal(self, withdrawal_id, headers):
        return self._request("GET", f"/school/withdrawals/{withdrawal_id}", headers=headers)

    def list_withdrawals(self, headers, params=None):
        return self._request("GET", "/school/withdrawals", headers=headers, params=params)

    def finalize_withdrawal(self, withdrawal_id, expected_enrollment_version, headers):
        return self._request(
            "POST", f"/school/withdrawals/{withdrawal_id}/finalize",
            {"expected_enrollment_version": expected_enrollment_version}, headers,
        )


api_client = ApiClient()
