"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ---- Course catalog ----
    def create_course(self, payload, headers):
        return self._request("POST", "/courses", payload, headers)

    def publish_course(self, course_id, headers):
        return self._request("POST", f"/courses/{course_id}/publish", {}, headers)

    def retire_course(self, course_id, headers):
        return self._request("POST", f"/courses/{course_id}/retire", {}, headers)

    def list_courses(self, headers, params=None):
        return self._request("GET", "/courses", headers=headers, params=params)

    def get_course(self, course_id, headers):
        return self._request("GET", f"/courses/{course_id}", headers=headers)

    def list_course_cohorts(self, course_id, headers, params=None):
        return self._request("GET", f"/courses/{course_id}/cohorts",
                             headers=headers, params=params)

    # ---- Instructors ----
    def create_instructor(self, payload, headers):
        return self._request("POST", "/instructors", payload, headers)

    def get_instructor(self, instructor_id, headers):
        return self._request("GET", f"/instructors/{instructor_id}", headers=headers)

    def list_instructor_cohorts(self, instructor_id, headers, params=None):
        return self._request("GET", f"/instructors/{instructor_id}/cohorts",
                             headers=headers, params=params)

    # ---- Cohorts ----
    def create_cohort(self, payload, headers):
        return self._request("POST", "/cohorts", payload, headers)

    def get_cohort(self, cohort_id, headers):
        return self._request("GET", f"/cohorts/{cohort_id}", headers=headers)

    def schedule_cohort(self, cohort_id, instructor_id, headers):
        return self._request("POST", f"/cohorts/{cohort_id}/schedule",
                             {"instructor_id": instructor_id}, headers)

    def start_cohort(self, cohort_id, headers):
        return self._request("POST", f"/cohorts/{cohort_id}/start", {}, headers)

    def conclude_cohort(self, cohort_id, headers):
        return self._request("POST", f"/cohorts/{cohort_id}/conclude", {}, headers)

    def cancel_cohort(self, cohort_id, headers):
        return self._request("POST", f"/cohorts/{cohort_id}/cancel", {}, headers)

    def list_cohort_enrollments(self, cohort_id, headers, params=None):
        return self._request("GET", f"/cohorts/{cohort_id}/enrollments",
                             headers=headers, params=params)

    # ---- Students ----
    def register_student(self, payload, headers):
        return self._request("POST", "/students/register", payload, headers)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/students/{student_id}", headers=headers)

    def list_student_enrollments(self, student_id, headers, params=None):
        return self._request("GET", f"/students/{student_id}/enrollments",
                             headers=headers, params=params)

    # ---- Enrollments ----
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def activate_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/activate", {}, headers)

    def cancel_enrollment(self, enrollment_id, expected_cohort_version, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/cancel",
                             {"expected_cohort_version": expected_cohort_version}, headers)

    def record_attendance(self, enrollment_id, sessions_attended, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/attendance",
                             {"sessions_attended": sessions_attended}, headers)

    def get_enrollment_analytics(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}/analytics", headers=headers)

    def get_enrollment_materials(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}/materials", headers=headers)

    def list_enrollment_practice_attempts(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/enrollments/{enrollment_id}/practice-attempts",
                             headers=headers, params=params)

    def list_enrollment_installment_plans(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/enrollments/{enrollment_id}/installment-plans",
                             headers=headers, params=params)

    def list_enrollment_guarantee_claims(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/enrollments/{enrollment_id}/guarantee-claims",
                             headers=headers, params=params)

    # ---- Practice attempts ----
    def create_practice_attempt(self, payload, headers):
        return self._request("POST", "/practice-attempts", payload, headers)

    def get_practice_attempt(self, attempt_id, headers):
        return self._request("GET", f"/practice-attempts/{attempt_id}", headers=headers)

    def score_practice_attempt(self, attempt_id, headers):
        return self._request("POST", f"/practice-attempts/{attempt_id}/score", {}, headers)

    def void_practice_attempt(self, attempt_id, headers):
        return self._request("POST", f"/practice-attempts/{attempt_id}/void", {}, headers)

    # ---- Financing ----
    def create_installment_plan(self, payload, headers):
        return self._request("POST", "/installment-plans", payload, headers)

    def get_installment_plan(self, plan_id, headers):
        return self._request("GET", f"/installment-plans/{plan_id}", headers=headers)

    def record_payment(self, plan_id, amount_cents, headers):
        return self._request("POST", f"/installment-plans/{plan_id}/payments",
                             {"amount_cents": amount_cents}, headers)

    def default_installment_plan(self, plan_id, headers):
        return self._request("POST", f"/installment-plans/{plan_id}/default", {}, headers)

    # ---- Guarantee claims ----
    def create_guarantee_claim(self, payload, headers):
        return self._request("POST", "/guarantee-claims", payload, headers)

    def get_guarantee_claim(self, claim_id, headers):
        return self._request("GET", f"/guarantee-claims/{claim_id}", headers=headers)

    def review_guarantee_claim(self, claim_id, headers):
        return self._request("POST", f"/guarantee-claims/{claim_id}/review", {}, headers)

    def approve_guarantee_claim(self, claim_id, headers):
        return self._request("POST", f"/guarantee-claims/{claim_id}/approve", {}, headers)

    def reject_guarantee_claim(self, claim_id, headers):
        return self._request("POST", f"/guarantee-claims/{claim_id}/reject", {}, headers)


api_client = ApiClient()
