"""API client: one method per endpoint defined in the PRD.

All routes are mounted under the /enrichment prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Test-driving clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/enrichment/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ---- Family ----
    def create_family(self, payload, headers):
        return self._request("POST", "/enrichment/families", payload, headers)

    def get_family(self, family_id, headers):
        return self._request("GET", f"/enrichment/families/{family_id}", headers=headers)

    def list_family_children(self, family_id, headers, params=None):
        return self._request(
            "GET", f"/enrichment/families/{family_id}/children",
            headers=headers, params=params,
        )

    def list_family_memberships(self, family_id, headers, params=None):
        return self._request(
            "GET", f"/enrichment/families/{family_id}/memberships",
            headers=headers, params=params,
        )

    # ---- Child ----
    def create_child(self, payload, headers):
        return self._request("POST", "/enrichment/children", payload, headers)

    def get_child(self, child_id, headers):
        return self._request("GET", f"/enrichment/children/{child_id}", headers=headers)

    def list_child_enrollments(self, child_id, headers, params=None):
        return self._request(
            "GET", f"/enrichment/children/{child_id}/enrollments",
            headers=headers, params=params,
        )

    def advance_child(self, child_id, payload, headers):
        return self._request(
            "POST", f"/enrichment/children/{child_id}/advance", payload, headers,
        )

    def withdraw_child(self, child_id, headers):
        return self._request(
            "POST", f"/enrichment/children/{child_id}/withdraw", {}, headers,
        )

    # ---- Membership ----
    def create_membership(self, payload, headers):
        return self._request("POST", "/enrichment/memberships", payload, headers)

    def get_membership(self, membership_id, headers):
        return self._request(
            "GET", f"/enrichment/memberships/{membership_id}", headers=headers,
        )

    def list_membership_makeup_credits(self, membership_id, headers, params=None):
        return self._request(
            "GET", f"/enrichment/memberships/{membership_id}/makeup-credits",
            headers=headers, params=params,
        )

    def list_membership_invoices(self, membership_id, headers, params=None):
        return self._request(
            "GET", f"/enrichment/memberships/{membership_id}/invoices",
            headers=headers, params=params,
        )

    def activate_membership(self, membership_id, headers):
        return self._request(
            "POST", f"/enrichment/memberships/{membership_id}/activate", {}, headers,
        )

    def freeze_membership(self, membership_id, headers):
        return self._request(
            "POST", f"/enrichment/memberships/{membership_id}/freeze", {}, headers,
        )

    def cancel_membership(self, membership_id, headers):
        return self._request(
            "POST", f"/enrichment/memberships/{membership_id}/cancel", {}, headers,
        )

    def renew_membership(self, membership_id, headers):
        return self._request(
            "POST", f"/enrichment/memberships/{membership_id}/renew", {}, headers,
        )

    # ---- Program ----
    def create_program(self, payload, headers):
        return self._request("POST", "/enrichment/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/enrichment/programs/{program_id}", headers=headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/enrichment/programs", headers=headers, params=params)

    # ---- Room ----
    def create_room(self, payload, headers):
        return self._request("POST", "/enrichment/rooms", payload, headers)

    def get_room(self, room_id, headers):
        return self._request("GET", f"/enrichment/rooms/{room_id}", headers=headers)

    def list_room_sessions(self, room_id, headers, params=None):
        return self._request(
            "GET", f"/enrichment/rooms/{room_id}/sessions",
            headers=headers, params=params,
        )

    def list_room_facility_bookings(self, room_id, headers, params=None):
        return self._request(
            "GET", f"/enrichment/rooms/{room_id}/facility-bookings",
            headers=headers, params=params,
        )

    # ---- Instructor ----
    def create_instructor(self, payload, headers):
        return self._request("POST", "/enrichment/instructors", payload, headers)

    def get_instructor(self, instructor_id, headers):
        return self._request(
            "GET", f"/enrichment/instructors/{instructor_id}", headers=headers,
        )

    def list_instructor_sessions(self, instructor_id, headers, params=None):
        return self._request(
            "GET", f"/enrichment/instructors/{instructor_id}/sessions",
            headers=headers, params=params,
        )

    def deactivate_instructor(self, instructor_id, headers):
        return self._request(
            "POST", f"/enrichment/instructors/{instructor_id}/deactivate", {}, headers,
        )

    # ---- ClassSession ----
    def create_session(self, payload, headers):
        return self._request("POST", "/enrichment/sessions", payload, headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/enrichment/sessions", headers=headers, params=params)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/enrichment/sessions/{session_id}", headers=headers)

    def list_session_enrollments(self, session_id, headers, params=None):
        return self._request(
            "GET", f"/enrichment/sessions/{session_id}/enrollments",
            headers=headers, params=params,
        )

    def list_session_attendance(self, session_id, headers, params=None):
        return self._request(
            "GET", f"/enrichment/sessions/{session_id}/attendance",
            headers=headers, params=params,
        )

    def list_attendance_records(self, headers, params=None):
        return self._request(
            "GET", "/enrichment/attendance-records", headers=headers, params=params,
        )

    def hold_session(self, session_id, payload, headers):
        return self._request(
            "POST", f"/enrichment/sessions/{session_id}/hold", payload, headers,
        )

    def cancel_session(self, session_id, headers):
        return self._request(
            "POST", f"/enrichment/sessions/{session_id}/cancel", {}, headers,
        )

    # ---- Enrollment ----
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/enrichment/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request(
            "GET", f"/enrichment/enrollments/{enrollment_id}", headers=headers,
        )

    def list_enrollment_attendance(self, enrollment_id, headers, params=None):
        return self._request(
            "GET", f"/enrichment/enrollments/{enrollment_id}/attendance",
            headers=headers, params=params,
        )

    def list_enrollments(self, headers, params=None):
        return self._request(
            "GET", "/enrichment/enrollments", headers=headers, params=params,
        )

    def cancel_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/enrichment/enrollments/{enrollment_id}/cancel", {}, headers,
        )

    def redeem_makeup(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"/enrichment/enrollments/{enrollment_id}/redeem-makeup",
            payload, headers,
        )

    # ---- FacilityBooking ----
    def create_facility_booking(self, payload, headers):
        return self._request("POST", "/enrichment/facility-bookings", payload, headers)

    def list_facility_bookings(self, headers, params=None):
        return self._request(
            "GET", "/enrichment/facility-bookings", headers=headers, params=params,
        )

    def get_facility_booking(self, booking_id, headers):
        return self._request(
            "GET", f"/enrichment/facility-bookings/{booking_id}", headers=headers,
        )

    def cancel_facility_booking(self, booking_id, headers):
        return self._request(
            "POST", f"/enrichment/facility-bookings/{booking_id}/cancel", {}, headers,
        )

    # ---- Invoice ----
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/enrichment/invoices/{invoice_id}", headers=headers)

    def pay_invoice(self, invoice_id, headers):
        return self._request(
            "POST", f"/enrichment/invoices/{invoice_id}/pay", {}, headers,
        )


api_client = ApiClient()
