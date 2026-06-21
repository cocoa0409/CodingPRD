"""API client: one method per endpoint defined in the PRD (PRD §4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Clock (PRD §2.8) ──────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Instructor (PRD §3.1) ─────────────────────────────────────
    def create_instructor(self, payload, headers):
        return self._request("POST", "/instructors", payload, headers)

    def get_instructor(self, instructor_id, headers):
        return self._request("GET", f"/instructors/{instructor_id}", headers=headers)

    # ─── Learner (PRD §3.1) ────────────────────────────────────────
    def create_learner(self, payload, headers):
        return self._request("POST", "/learners", payload, headers)

    def get_learner(self, learner_id, headers):
        return self._request("GET", f"/learners/{learner_id}", headers=headers)

    # ─── Course (PRD §3.2, §3.3) ───────────────────────────────────
    def create_course(self, payload, headers):
        return self._request("POST", "/courses", payload, headers)

    def get_course(self, course_id, headers):
        return self._request("GET", f"/courses/{course_id}", headers=headers)

    def list_courses(self, headers, params=None):
        return self._request("GET", "/courses", headers=headers, params=params)

    def publish_course(self, course_id, headers, payload=None):
        return self._request(
            "POST", f"/courses/{course_id}/publish",
            payload if payload is not None else {}, headers,
        )

    def unpublish_course(self, course_id, headers, payload=None):
        return self._request(
            "POST", f"/courses/{course_id}/unpublish",
            payload if payload is not None else {}, headers,
        )

    def retire_course(self, course_id, headers, payload=None):
        return self._request(
            "POST", f"/courses/{course_id}/retire",
            payload if payload is not None else {}, headers,
        )

    # ─── Lesson (PRD §3.2) ─────────────────────────────────────────
    def create_lesson(self, payload, headers):
        return self._request("POST", "/lessons", payload, headers)

    def get_lesson(self, lesson_id, headers):
        return self._request("GET", f"/lessons/{lesson_id}", headers=headers)

    def list_lessons(self, headers, params=None):
        return self._request("GET", "/lessons", headers=headers, params=params)

    # ─── Coupon (PRD §3.5) ─────────────────────────────────────────
    def create_coupon(self, payload, headers):
        return self._request("POST", "/coupons", payload, headers)

    def get_coupon(self, coupon_id, headers):
        return self._request("GET", f"/coupons/{coupon_id}", headers=headers)

    def list_coupons(self, headers, params=None):
        return self._request("GET", "/coupons", headers=headers, params=params)

    def disable_coupon(self, coupon_id, headers, payload=None):
        return self._request(
            "POST", f"/coupons/{coupon_id}/disable",
            payload if payload is not None else {}, headers,
        )

    # ─── Bundle (PRD §3.6) ─────────────────────────────────────────
    def create_bundle(self, payload, headers):
        return self._request("POST", "/bundles", payload, headers)

    def get_bundle(self, bundle_id, headers):
        return self._request("GET", f"/bundles/{bundle_id}", headers=headers)

    def list_bundles(self, headers, params=None):
        return self._request("GET", "/bundles", headers=headers, params=params)

    def enroll_bundle(self, bundle_id, payload, headers):
        return self._request("POST", f"/bundles/{bundle_id}/enroll", payload, headers)

    # ─── Enrollment (PRD §3.4, §3.9) ───────────────────────────────
    def enroll_course(self, course_id, payload, headers):
        return self._request("POST", f"/courses/{course_id}/enroll", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def refund_enrollment(self, enrollment_id, headers, payload=None):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/refund",
            payload if payload is not None else {}, headers,
        )

    def list_enrollment_lesson_completions(self, enrollment_id, headers, params=None):
        return self._request(
            "GET", f"/enrollments/{enrollment_id}/lesson-completions",
            headers=headers, params=params,
        )

    def get_enrollment_certificate(self, enrollment_id, headers):
        return self._request(
            "GET", f"/enrollments/{enrollment_id}/certificate", headers=headers
        )

    # ─── LessonCompletion (PRD §3.7) ───────────────────────────────
    def create_lesson_completion(self, payload, headers):
        return self._request("POST", "/lesson-completions", payload, headers)

    def get_lesson_completion(self, completion_id, headers):
        return self._request(
            "GET", f"/lesson-completions/{completion_id}", headers=headers
        )

    def list_lesson_completions(self, headers, params=None):
        return self._request(
            "GET", "/lesson-completions", headers=headers, params=params
        )

    # ─── Certificate (PRD §3.8) ────────────────────────────────────
    def get_certificate(self, certificate_id, headers):
        return self._request("GET", f"/certificates/{certificate_id}", headers=headers)

    def list_certificates(self, headers, params=None):
        return self._request("GET", "/certificates", headers=headers, params=params)

    # ─── Review (PRD §3.10) ────────────────────────────────────────
    def create_review(self, payload, headers):
        return self._request("POST", "/reviews", payload, headers)

    def get_review(self, review_id, headers):
        return self._request("GET", f"/reviews/{review_id}", headers=headers)

    def list_reviews(self, headers, params=None):
        return self._request("GET", "/reviews", headers=headers, params=params)

    def hide_review(self, review_id, headers, payload=None):
        return self._request(
            "POST", f"/reviews/{review_id}/hide",
            payload if payload is not None else {}, headers,
        )

    def unhide_review(self, review_id, headers, payload=None):
        return self._request(
            "POST", f"/reviews/{review_id}/unhide",
            payload if payload is not None else {}, headers,
        )

    def retract_review(self, review_id, headers, payload=None):
        return self._request(
            "POST", f"/reviews/{review_id}/retract",
            payload if payload is not None else {}, headers,
        )

    # ─── Payout & Ledger (PRD §3.11, §2.7) ─────────────────────────
    def create_payout(self, payload, headers):
        return self._request("POST", "/payouts", payload, headers)

    def get_payout(self, payout_id, headers):
        return self._request("GET", f"/payouts/{payout_id}", headers=headers)

    def list_payouts(self, headers, params=None):
        return self._request("GET", "/payouts", headers=headers, params=params)

    def approve_payout(self, payout_id, payload, headers):
        return self._request(
            "POST", f"/payouts/{payout_id}/approve", payload, headers
        )

    def reject_payout(self, payout_id, headers, payload=None):
        return self._request(
            "POST", f"/payouts/{payout_id}/reject",
            payload if payload is not None else {}, headers,
        )

    def get_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/ledger-entries/{entry_id}", headers=headers)

    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/ledger-entries", headers=headers, params=params)


api_client = ApiClient()
