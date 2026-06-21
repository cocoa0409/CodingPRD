"""API client: one method per endpoint defined in the PRD.

All studio-scoped paths are mounted under /studios/{studioId} (PRD 2).
Subclasses GenericApiClient; the base _request() handles the HTTP envelope.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------- Studio ----------------
    def create_studio(self, payload, headers):
        return self._request("POST", "/studios", payload, headers)

    def list_studios(self, headers, params=None):
        return self._request("GET", "/studios", headers=headers, params=params)

    def get_studio(self, studio_id, headers):
        return self._request("GET", f"/studios/{studio_id}", headers=headers)

    def set_clock(self, studio_id, payload, headers):
        return self._request(
            "POST", f"/studios/{studio_id}/_clock/set_current_utc", payload, headers
        )

    # ---------------- Family ----------------
    def create_family(self, studio_id, payload, headers):
        return self._request("POST", f"/studios/{studio_id}/families", payload, headers)

    def list_families(self, studio_id, headers, params=None):
        return self._request(
            "GET", f"/studios/{studio_id}/families", headers=headers, params=params
        )

    def get_family(self, studio_id, family_id, headers):
        return self._request(
            "GET", f"/studios/{studio_id}/families/{family_id}", headers=headers
        )

    def update_family(self, studio_id, family_id, payload, headers):
        return self._request(
            "PATCH", f"/studios/{studio_id}/families/{family_id}", payload, headers
        )

    def credit_wallet(self, studio_id, family_id, payload, headers):
        return self._request(
            "POST",
            f"/studios/{studio_id}/families/{family_id}/wallet/credits",
            payload,
            headers,
        )

    # ---------------- Student ----------------
    def create_student(self, studio_id, payload, headers):
        return self._request("POST", f"/studios/{studio_id}/students", payload, headers)

    def list_students(self, studio_id, headers, params=None):
        return self._request(
            "GET", f"/studios/{studio_id}/students", headers=headers, params=params
        )

    def get_student(self, studio_id, student_id, headers):
        return self._request(
            "GET", f"/studios/{studio_id}/students/{student_id}", headers=headers
        )

    def create_practice_log(self, studio_id, student_id, payload, headers):
        return self._request(
            "POST",
            f"/studios/{studio_id}/students/{student_id}/practice-logs",
            payload,
            headers,
        )

    # ---------------- Instructor ----------------
    def create_instructor(self, studio_id, payload, headers):
        return self._request(
            "POST", f"/studios/{studio_id}/instructors", payload, headers
        )

    def list_instructors(self, studio_id, headers, params=None):
        return self._request(
            "GET", f"/studios/{studio_id}/instructors", headers=headers, params=params
        )

    def get_instructor(self, studio_id, instructor_id, headers):
        return self._request(
            "GET", f"/studios/{studio_id}/instructors/{instructor_id}", headers=headers
        )

    def update_instructor(self, studio_id, instructor_id, payload, headers):
        return self._request(
            "PATCH",
            f"/studios/{studio_id}/instructors/{instructor_id}",
            payload,
            headers,
        )

    # ---------------- Room ----------------
    def create_room(self, studio_id, payload, headers):
        return self._request("POST", f"/studios/{studio_id}/rooms", payload, headers)

    def list_rooms(self, studio_id, headers, params=None):
        return self._request(
            "GET", f"/studios/{studio_id}/rooms", headers=headers, params=params
        )

    def get_room(self, studio_id, room_id, headers):
        return self._request(
            "GET", f"/studios/{studio_id}/rooms/{room_id}", headers=headers
        )

    # ---------------- Enrollment ----------------
    def create_enrollment(self, studio_id, payload, headers):
        return self._request(
            "POST", f"/studios/{studio_id}/enrollments", payload, headers
        )

    def list_enrollments(self, studio_id, headers, params=None):
        return self._request(
            "GET", f"/studios/{studio_id}/enrollments", headers=headers, params=params
        )

    def get_enrollment(self, studio_id, enrollment_id, headers):
        return self._request(
            "GET", f"/studios/{studio_id}/enrollments/{enrollment_id}", headers=headers
        )

    def activate_enrollment(self, studio_id, enrollment_id, payload, headers):
        return self._request(
            "POST",
            f"/studios/{studio_id}/enrollments/{enrollment_id}/activate",
            payload,
            headers,
        )

    def freeze_enrollment(self, studio_id, enrollment_id, headers):
        return self._request(
            "POST",
            f"/studios/{studio_id}/enrollments/{enrollment_id}/freeze",
            {},
            headers,
        )

    def resume_enrollment(self, studio_id, enrollment_id, payload, headers):
        return self._request(
            "POST",
            f"/studios/{studio_id}/enrollments/{enrollment_id}/resume",
            payload,
            headers,
        )

    def cancel_enrollment(self, studio_id, enrollment_id, headers):
        return self._request(
            "POST",
            f"/studios/{studio_id}/enrollments/{enrollment_id}/cancel",
            {},
            headers,
        )

    # ---------------- LessonOccurrence ----------------
    def create_occurrence(self, studio_id, payload, headers):
        return self._request(
            "POST", f"/studios/{studio_id}/lesson-occurrences", payload, headers
        )

    def list_occurrences(self, studio_id, headers, params=None):
        return self._request(
            "GET",
            f"/studios/{studio_id}/lesson-occurrences",
            headers=headers,
            params=params,
        )

    def get_occurrence(self, studio_id, occ_id, headers):
        return self._request(
            "GET", f"/studios/{studio_id}/lesson-occurrences/{occ_id}", headers=headers
        )

    def complete_occurrence(self, studio_id, occ_id, headers):
        return self._request(
            "POST",
            f"/studios/{studio_id}/lesson-occurrences/{occ_id}/complete",
            {},
            headers,
        )

    def cancel_occurrence(self, studio_id, occ_id, headers):
        return self._request(
            "POST",
            f"/studios/{studio_id}/lesson-occurrences/{occ_id}/cancel",
            {},
            headers,
        )

    def request_makeup(self, studio_id, occ_id, headers):
        return self._request(
            "POST",
            f"/studios/{studio_id}/lesson-occurrences/{occ_id}/request-makeup",
            {},
            headers,
        )

    def create_makeup_occurrence(self, studio_id, payload, headers):
        return self._request(
            "POST", f"/studios/{studio_id}/make-up-occurrences", payload, headers
        )

    # ---------------- MakeupCredit ----------------
    def list_makeup_credits(self, studio_id, headers, params=None):
        return self._request(
            "GET",
            f"/studios/{studio_id}/makeup-credits",
            headers=headers,
            params=params,
        )

    def get_makeup_credit(self, studio_id, credit_id, headers):
        return self._request(
            "GET", f"/studios/{studio_id}/makeup-credits/{credit_id}", headers=headers
        )

    # ---------------- TuitionInvoice ----------------
    def create_invoice(self, studio_id, payload, headers):
        return self._request("POST", f"/studios/{studio_id}/invoices", payload, headers)

    def list_invoices(self, studio_id, headers, params=None):
        return self._request(
            "GET", f"/studios/{studio_id}/invoices", headers=headers, params=params
        )

    def get_invoice(self, studio_id, invoice_id, headers):
        return self._request(
            "GET", f"/studios/{studio_id}/invoices/{invoice_id}", headers=headers
        )

    def finalize_invoice(self, studio_id, invoice_id, headers):
        return self._request(
            "POST",
            f"/studios/{studio_id}/invoices/{invoice_id}/finalize",
            {},
            headers,
        )

    def void_invoice(self, studio_id, invoice_id, headers):
        return self._request(
            "POST", f"/studios/{studio_id}/invoices/{invoice_id}/void", {}, headers
        )

    # ---------------- Payment ----------------
    def create_payment(self, studio_id, payload, headers):
        return self._request("POST", f"/studios/{studio_id}/payments", payload, headers)

    def list_payments(self, studio_id, headers, params=None):
        return self._request(
            "GET", f"/studios/{studio_id}/payments", headers=headers, params=params
        )

    def get_payment(self, studio_id, payment_id, headers):
        return self._request(
            "GET", f"/studios/{studio_id}/payments/{payment_id}", headers=headers
        )

    def refund_payment(self, studio_id, payment_id, headers):
        return self._request(
            "POST", f"/studios/{studio_id}/payments/{payment_id}/refund", {}, headers
        )

    # ---------------- RecitalEvent ----------------
    def create_recital_event(self, studio_id, payload, headers):
        return self._request(
            "POST", f"/studios/{studio_id}/recital-events", payload, headers
        )

    def list_recital_events(self, studio_id, headers, params=None):
        return self._request(
            "GET",
            f"/studios/{studio_id}/recital-events",
            headers=headers,
            params=params,
        )

    def get_recital_event(self, studio_id, event_id, headers):
        return self._request(
            "GET", f"/studios/{studio_id}/recital-events/{event_id}", headers=headers
        )

    def close_registration(self, studio_id, event_id, headers):
        return self._request(
            "POST",
            f"/studios/{studio_id}/recital-events/{event_id}/close-registration",
            {},
            headers,
        )

    def complete_recital_event(self, studio_id, event_id, headers):
        return self._request(
            "POST",
            f"/studios/{studio_id}/recital-events/{event_id}/complete",
            {},
            headers,
        )

    def cancel_recital_event(self, studio_id, event_id, headers):
        return self._request(
            "POST",
            f"/studios/{studio_id}/recital-events/{event_id}/cancel",
            {},
            headers,
        )

    # ---------------- RecitalRegistration ----------------
    def create_registration(self, studio_id, payload, headers):
        return self._request(
            "POST", f"/studios/{studio_id}/recital-registrations", payload, headers
        )

    def list_registrations(self, studio_id, headers, params=None):
        return self._request(
            "GET",
            f"/studios/{studio_id}/recital-registrations",
            headers=headers,
            params=params,
        )

    def get_registration(self, studio_id, reg_id, headers):
        return self._request(
            "GET",
            f"/studios/{studio_id}/recital-registrations/{reg_id}",
            headers=headers,
        )

    def withdraw_registration(self, studio_id, reg_id, headers):
        return self._request(
            "POST",
            f"/studios/{studio_id}/recital-registrations/{reg_id}/withdraw",
            {},
            headers,
        )

    # ---------------- InstrumentRental ----------------
    def create_rental(self, studio_id, payload, headers):
        return self._request(
            "POST", f"/studios/{studio_id}/instrument-rentals", payload, headers
        )

    def list_rentals(self, studio_id, headers, params=None):
        return self._request(
            "GET",
            f"/studios/{studio_id}/instrument-rentals",
            headers=headers,
            params=params,
        )

    def get_rental(self, studio_id, rental_id, headers):
        return self._request(
            "GET",
            f"/studios/{studio_id}/instrument-rentals/{rental_id}",
            headers=headers,
        )

    def activate_rental(self, studio_id, rental_id, headers):
        return self._request(
            "POST",
            f"/studios/{studio_id}/instrument-rentals/{rental_id}/activate",
            {},
            headers,
        )

    def return_rental(self, studio_id, rental_id, headers):
        return self._request(
            "POST",
            f"/studios/{studio_id}/instrument-rentals/{rental_id}/return",
            {},
            headers,
        )

    def cancel_rental(self, studio_id, rental_id, headers):
        return self._request(
            "POST",
            f"/studios/{studio_id}/instrument-rentals/{rental_id}/cancel",
            {},
            headers,
        )


api_client = ApiClient()
