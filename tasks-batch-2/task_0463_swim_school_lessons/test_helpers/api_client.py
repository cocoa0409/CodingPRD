"""API client: one method per endpoint defined in the PRD (Section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Test-driving clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- Location ----
    def create_location(self, payload, headers):
        return self._request("POST", "/locations", payload, headers)

    def list_locations(self, headers, params=None):
        return self._request("GET", "/locations", headers=headers, params=params)

    def get_location(self, location_id, headers):
        return self._request("GET", f"/locations/{location_id}", headers=headers)

    # ---- Level + Skill ----
    def create_level(self, payload, headers):
        return self._request("POST", "/levels", payload, headers)

    def list_levels(self, headers, params=None):
        return self._request("GET", "/levels", headers=headers, params=params)

    def get_level(self, level_id, headers):
        return self._request("GET", f"/levels/{level_id}", headers=headers)

    def create_skill(self, level_id, payload, headers):
        return self._request("POST", f"/levels/{level_id}/skills", payload, headers)

    def list_skills(self, level_id, headers, params=None):
        return self._request(
            "GET", f"/levels/{level_id}/skills", headers=headers, params=params
        )

    # ---- Instructor ----
    def create_instructor(self, payload, headers):
        return self._request("POST", "/instructors", payload, headers)

    def list_instructors(self, headers, params=None):
        return self._request("GET", "/instructors", headers=headers, params=params)

    def get_instructor(self, instructor_id, headers):
        return self._request("GET", f"/instructors/{instructor_id}", headers=headers)

    # ---- Parent + Student ----
    def create_parent(self, payload, headers):
        return self._request("POST", "/parents", payload, headers)

    def list_parents(self, headers, params=None):
        return self._request("GET", "/parents", headers=headers, params=params)

    def get_parent(self, parent_id, headers):
        return self._request("GET", f"/parents/{parent_id}", headers=headers)

    def create_student(self, parent_id, payload, headers):
        return self._request(
            "POST", f"/parents/{parent_id}/students", payload, headers
        )

    def list_parent_students(self, parent_id, headers, params=None):
        return self._request(
            "GET", f"/parents/{parent_id}/students", headers=headers, params=params
        )

    def list_students(self, headers, params=None):
        return self._request("GET", "/students", headers=headers, params=params)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/students/{student_id}", headers=headers)

    def withdraw_student(self, student_id, headers):
        return self._request(
            "POST", f"/students/{student_id}/withdraw", headers=headers
        )

    # ---- ClassSession ----
    def create_class_session(self, payload, headers):
        return self._request("POST", "/class-sessions", payload, headers)

    def list_class_sessions(self, headers, params=None):
        return self._request("GET", "/class-sessions", headers=headers, params=params)

    def get_class_session(self, session_id, headers):
        return self._request("GET", f"/class-sessions/{session_id}", headers=headers)

    def open_class_session(self, session_id, headers):
        return self._request(
            "POST", f"/class-sessions/{session_id}/open", headers=headers
        )

    def close_class_session(self, session_id, headers):
        return self._request(
            "POST", f"/class-sessions/{session_id}/close", headers=headers
        )

    # ---- Enrollment ----
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/enrollments", payload, headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def pause_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/pause", headers=headers
        )

    def resume_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/resume", headers=headers
        )

    def withdraw_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/withdraw", headers=headers
        )

    # ---- Invoice ----
    def create_invoice(self, payload, headers):
        return self._request("POST", "/invoices", payload, headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/issue", headers=headers)

    def pay_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/pay", payload, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/void", headers=headers)

    # ---- MakeupCredit ----
    def list_makeup_credits(self, headers, params=None):
        return self._request("GET", "/makeup-credits", headers=headers, params=params)

    def get_makeup_credit(self, credit_id, headers):
        return self._request("GET", f"/makeup-credits/{credit_id}", headers=headers)

    # ---- MakeupBooking ----
    def create_makeup_booking(self, payload, headers):
        return self._request("POST", "/makeup-bookings", payload, headers)

    def list_makeup_bookings(self, headers, params=None):
        return self._request("GET", "/makeup-bookings", headers=headers, params=params)

    def get_makeup_booking(self, booking_id, headers):
        return self._request("GET", f"/makeup-bookings/{booking_id}", headers=headers)

    def cancel_makeup_booking(self, booking_id, headers):
        return self._request(
            "POST", f"/makeup-bookings/{booking_id}/cancel", headers=headers
        )

    def mark_attended_makeup_booking(self, booking_id, headers):
        return self._request(
            "POST", f"/makeup-bookings/{booking_id}/mark-attended", headers=headers
        )

    def mark_no_show_makeup_booking(self, booking_id, headers):
        return self._request(
            "POST", f"/makeup-bookings/{booking_id}/mark-no-show", headers=headers
        )

    # ---- Assessment ----
    def create_assessment(self, payload, headers):
        return self._request("POST", "/assessments", payload, headers)

    def list_assessments(self, headers, params=None):
        return self._request("GET", "/assessments", headers=headers, params=params)

    def get_assessment(self, assessment_id, headers):
        return self._request("GET", f"/assessments/{assessment_id}", headers=headers)

    def submit_assessment(self, assessment_id, headers):
        return self._request(
            "POST", f"/assessments/{assessment_id}/submit", headers=headers
        )

    def approve_assessment(self, assessment_id, headers):
        return self._request(
            "POST", f"/assessments/{assessment_id}/approve", headers=headers
        )

    def reject_assessment(self, assessment_id, headers):
        return self._request(
            "POST", f"/assessments/{assessment_id}/reject", headers=headers
        )


api_client = ApiClient()
