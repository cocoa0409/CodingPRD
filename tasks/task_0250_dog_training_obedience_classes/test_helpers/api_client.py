"""API client: one method per endpoint defined in the Dog Training & Obedience Classes PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Owners ─────────────────────────────────────────────────────────────────
    def create_owner(self, payload, headers):
        return self._request("POST", "/owners", payload, headers)

    def list_owners(self, headers, params=None):
        return self._request("GET", "/owners", headers=headers, params=params)

    def get_owner(self, owner_id, headers):
        return self._request("GET", f"/owners/{owner_id}", headers=headers)

    # ─── Dogs ───────────────────────────────────────────────────────────────────
    def create_dog(self, payload, headers):
        return self._request("POST", "/dogs", payload, headers)

    def list_dogs(self, headers, params=None):
        return self._request("GET", "/dogs", headers=headers, params=params)

    def get_dog(self, dog_id, headers):
        return self._request("GET", f"/dogs/{dog_id}", headers=headers)

    # ─── Vaccination records ────────────────────────────────────────────────────
    def create_vaccination(self, dog_id, payload, headers):
        return self._request("POST", f"/dogs/{dog_id}/vaccinations", payload, headers)

    def list_vaccinations(self, headers, params=None):
        return self._request("GET", "/vaccinations", headers=headers, params=params)

    def get_vaccination(self, vaccination_id, headers):
        return self._request("GET", f"/vaccinations/{vaccination_id}", headers=headers)

    def void_vaccination(self, vaccination_id, headers):
        return self._request("POST", f"/vaccinations/{vaccination_id}/void", headers=headers)

    # ─── Behavioral intakes ─────────────────────────────────────────────────────
    def create_behavioral_intake(self, dog_id, payload, headers):
        return self._request("POST", f"/dogs/{dog_id}/behavioral-intakes", payload, headers)

    def list_behavioral_intakes(self, headers, params=None):
        return self._request("GET", "/behavioral-intakes", headers=headers, params=params)

    def get_behavioral_intake(self, intake_id, headers):
        return self._request("GET", f"/behavioral-intakes/{intake_id}", headers=headers)

    # ─── Trainers ───────────────────────────────────────────────────────────────
    def create_trainer(self, payload, headers):
        return self._request("POST", "/trainers", payload, headers)

    def list_trainers(self, headers, params=None):
        return self._request("GET", "/trainers", headers=headers, params=params)

    def get_trainer(self, trainer_id, headers):
        return self._request("GET", f"/trainers/{trainer_id}", headers=headers)

    # ─── Class series ───────────────────────────────────────────────────────────
    def create_class_series(self, payload, headers):
        return self._request("POST", "/class-series", payload, headers)

    def list_class_series(self, headers, params=None):
        return self._request("GET", "/class-series", headers=headers, params=params)

    def get_class_series(self, series_id, headers):
        return self._request("GET", f"/class-series/{series_id}", headers=headers)

    def open_class_series(self, series_id, headers):
        return self._request("POST", f"/class-series/{series_id}/open", headers=headers)

    def close_class_series(self, series_id, headers):
        return self._request("POST", f"/class-series/{series_id}/close", headers=headers)

    def archive_class_series(self, series_id, headers):
        return self._request("POST", f"/class-series/{series_id}/archive", headers=headers)

    # ─── Class sessions ─────────────────────────────────────────────────────────
    def create_class_session(self, payload, headers):
        return self._request("POST", "/class-sessions", payload, headers)

    def list_class_sessions(self, headers, params=None):
        return self._request("GET", "/class-sessions", headers=headers, params=params)

    def get_class_session(self, session_id, headers):
        return self._request("GET", f"/class-sessions/{session_id}", headers=headers)

    def reschedule_class_session(self, session_id, payload, headers):
        return self._request("PATCH", f"/class-sessions/{session_id}", payload, headers)

    def start_class_session(self, session_id, headers):
        return self._request("POST", f"/class-sessions/{session_id}/start", headers=headers)

    def complete_class_session(self, session_id, headers):
        return self._request("POST", f"/class-sessions/{session_id}/complete", headers=headers)

    def cancel_class_session(self, session_id, headers):
        return self._request("POST", f"/class-sessions/{session_id}/cancel", headers=headers)

    def mark_attendance(self, session_id, payload, headers):
        return self._request("POST", f"/class-sessions/{session_id}/attendance", payload, headers)

    # ─── Attendance records ─────────────────────────────────────────────────────
    def list_attendance_records(self, headers, params=None):
        return self._request("GET", "/attendance-records", headers=headers, params=params)

    def get_attendance_record(self, attendance_id, headers):
        return self._request("GET", f"/attendance-records/{attendance_id}", headers=headers)

    # ─── Enrollments ────────────────────────────────────────────────────────────
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/enrollments", payload, headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def promote_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/promote", headers=headers)

    def reinstate_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/reinstate", headers=headers)

    def graduate_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/graduate", headers=headers)

    def withdraw_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/withdraw", headers=headers)

    # ─── Packages ───────────────────────────────────────────────────────────────
    def create_package(self, payload, headers):
        return self._request("POST", "/packages", payload, headers)

    def list_packages(self, headers, params=None):
        return self._request("GET", "/packages", headers=headers, params=params)

    def get_package(self, package_id, headers):
        return self._request("GET", f"/packages/{package_id}", headers=headers)

    def get_package_valuation(self, package_id, headers):
        return self._request("GET", f"/packages/{package_id}/valuation", headers=headers)

    def list_package_redemptions_for_package(self, package_id, headers, params=None):
        return self._request("GET", f"/packages/{package_id}/redemptions", headers=headers, params=params)

    def expire_package(self, package_id, headers):
        return self._request("POST", f"/packages/{package_id}/expire", headers=headers)

    # ─── Package redemptions (cross-package) ────────────────────────────────────
    def list_package_redemptions(self, headers, params=None):
        return self._request("GET", "/package-redemptions", headers=headers, params=params)

    def get_package_redemption(self, redemption_id, headers):
        return self._request("GET", f"/package-redemptions/{redemption_id}", headers=headers)

    # ─── Makeup bookings ────────────────────────────────────────────────────────
    def create_makeup_booking(self, payload, headers):
        return self._request("POST", "/makeup-bookings", payload, headers)

    def list_makeup_bookings(self, headers, params=None):
        return self._request("GET", "/makeup-bookings", headers=headers, params=params)

    def get_makeup_booking(self, makeup_id, headers):
        return self._request("GET", f"/makeup-bookings/{makeup_id}", headers=headers)

    def confirm_makeup_booking(self, makeup_id, headers):
        return self._request("POST", f"/makeup-bookings/{makeup_id}/confirm", headers=headers)

    def reject_makeup_booking(self, makeup_id, headers):
        return self._request("POST", f"/makeup-bookings/{makeup_id}/reject", headers=headers)

    def complete_makeup_booking(self, makeup_id, headers):
        return self._request("POST", f"/makeup-bookings/{makeup_id}/complete", headers=headers)

    def cancel_makeup_booking(self, makeup_id, headers):
        return self._request("POST", f"/makeup-bookings/{makeup_id}/cancel", headers=headers)

    # ─── Certificates ───────────────────────────────────────────────────────────
    def list_certificates(self, headers, params=None):
        return self._request("GET", "/certificates", headers=headers, params=params)

    def get_certificate(self, certificate_id, headers):
        return self._request("GET", f"/certificates/{certificate_id}", headers=headers)

    # ─── Logical clock (test-driving) ───────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
