"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; the base _request() is inherited.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (test-driving) ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- Diver ---
    def create_diver(self, payload, headers):
        return self._request("POST", "/divers", payload, headers)

    def get_diver(self, diver_id, headers):
        return self._request("GET", f"/divers/{diver_id}", headers=headers)

    def list_divers(self, headers, params=None):
        return self._request("GET", "/divers", headers=headers, params=params)

    # --- Waiver ---
    def create_waiver(self, payload, headers):
        return self._request("POST", "/waivers", payload, headers)

    def get_waiver(self, waiver_id, headers):
        return self._request("GET", f"/waivers/{waiver_id}", headers=headers)

    def list_waivers(self, headers, params=None):
        return self._request("GET", "/waivers", headers=headers, params=params)

    # --- CertificationCard ---
    def get_certification_card(self, card_id, headers):
        return self._request("GET", f"/certification-cards/{card_id}", headers=headers)

    def list_certification_cards(self, headers, params=None):
        return self._request(
            "GET", "/certification-cards", headers=headers, params=params
        )

    # --- Instructor ---
    def create_instructor(self, payload, headers):
        return self._request("POST", "/instructors", payload, headers)

    def get_instructor(self, instructor_id, headers):
        return self._request("GET", f"/instructors/{instructor_id}", headers=headers)

    # --- Course ---
    def create_course(self, payload, headers):
        return self._request("POST", "/courses", payload, headers)

    def get_course(self, course_id, headers):
        return self._request("GET", f"/courses/{course_id}", headers=headers)

    # --- Enrollment ---
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def set_elearning_progress(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/elearning-progress", payload, headers
        )

    def recompute_eligibility(self, enrollment_id, headers):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/recompute-eligibility", {}, headers
        )

    def issue_certification(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/issue-certification", payload, headers
        )

    def withdraw_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/withdraw", {}, headers
        )

    # --- Session ---
    def create_session(self, payload, headers):
        return self._request("POST", "/sessions", payload, headers)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/sessions/{session_id}", headers=headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/sessions", headers=headers, params=params)

    def complete_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/complete", {}, headers)

    def cancel_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/cancel", {}, headers)

    # --- SessionBooking ---
    def create_session_booking(self, payload, headers):
        return self._request("POST", "/session-bookings", payload, headers)

    def get_session_booking(self, booking_id, headers):
        return self._request(
            "GET", f"/session-bookings/{booking_id}", headers=headers
        )

    def list_session_bookings(self, headers, params=None):
        return self._request(
            "GET", "/session-bookings", headers=headers, params=params
        )

    def attend_session_booking(self, booking_id, headers):
        return self._request(
            "POST", f"/session-bookings/{booking_id}/attend", {}, headers
        )

    def cancel_session_booking(self, booking_id, headers):
        return self._request(
            "POST", f"/session-bookings/{booking_id}/cancel", {}, headers
        )

    # --- Boat ---
    def create_boat(self, payload, headers):
        return self._request("POST", "/boats", payload, headers)

    def get_boat(self, boat_id, headers):
        return self._request("GET", f"/boats/{boat_id}", headers=headers)

    # --- DiveTrip ---
    def create_dive_trip(self, payload, headers):
        return self._request("POST", "/dive-trips", payload, headers)

    def get_dive_trip(self, trip_id, headers):
        return self._request("GET", f"/dive-trips/{trip_id}", headers=headers)

    def list_dive_trips(self, headers, params=None):
        return self._request("GET", "/dive-trips", headers=headers, params=params)

    def depart_dive_trip(self, trip_id, headers):
        return self._request("POST", f"/dive-trips/{trip_id}/depart", {}, headers)

    def cancel_dive_trip(self, trip_id, headers):
        return self._request("POST", f"/dive-trips/{trip_id}/cancel", {}, headers)

    # --- TripBooking ---
    def create_trip_booking(self, payload, headers):
        return self._request("POST", "/trip-bookings", payload, headers)

    def get_trip_booking(self, booking_id, headers):
        return self._request("GET", f"/trip-bookings/{booking_id}", headers=headers)

    def list_trip_bookings(self, headers, params=None):
        return self._request("GET", "/trip-bookings", headers=headers, params=params)

    def cancel_trip_booking(self, booking_id, headers):
        return self._request(
            "POST", f"/trip-bookings/{booking_id}/cancel", {}, headers
        )

    # --- RentalAgreement ---
    def create_rental_agreement(self, payload, headers):
        return self._request("POST", "/rental-agreements", payload, headers)

    def get_rental_agreement(self, rental_id, headers):
        return self._request(
            "GET", f"/rental-agreements/{rental_id}", headers=headers
        )

    def list_rental_agreements(self, headers, params=None):
        return self._request(
            "GET", "/rental-agreements", headers=headers, params=params
        )

    def checkin_rental_agreement(self, rental_id, payload, headers):
        return self._request(
            "POST", f"/rental-agreements/{rental_id}/checkin", payload, headers
        )

    def void_rental_agreement(self, rental_id, headers):
        return self._request(
            "POST", f"/rental-agreements/{rental_id}/void", {}, headers
        )

    # --- FillService ---
    def create_fill_service(self, payload, headers):
        return self._request("POST", "/fill-services", payload, headers)

    def get_fill_service(self, fill_id, headers):
        return self._request("GET", f"/fill-services/{fill_id}", headers=headers)

    def list_fill_services(self, headers, params=None):
        return self._request("GET", "/fill-services", headers=headers, params=params)

    # --- GearServiceOrder ---
    def create_gear_service_order(self, payload, headers):
        return self._request("POST", "/gear-service-orders", payload, headers)

    def get_gear_service_order(self, order_id, headers):
        return self._request(
            "GET", f"/gear-service-orders/{order_id}", headers=headers
        )

    def list_gear_service_orders(self, headers, params=None):
        return self._request(
            "GET", "/gear-service-orders", headers=headers, params=params
        )

    def complete_gear_service_order(self, order_id, headers):
        return self._request(
            "POST", f"/gear-service-orders/{order_id}/complete", {}, headers
        )

    def cancel_gear_service_order(self, order_id, headers):
        return self._request(
            "POST", f"/gear-service-orders/{order_id}/cancel", {}, headers
        )


api_client = ApiClient()
