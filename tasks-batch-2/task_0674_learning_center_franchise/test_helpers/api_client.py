"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Test-driving clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ---- Center ----
    def create_center(self, payload, headers):
        return self._request("POST", "/centers", payload, headers)

    def get_center(self, center_id, headers):
        return self._request("GET", f"/centers/{center_id}", headers=headers)

    def list_centers(self, headers, params=None):
        return self._request("GET", "/centers", headers=headers, params=params)

    def activate_center(self, center_id, headers):
        return self._request("POST", f"/centers/{center_id}/activate", {}, headers)

    def suspend_center(self, center_id, headers):
        return self._request("POST", f"/centers/{center_id}/suspend", {}, headers)

    # ---- FranchiseAgreement ----
    def create_agreement(self, payload, headers):
        return self._request("POST", "/franchise-agreements", payload, headers)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/franchise-agreements/{agreement_id}", headers=headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/franchise-agreements", headers=headers, params=params)

    def activate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/franchise-agreements/{agreement_id}/activate", {}, headers)

    def terminate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/franchise-agreements/{agreement_id}/terminate", {}, headers)

    # ---- Subject ----
    def create_subject(self, payload, headers):
        return self._request("POST", "/subjects", payload, headers)

    def get_subject(self, subject_id, headers):
        return self._request("GET", f"/subjects/{subject_id}", headers=headers)

    def list_subjects(self, headers, params=None):
        return self._request("GET", "/subjects", headers=headers, params=params)

    # ---- CurriculumLevel ----
    def create_curriculum_level(self, payload, headers):
        return self._request("POST", "/curriculum-levels", payload, headers)

    def get_curriculum_level(self, level_id, headers):
        return self._request("GET", f"/curriculum-levels/{level_id}", headers=headers)

    def list_curriculum_levels(self, headers, params=None):
        return self._request("GET", "/curriculum-levels", headers=headers, params=params)

    # ---- Family ----
    def create_family(self, payload, headers):
        return self._request("POST", "/families", payload, headers)

    def get_family(self, family_id, headers):
        return self._request("GET", f"/families/{family_id}", headers=headers)

    def list_families(self, headers, params=None):
        return self._request("GET", "/families", headers=headers, params=params)

    def adjust_wallet(self, family_id, payload, headers):
        return self._request("POST", f"/families/{family_id}/wallet-adjustments", payload, headers)

    # ---- Student ----
    def create_student(self, payload, headers):
        return self._request("POST", "/students", payload, headers)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/students/{student_id}", headers=headers)

    def list_students(self, headers, params=None):
        return self._request("GET", "/students", headers=headers, params=params)

    # ---- Enrollment ----
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def place_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/place", payload, headers)

    def pause_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/pause", {}, headers)

    def resume_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/resume", {}, headers)

    def withdraw_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/withdraw", {}, headers)

    def get_enrollment_report(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}/report", headers=headers)

    # ---- Worksheet ----
    def create_worksheet(self, payload, headers):
        return self._request("POST", "/worksheets", payload, headers)

    def get_worksheet(self, worksheet_id, headers):
        return self._request("GET", f"/worksheets/{worksheet_id}", headers=headers)

    def list_worksheets(self, headers, params=None):
        return self._request("GET", "/worksheets", headers=headers, params=params)

    def grade_worksheet(self, worksheet_id, payload, headers):
        return self._request("POST", f"/worksheets/{worksheet_id}/grade", payload, headers)

    def reassign_worksheet(self, worksheet_id, headers):
        return self._request("POST", f"/worksheets/{worksheet_id}/reassign", {}, headers)

    # ---- Session ----
    def create_session(self, payload, headers):
        return self._request("POST", "/sessions", payload, headers)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/sessions/{session_id}", headers=headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/sessions", headers=headers, params=params)

    def open_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/open", {}, headers)

    def close_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/close", {}, headers)

    def cancel_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/cancel", {}, headers)

    # ---- AttendanceRecord ----
    def create_attendance_record(self, payload, headers):
        return self._request("POST", "/attendance-records", payload, headers)

    def get_attendance_record(self, record_id, headers):
        return self._request("GET", f"/attendance-records/{record_id}", headers=headers)

    def list_attendance_records(self, headers, params=None):
        return self._request("GET", "/attendance-records", headers=headers, params=params)

    def check_in_attendance(self, record_id, headers):
        return self._request("POST", f"/attendance-records/{record_id}/check-in", {}, headers)

    def mark_absent_attendance(self, record_id, headers):
        return self._request("POST", f"/attendance-records/{record_id}/mark-absent", {}, headers)

    def cancel_attendance(self, record_id, headers):
        return self._request("POST", f"/attendance-records/{record_id}/cancel", {}, headers)

    # ---- Invoice ----
    def create_invoice(self, payload, headers):
        return self._request("POST", "/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/issue", {}, headers)

    def pay_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/pay", payload, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/void", {}, headers)


api_client = ApiClient()
