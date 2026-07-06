"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; the base _request() handles the
HTTP envelope, base URL and JSON serialization.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # --- Logical clock ------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- School -------------------------------------------------------------
    def create_school(self, payload, headers):
        return self._request("POST", "/schools", payload, headers)

    def list_schools(self, headers, params=None):
        return self._request("GET", "/schools", headers=headers, params=params)

    def get_school(self, school_id, headers):
        return self._request("GET", f"/schools/{school_id}", headers=headers)

    def set_storm_advisory(self, school_id, payload, headers):
        return self._request("POST", f"/schools/{school_id}/storm-advisory",
                             payload, headers)

    # --- Course -------------------------------------------------------------
    def create_course(self, payload, headers):
        return self._request("POST", "/courses", payload, headers)

    def list_courses(self, headers, params=None):
        return self._request("GET", "/courses", headers=headers, params=params)

    def get_course(self, course_id, headers):
        return self._request("GET", f"/courses/{course_id}", headers=headers)

    # --- CourseLevel --------------------------------------------------------
    def create_level(self, payload, headers):
        return self._request("POST", "/levels", payload, headers)

    def list_levels(self, headers, params=None):
        return self._request("GET", "/levels", headers=headers, params=params)

    def get_level(self, level_id, headers):
        return self._request("GET", f"/levels/{level_id}", headers=headers)

    # --- Instructor ---------------------------------------------------------
    def create_instructor(self, payload, headers):
        return self._request("POST", "/instructors", payload, headers)

    def list_instructors(self, headers, params=None):
        return self._request("GET", "/instructors", headers=headers, params=params)

    def get_instructor(self, instructor_id, headers):
        return self._request("GET", f"/instructors/{instructor_id}", headers=headers)

    # --- Equipment ----------------------------------------------------------
    def create_equipment(self, payload, headers):
        return self._request("POST", "/equipment", payload, headers)

    def list_equipment(self, headers, params=None):
        return self._request("GET", "/equipment", headers=headers, params=params)

    def get_equipment(self, equipment_id, headers):
        return self._request("GET", f"/equipment/{equipment_id}", headers=headers)

    def toggle_maintenance(self, equipment_id, payload, headers):
        return self._request("POST", f"/equipment/{equipment_id}/maintenance",
                             payload, headers)

    # --- Student ------------------------------------------------------------
    def create_student(self, payload, headers):
        return self._request("POST", "/students", payload, headers)

    def list_students(self, headers, params=None):
        return self._request("GET", "/students", headers=headers, params=params)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/students/{student_id}", headers=headers)

    def record_swim_test(self, student_id, payload, headers):
        return self._request("POST", f"/students/{student_id}/swim-test",
                             payload, headers)

    # --- Waiver -------------------------------------------------------------
    def create_waiver(self, payload, headers):
        return self._request("POST", "/waivers", payload, headers)

    def list_waivers(self, headers, params=None):
        return self._request("GET", "/waivers", headers=headers, params=params)

    def get_waiver(self, waiver_id, headers):
        return self._request("GET", f"/waivers/{waiver_id}", headers=headers)

    def revoke_waiver(self, waiver_id, headers):
        return self._request("POST", f"/waivers/{waiver_id}/revoke", headers=headers)

    # --- Membership ---------------------------------------------------------
    def create_membership(self, payload, headers):
        return self._request("POST", "/memberships", payload, headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", "/memberships", headers=headers, params=params)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/memberships/{membership_id}", headers=headers)

    # --- Enrollment ---------------------------------------------------------
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/enrollments", payload, headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def pay_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/pay", headers=headers)

    def withdraw_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/withdraw", headers=headers)

    def refund_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/refund", headers=headers)

    def complete_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/complete", headers=headers)

    # --- Session ------------------------------------------------------------
    def create_session(self, payload, headers):
        return self._request("POST", "/sessions", payload, headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/sessions", headers=headers, params=params)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/sessions/{session_id}", headers=headers)

    def weather_hold_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/weather-hold", headers=headers)

    def clear_hold_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/clear-hold", headers=headers)

    def start_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/start", headers=headers)

    def complete_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/complete", headers=headers)

    def cancel_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/cancel", headers=headers)

    # --- SessionBooking -----------------------------------------------------
    def create_booking(self, payload, headers):
        return self._request("POST", "/bookings", payload, headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/bookings", headers=headers, params=params)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def check_in_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/check-in", headers=headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/cancel", headers=headers)

    # --- RentalAgreement ----------------------------------------------------
    def create_rental(self, payload, headers):
        return self._request("POST", "/rentals", payload, headers)

    def list_rentals(self, headers, params=None):
        return self._request("GET", "/rentals", headers=headers, params=params)

    def get_rental(self, rental_id, headers):
        return self._request("GET", f"/rentals/{rental_id}", headers=headers)

    def checkout_rental(self, rental_id, headers):
        return self._request("POST", f"/rentals/{rental_id}/checkout", headers=headers)

    def return_rental(self, rental_id, headers):
        return self._request("POST", f"/rentals/{rental_id}/return", headers=headers)

    def cancel_rental(self, rental_id, headers):
        return self._request("POST", f"/rentals/{rental_id}/cancel", headers=headers)

    # --- CertificationCard --------------------------------------------------
    def list_certification_cards(self, headers, params=None):
        return self._request("GET", "/certification-cards", headers=headers, params=params)

    def get_certification_card(self, card_id, headers):
        return self._request("GET", f"/certification-cards/{card_id}", headers=headers)


api_client = ApiClient()
