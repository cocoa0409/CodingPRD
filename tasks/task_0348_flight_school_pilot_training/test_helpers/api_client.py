"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; the base _request() is inherited.
List endpoints accept a `params` dict for query filters and pagination.
All paths are under the /flight-school mount.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Students ----
    def create_student(self, payload, headers):
        return self._request("POST", "/flight-school/students", payload, headers)

    def list_students(self, headers, params=None):
        return self._request("GET", "/flight-school/students", headers=headers, params=params)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/flight-school/students/{student_id}", headers=headers)

    def create_deposit(self, student_id, payload, headers):
        return self._request("POST", f"/flight-school/students/{student_id}/deposits", payload, headers)

    # ---- Deposit transactions ----
    def list_deposit_transactions(self, headers, params=None):
        return self._request("GET", "/flight-school/deposit-transactions", headers=headers, params=params)

    def get_deposit_transaction(self, deposit_transaction_id, headers):
        return self._request("GET", f"/flight-school/deposit-transactions/{deposit_transaction_id}", headers=headers)

    # ---- Instructors ----
    def create_instructor(self, payload, headers):
        return self._request("POST", "/flight-school/instructors", payload, headers)

    def list_instructors(self, headers, params=None):
        return self._request("GET", "/flight-school/instructors", headers=headers, params=params)

    def get_instructor(self, instructor_id, headers):
        return self._request("GET", f"/flight-school/instructors/{instructor_id}", headers=headers)

    # ---- Aircraft ----
    def create_aircraft(self, payload, headers):
        return self._request("POST", "/flight-school/aircraft", payload, headers)

    def list_aircraft(self, headers, params=None):
        return self._request("GET", "/flight-school/aircraft", headers=headers, params=params)

    def get_aircraft(self, aircraft_id, headers):
        return self._request("GET", f"/flight-school/aircraft/{aircraft_id}", headers=headers)

    def retire_aircraft(self, aircraft_id, headers):
        return self._request("POST", f"/flight-school/aircraft/{aircraft_id}/retire", headers=headers)

    # ---- Squawks ----
    def create_squawk(self, payload, headers):
        return self._request("POST", "/flight-school/squawks", payload, headers)

    def list_squawks(self, headers, params=None):
        return self._request("GET", "/flight-school/squawks", headers=headers, params=params)

    def get_squawk(self, squawk_id, headers):
        return self._request("GET", f"/flight-school/squawks/{squawk_id}", headers=headers)

    def resolve_squawk(self, squawk_id, headers):
        return self._request("POST", f"/flight-school/squawks/{squawk_id}/resolve", headers=headers)

    def defer_squawk(self, squawk_id, headers):
        return self._request("POST", f"/flight-school/squawks/{squawk_id}/defer", headers=headers)

    def reopen_squawk(self, squawk_id, headers):
        return self._request("POST", f"/flight-school/squawks/{squawk_id}/reopen", headers=headers)

    # ---- Syllabi ----
    def create_syllabus(self, payload, headers):
        return self._request("POST", "/flight-school/syllabi", payload, headers)

    def list_syllabi(self, headers, params=None):
        return self._request("GET", "/flight-school/syllabi", headers=headers, params=params)

    def get_syllabus(self, syllabus_id, headers):
        return self._request("GET", f"/flight-school/syllabi/{syllabus_id}", headers=headers)

    # ---- Enrollments ----
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/flight-school/enrollments", payload, headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/flight-school/enrollments", headers=headers, params=params)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/flight-school/enrollments/{enrollment_id}", headers=headers)

    def record_clearance(self, enrollment_id, payload, headers):
        return self._request("POST", f"/flight-school/enrollments/{enrollment_id}/clearance", payload, headers)

    def activate_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/flight-school/enrollments/{enrollment_id}/activate", headers=headers)

    def suspend_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/flight-school/enrollments/{enrollment_id}/suspend", headers=headers)

    def complete_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/flight-school/enrollments/{enrollment_id}/complete", headers=headers)

    def withdraw_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/flight-school/enrollments/{enrollment_id}/withdraw", headers=headers)

    # ---- Bookings ----
    def create_booking(self, payload, headers):
        return self._request("POST", "/flight-school/bookings", payload, headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/flight-school/bookings", headers=headers, params=params)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/flight-school/bookings/{booking_id}", headers=headers)

    def confirm_booking(self, booking_id, headers):
        return self._request("POST", f"/flight-school/bookings/{booking_id}/confirm", headers=headers)

    def dispatch_booking(self, booking_id, headers):
        return self._request("POST", f"/flight-school/bookings/{booking_id}/dispatch", headers=headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/flight-school/bookings/{booking_id}/cancel", headers=headers)

    def no_show_booking(self, booking_id, headers):
        return self._request("POST", f"/flight-school/bookings/{booking_id}/no-show", headers=headers)

    # ---- Flight logs ----
    def create_flight_log(self, payload, headers):
        return self._request("POST", "/flight-school/flight-logs", payload, headers)

    def list_flight_logs(self, headers, params=None):
        return self._request("GET", "/flight-school/flight-logs", headers=headers, params=params)

    def get_flight_log(self, flight_log_id, headers):
        return self._request("GET", f"/flight-school/flight-logs/{flight_log_id}", headers=headers)

    def post_flight_log(self, flight_log_id, headers):
        return self._request("POST", f"/flight-school/flight-logs/{flight_log_id}/post", headers=headers)

    def void_flight_log(self, flight_log_id, headers):
        return self._request("POST", f"/flight-school/flight-logs/{flight_log_id}/void", headers=headers)

    # ---- Stage checks ----
    def create_stage_check(self, payload, headers):
        return self._request("POST", "/flight-school/stage-checks", payload, headers)

    def list_stage_checks(self, headers, params=None):
        return self._request("GET", "/flight-school/stage-checks", headers=headers, params=params)

    def get_stage_check(self, stage_check_id, headers):
        return self._request("GET", f"/flight-school/stage-checks/{stage_check_id}", headers=headers)

    def begin_stage_check(self, stage_check_id, headers):
        return self._request("POST", f"/flight-school/stage-checks/{stage_check_id}/begin", headers=headers)

    def pass_stage_check(self, stage_check_id, headers, payload=None):
        return self._request("POST", f"/flight-school/stage-checks/{stage_check_id}/pass", payload or {}, headers)

    def fail_stage_check(self, stage_check_id, headers, payload=None):
        return self._request("POST", f"/flight-school/stage-checks/{stage_check_id}/fail", payload or {}, headers)

    # ---- Endorsements ----
    def create_endorsement(self, payload, headers):
        return self._request("POST", "/flight-school/endorsements", payload, headers)

    def list_endorsements(self, headers, params=None):
        return self._request("GET", "/flight-school/endorsements", headers=headers, params=params)

    def get_endorsement(self, endorsement_id, headers):
        return self._request("GET", f"/flight-school/endorsements/{endorsement_id}", headers=headers)

    def revoke_endorsement(self, endorsement_id, headers):
        return self._request("POST", f"/flight-school/endorsements/{endorsement_id}/revoke", headers=headers)


api_client = ApiClient()
