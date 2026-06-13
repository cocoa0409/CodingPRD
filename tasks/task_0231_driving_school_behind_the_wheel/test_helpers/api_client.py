"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clock (test driving) ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- CoursePackage ----
    def create_course_package(self, payload, headers):
        return self._request("POST", "/course-packages", payload, headers)

    def get_course_package(self, package_id, headers):
        return self._request("GET", f"/course-packages/{package_id}", headers=headers)

    def list_course_packages(self, headers, params=None):
        return self._request("GET", "/course-packages", headers=headers, params=params)

    # ---- Student ----
    def create_student(self, payload, headers):
        return self._request("POST", "/students", payload, headers)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/students/{student_id}", headers=headers)

    def list_students(self, headers, params=None):
        return self._request("GET", "/students", headers=headers, params=params)

    def record_permit(self, student_id, payload, headers):
        return self._request(
            "POST", f"/students/{student_id}/record-permit", payload, headers
        )

    def issue_certificate(self, student_id, payload, headers):
        return self._request(
            "POST", f"/students/{student_id}/certificate", payload, headers
        )

    # ---- GuardianConsent ----
    def create_guardian_consent(self, payload, headers):
        return self._request("POST", "/guardian-consents", payload, headers)

    def get_guardian_consent(self, consent_id, headers):
        return self._request("GET", f"/guardian-consents/{consent_id}", headers=headers)

    def list_guardian_consents(self, headers, params=None):
        return self._request(
            "GET", "/guardian-consents", headers=headers, params=params
        )

    def grant_consent(self, consent_id, headers):
        return self._request(
            "POST", f"/guardian-consents/{consent_id}/grant", headers=headers
        )

    def revoke_consent(self, consent_id, headers):
        return self._request(
            "POST", f"/guardian-consents/{consent_id}/revoke", headers=headers
        )

    # ---- Enrollment ----
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def activate_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/activate", headers=headers
        )

    def complete_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/complete", headers=headers
        )

    def cancel_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/cancel", headers=headers
        )

    def refund_enrollment(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/refund", payload, headers
        )

    # ---- Instructor ----
    def create_instructor(self, payload, headers):
        return self._request("POST", "/instructors", payload, headers)

    def get_instructor(self, instructor_id, headers):
        return self._request("GET", f"/instructors/{instructor_id}", headers=headers)

    def list_instructors(self, headers, params=None):
        return self._request("GET", "/instructors", headers=headers, params=params)

    def get_payout_summary(self, instructor_id, headers, params=None):
        return self._request(
            "GET",
            f"/instructors/{instructor_id}/payout-summary",
            headers=headers,
            params=params,
        )

    # ---- Vehicle ----
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/vehicles/{vehicle_id}", headers=headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/vehicles", headers=headers, params=params)

    # ---- Lesson ----
    def create_lesson(self, payload, headers):
        return self._request("POST", "/lessons", payload, headers)

    def get_lesson(self, lesson_id, headers):
        return self._request("GET", f"/lessons/{lesson_id}", headers=headers)

    def list_lessons(self, headers, params=None):
        return self._request("GET", "/lessons", headers=headers, params=params)

    def complete_lesson(self, lesson_id, headers):
        return self._request(
            "POST", f"/lessons/{lesson_id}/complete", headers=headers
        )

    def no_show_lesson(self, lesson_id, headers):
        return self._request(
            "POST", f"/lessons/{lesson_id}/no-show", headers=headers
        )

    def cancel_lesson(self, lesson_id, headers):
        return self._request(
            "POST", f"/lessons/{lesson_id}/cancel", headers=headers
        )

    # ---- NoShowStrike ----
    def get_no_show_strike(self, strike_id, headers):
        return self._request("GET", f"/no-show-strikes/{strike_id}", headers=headers)

    def list_no_show_strikes(self, headers, params=None):
        return self._request(
            "GET", "/no-show-strikes", headers=headers, params=params
        )

    # ---- WalletEntry ----
    def get_wallet_entry(self, entry_id, headers):
        return self._request("GET", f"/wallet-entries/{entry_id}", headers=headers)

    def list_wallet_entries(self, headers, params=None):
        return self._request("GET", "/wallet-entries", headers=headers, params=params)

    def create_wallet_entry(self, payload, headers):
        return self._request("POST", "/wallet-entries", payload, headers)

    # ---- Certificate ----
    def get_certificate(self, certificate_id, headers):
        return self._request("GET", f"/certificates/{certificate_id}", headers=headers)

    def list_certificates(self, headers, params=None):
        return self._request("GET", "/certificates", headers=headers, params=params)

    def submit_certificate(self, certificate_id, headers):
        return self._request(
            "POST", f"/certificates/{certificate_id}/submit", headers=headers
        )

    def dmv_callback(self, certificate_id, payload, headers):
        return self._request(
            "POST", f"/certificates/{certificate_id}/dmv-callback", payload, headers
        )


api_client = ApiClient()
