"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient

_PREFIX = "/montessori"


class ApiClient(GenericApiClient):
    # ─── Logical clock ────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", f"{_PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    def get_clock(self, headers):
        return self._request("GET", f"{_PREFIX}/_clock", headers=headers)

    # ─── TuitionTier ──────────────────────────────────
    def create_tier(self, payload, headers):
        return self._request("POST", f"{_PREFIX}/tiers", payload, headers)

    def get_tier(self, tier_id, headers):
        return self._request("GET", f"{_PREFIX}/tiers/{tier_id}", headers=headers)

    def list_tiers(self, headers, params=None):
        return self._request("GET", f"{_PREFIX}/tiers", headers=headers, params=params)

    # ─── Classroom ────────────────────────────────────
    def create_classroom(self, payload, headers):
        return self._request("POST", f"{_PREFIX}/classrooms", payload, headers)

    def get_classroom(self, classroom_id, headers):
        return self._request("GET", f"{_PREFIX}/classrooms/{classroom_id}", headers=headers)

    def list_classrooms(self, headers, params=None):
        return self._request("GET", f"{_PREFIX}/classrooms", headers=headers, params=params)

    def list_classroom_staff_assignments(self, classroom_id, headers, params=None):
        return self._request(
            "GET", f"{_PREFIX}/classrooms/{classroom_id}/staff-assignments",
            headers=headers, params=params,
        )

    def promote_waitlist(self, classroom_id, headers):
        return self._request(
            "POST", f"{_PREFIX}/classrooms/{classroom_id}/promote-waitlist",
            {}, headers,
        )

    # ─── Student ──────────────────────────────────────
    def create_student(self, payload, headers):
        return self._request("POST", f"{_PREFIX}/students", payload, headers)

    def get_student(self, student_id, headers):
        return self._request("GET", f"{_PREFIX}/students/{student_id}", headers=headers)

    def list_students(self, headers, params=None):
        return self._request("GET", f"{_PREFIX}/students", headers=headers, params=params)

    # ─── Application ──────────────────────────────────
    def create_application(self, payload, headers):
        return self._request("POST", f"{_PREFIX}/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"{_PREFIX}/applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", f"{_PREFIX}/applications", headers=headers, params=params)

    def start_review(self, application_id, headers):
        return self._request(
            "POST", f"{_PREFIX}/applications/{application_id}/start-review", {}, headers)

    def request_changes(self, application_id, headers):
        return self._request(
            "POST", f"{_PREFIX}/applications/{application_id}/request-changes", {}, headers)

    def resubmit(self, application_id, headers):
        return self._request(
            "POST", f"{_PREFIX}/applications/{application_id}/resubmit", {}, headers)

    def waitlist(self, application_id, headers):
        return self._request(
            "POST", f"{_PREFIX}/applications/{application_id}/waitlist", {}, headers)

    def offer(self, application_id, headers):
        return self._request(
            "POST", f"{_PREFIX}/applications/{application_id}/offer", {}, headers)

    def decline(self, application_id, headers):
        return self._request(
            "POST", f"{_PREFIX}/applications/{application_id}/decline", {}, headers)

    def accept_offer(self, application_id, payload, headers):
        return self._request(
            "POST", f"{_PREFIX}/applications/{application_id}/accept-offer", payload, headers)

    def decline_offer(self, application_id, headers):
        return self._request(
            "POST", f"{_PREFIX}/applications/{application_id}/decline-offer", {}, headers)

    # ─── Enrollment ───────────────────────────────────
    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"{_PREFIX}/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", f"{_PREFIX}/enrollments", headers=headers, params=params)

    def leave(self, enrollment_id, headers):
        return self._request(
            "POST", f"{_PREFIX}/enrollments/{enrollment_id}/leave", {}, headers)

    def return_from_leave(self, enrollment_id, headers):
        return self._request(
            "POST", f"{_PREFIX}/enrollments/{enrollment_id}/return", {}, headers)

    def withdraw(self, enrollment_id, headers):
        return self._request(
            "POST", f"{_PREFIX}/enrollments/{enrollment_id}/withdraw", {}, headers)

    def mark_past_due(self, enrollment_id, headers):
        return self._request(
            "POST", f"{_PREFIX}/enrollments/{enrollment_id}/mark-past-due", {}, headers)

    # ─── Payment ──────────────────────────────────────
    def create_payment(self, payload, headers):
        return self._request("POST", f"{_PREFIX}/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"{_PREFIX}/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", f"{_PREFIX}/payments", headers=headers, params=params)

    # ─── RefundRequest ────────────────────────────────
    def create_refund_request(self, payload, headers):
        return self._request("POST", f"{_PREFIX}/refund-requests", payload, headers)

    def get_refund_request(self, refund_id, headers):
        return self._request("GET", f"{_PREFIX}/refund-requests/{refund_id}", headers=headers)

    def list_refund_requests(self, headers, params=None):
        return self._request("GET", f"{_PREFIX}/refund-requests", headers=headers, params=params)

    def approve_refund(self, refund_id, headers):
        return self._request(
            "POST", f"{_PREFIX}/refund-requests/{refund_id}/approve", {}, headers)

    def pay_refund(self, refund_id, headers):
        return self._request(
            "POST", f"{_PREFIX}/refund-requests/{refund_id}/pay", {}, headers)

    def void_refund(self, refund_id, headers):
        return self._request(
            "POST", f"{_PREFIX}/refund-requests/{refund_id}/void", {}, headers)

    # ─── StaffAssignment ──────────────────────────────
    def create_staff_assignment(self, payload, headers):
        return self._request("POST", f"{_PREFIX}/staff-assignments", payload, headers)

    def get_staff_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"{_PREFIX}/staff-assignments/{assignment_id}", headers=headers)

    def end_staff_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"{_PREFIX}/staff-assignments/{assignment_id}/end", payload, headers)

    # ─── AssessmentRecord ─────────────────────────────
    def create_assessment_record(self, payload, headers):
        return self._request("POST", f"{_PREFIX}/assessment-records", payload, headers)

    def get_assessment_record(self, record_id, headers):
        return self._request(
            "GET", f"{_PREFIX}/assessment-records/{record_id}", headers=headers)

    def list_assessment_records(self, headers, params=None):
        return self._request(
            "GET", f"{_PREFIX}/assessment-records", headers=headers, params=params)

    # ─── ConferenceSlot ───────────────────────────────
    def create_conference_slot(self, payload, headers):
        return self._request("POST", f"{_PREFIX}/conference-slots", payload, headers)

    def get_conference_slot(self, slot_id, headers):
        return self._request("GET", f"{_PREFIX}/conference-slots/{slot_id}", headers=headers)

    def list_conference_slots(self, headers, params=None):
        return self._request(
            "GET", f"{_PREFIX}/conference-slots", headers=headers, params=params)

    def book_slot(self, slot_id, payload, headers):
        return self._request(
            "POST", f"{_PREFIX}/conference-slots/{slot_id}/book", payload, headers)

    def complete_slot(self, slot_id, headers):
        return self._request(
            "POST", f"{_PREFIX}/conference-slots/{slot_id}/complete", {}, headers)

    def no_show_slot(self, slot_id, headers):
        return self._request(
            "POST", f"{_PREFIX}/conference-slots/{slot_id}/no-show", {}, headers)

    def cancel_slot(self, slot_id, headers):
        return self._request(
            "POST", f"{_PREFIX}/conference-slots/{slot_id}/cancel", {}, headers)

    # ─── Observation ──────────────────────────────────
    def create_observation(self, payload, headers):
        return self._request("POST", f"{_PREFIX}/observations", payload, headers)

    def get_observation(self, observation_id, headers):
        return self._request("GET", f"{_PREFIX}/observations/{observation_id}", headers=headers)

    def list_observations(self, headers, params=None):
        return self._request("GET", f"{_PREFIX}/observations", headers=headers, params=params)


api_client = ApiClient()
