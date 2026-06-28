"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # ---- Families ----
    def create_family(self, payload, headers):
        return self._request("POST", "/families", payload, headers)

    def get_family(self, family_id, headers):
        return self._request("GET", f"/families/{family_id}", headers=headers)

    def list_families(self, headers, params=None):
        return self._request("GET", "/families", headers=headers, params=params)

    def patch_family(self, family_id, payload, headers):
        return self._request("PATCH", f"/families/{family_id}", payload, headers)

    def add_payment_method(self, family_id, payload, headers):
        return self._request("POST", f"/families/{family_id}/payment-method", payload, headers)

    def grant_credit(self, family_id, payload, headers):
        return self._request("POST", f"/families/{family_id}/credit", payload, headers)

    # ---- Students ----
    def create_student(self, family_id, payload, headers):
        return self._request("POST", f"/families/{family_id}/students", payload, headers)

    def list_family_students(self, family_id, headers, params=None):
        return self._request("GET", f"/families/{family_id}/students", headers=headers, params=params)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/students/{student_id}", headers=headers)

    def withdraw_student(self, student_id, headers):
        return self._request("POST", f"/students/{student_id}/withdraw", {}, headers)

    # ---- Terms ----
    def create_term(self, payload, headers):
        return self._request("POST", "/terms", payload, headers)

    def get_term(self, term_id, headers):
        return self._request("GET", f"/terms/{term_id}", headers=headers)

    def open_term(self, term_id, headers):
        return self._request("POST", f"/terms/{term_id}/open", {}, headers)

    def close_term(self, term_id, headers):
        return self._request("POST", f"/terms/{term_id}/close", {}, headers)

    # ---- Rooms ----
    def create_room(self, payload, headers):
        return self._request("POST", "/rooms", payload, headers)

    def get_room(self, room_id, headers):
        return self._request("GET", f"/rooms/{room_id}", headers=headers)

    # ---- Instructors ----
    def create_instructor(self, payload, headers):
        return self._request("POST", "/instructors", payload, headers)

    def get_instructor(self, instructor_id, headers):
        return self._request("GET", f"/instructors/{instructor_id}", headers=headers)

    # ---- Sections ----
    def create_section(self, payload, headers):
        return self._request("POST", "/sections", payload, headers)

    def get_section(self, section_id, headers):
        return self._request("GET", f"/sections/{section_id}", headers=headers)

    def list_sections(self, headers, params=None):
        return self._request("GET", "/sections", headers=headers, params=params)

    def create_session(self, section_id, payload, headers):
        return self._request("POST", f"/sections/{section_id}/sessions", payload, headers)

    def list_section_sessions(self, section_id, headers, params=None):
        return self._request("GET", f"/sections/{section_id}/sessions", headers=headers, params=params)

    def cancel_section(self, section_id, headers):
        return self._request("POST", f"/sections/{section_id}/cancel", {}, headers)

    # ---- Sessions ----
    def get_session(self, session_id, headers):
        return self._request("GET", f"/sessions/{session_id}", headers=headers)

    # ---- Enrollments ----
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def confirm_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/confirm", {}, headers)

    def drop_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/drop", {}, headers)

    def pause_billing(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/pause-billing", {}, headers)

    def resume_billing(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/resume-billing", {}, headers)

    # ---- Attendance ----
    def mark_attendance(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/attendance", payload, headers)

    def list_enrollment_attendance(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/enrollments/{enrollment_id}/attendance", headers=headers, params=params)

    def get_attendance(self, attendance_id, headers):
        return self._request("GET", f"/attendance/{attendance_id}", headers=headers)

    def amend_attendance(self, attendance_id, payload, headers):
        return self._request("POST", f"/attendance/{attendance_id}/amend", payload, headers)

    def list_session_attendance(self, session_id, headers, params=None):
        return self._request("GET", f"/sessions/{session_id}/attendance", headers=headers, params=params)

    # ---- Costumes ----
    def create_costume(self, section_id, payload, headers):
        return self._request("POST", f"/sections/{section_id}/costumes", payload, headers)

    def list_section_costumes(self, section_id, headers, params=None):
        return self._request("GET", f"/sections/{section_id}/costumes", headers=headers, params=params)

    def get_costume(self, costume_id, headers):
        return self._request("GET", f"/costumes/{costume_id}", headers=headers)

    def submit_costume_order(self, costume_id, headers):
        return self._request("POST", f"/costumes/{costume_id}/submit-order", {}, headers)

    # ---- CostumeOrders ----
    def create_costume_order(self, payload, headers):
        return self._request("POST", "/costume-orders", payload, headers)

    def get_costume_order(self, order_id, headers):
        return self._request("GET", f"/costume-orders/{order_id}", headers=headers)

    def list_costume_orders(self, headers, params=None):
        return self._request("GET", "/costume-orders", headers=headers, params=params)

    def cancel_costume_order(self, order_id, headers):
        return self._request("POST", f"/costume-orders/{order_id}/cancel", {}, headers)

    # ---- Recitals ----
    def create_recital(self, term_id, payload, headers):
        return self._request("POST", f"/terms/{term_id}/recitals", payload, headers)

    def list_term_recitals(self, term_id, headers, params=None):
        return self._request("GET", f"/terms/{term_id}/recitals", headers=headers, params=params)

    def get_recital(self, recital_id, headers):
        return self._request("GET", f"/recitals/{recital_id}", headers=headers)

    def open_recital_sales(self, recital_id, headers):
        return self._request("POST", f"/recitals/{recital_id}/open-sales", {}, headers)

    def complete_recital(self, recital_id, headers):
        return self._request("POST", f"/recitals/{recital_id}/complete", {}, headers)

    def hold_seat(self, recital_id, payload, headers):
        return self._request("POST", f"/recitals/{recital_id}/seats", payload, headers)

    def list_recital_seats(self, recital_id, headers, params=None):
        return self._request("GET", f"/recitals/{recital_id}/seats", headers=headers, params=params)

    # ---- Seats ----
    def get_seat(self, seat_id, headers):
        return self._request("GET", f"/seats/{seat_id}", headers=headers)

    def list_seats(self, headers, params=None):
        return self._request("GET", "/seats", headers=headers, params=params)

    def purchase_seat(self, seat_id, headers):
        return self._request("POST", f"/seats/{seat_id}/purchase", {}, headers)

    def release_seat(self, seat_id, headers):
        return self._request("POST", f"/seats/{seat_id}/release", {}, headers)

    # ---- Teams ----
    def create_team(self, payload, headers):
        return self._request("POST", "/teams", payload, headers)

    def get_team(self, team_id, headers):
        return self._request("GET", f"/teams/{team_id}", headers=headers)

    def lock_team(self, team_id, headers):
        return self._request("POST", f"/teams/{team_id}/lock", {}, headers)

    def create_membership(self, team_id, payload, headers):
        return self._request("POST", f"/teams/{team_id}/memberships", payload, headers)

    def list_team_memberships(self, team_id, headers, params=None):
        return self._request("GET", f"/teams/{team_id}/memberships", headers=headers, params=params)

    def list_memberships(self, headers, params=None):
        return self._request("GET", "/memberships", headers=headers, params=params)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/memberships/{membership_id}", headers=headers)

    def release_membership(self, membership_id, headers):
        return self._request("POST", f"/memberships/{membership_id}/release", {}, headers)

    # ---- Trips ----
    def create_trip(self, team_id, payload, headers):
        return self._request("POST", f"/teams/{team_id}/trips", payload, headers)

    def list_team_trips(self, team_id, headers, params=None):
        return self._request("GET", f"/teams/{team_id}/trips", headers=headers, params=params)

    def get_trip(self, trip_id, headers):
        return self._request("GET", f"/trips/{trip_id}", headers=headers)

    def create_participant(self, trip_id, payload, headers):
        return self._request("POST", f"/trips/{trip_id}/participants", payload, headers)

    def list_trip_participants(self, trip_id, headers, params=None):
        return self._request("GET", f"/trips/{trip_id}/participants", headers=headers, params=params)

    def list_participants(self, headers, params=None):
        return self._request("GET", "/participants", headers=headers, params=params)

    def get_participant(self, participant_id, headers):
        return self._request("GET", f"/participants/{participant_id}", headers=headers)

    def withdraw_participant(self, participant_id, headers):
        return self._request("POST", f"/participants/{participant_id}/withdraw", {}, headers)

    def confirm_trip(self, trip_id, headers):
        return self._request("POST", f"/trips/{trip_id}/confirm", {}, headers)

    def cancel_trip(self, trip_id, headers):
        return self._request("POST", f"/trips/{trip_id}/cancel", {}, headers)

    # ---- Invoices ----
    def generate_invoice(self, payload, headers):
        return self._request("POST", "/invoices/generate", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/pay", {}, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/void", {}, headers)


api_client = ApiClient()
