"""API client: one method per endpoint defined in the Licensing Exam Prep PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------- LicenseProgram ----------------
    def create_license_program(self, payload, headers):
        return self._request("POST", "/license-programs", payload, headers)

    def get_license_program(self, program_id, headers):
        return self._request("GET", f"/license-programs/{program_id}", headers=headers)

    def list_license_programs(self, headers, params=None):
        return self._request("GET", "/license-programs", headers=headers, params=params)

    def add_question_item(self, program_id, payload, headers):
        return self._request("POST", f"/license-programs/{program_id}/items", payload, headers)

    def list_question_items(self, program_id, headers, params=None):
        return self._request("GET", f"/license-programs/{program_id}/items", headers=headers, params=params)

    def publish_license_program(self, program_id, headers):
        return self._request("POST", f"/license-programs/{program_id}/publish", {}, headers)

    def retire_license_program(self, program_id, headers):
        return self._request("POST", f"/license-programs/{program_id}/retire", {}, headers)

    # ---------------- SubscriptionPlan ----------------
    def create_subscription_plan(self, payload, headers):
        return self._request("POST", "/subscription-plans", payload, headers)

    def get_subscription_plan(self, plan_id, headers):
        return self._request("GET", f"/subscription-plans/{plan_id}", headers=headers)

    def archive_subscription_plan(self, plan_id, headers):
        return self._request("POST", f"/subscription-plans/{plan_id}/archive", {}, headers)

    # ---------------- CEBundle ----------------
    def create_ce_bundle(self, payload, headers):
        return self._request("POST", "/ce-bundles", payload, headers)

    def get_ce_bundle(self, bundle_id, headers):
        return self._request("GET", f"/ce-bundles/{bundle_id}", headers=headers)

    def list_ce_bundles(self, headers, params=None):
        return self._request("GET", "/ce-bundles", headers=headers, params=params)

    def list_bundle_ce_awards(self, bundle_id, headers, params=None):
        return self._request("GET", f"/ce-bundles/{bundle_id}/ce-awards", headers=headers, params=params)

    # ---------------- Learner ----------------
    def create_learner(self, payload, headers):
        return self._request("POST", "/learners", payload, headers)

    def get_learner(self, learner_id, headers):
        return self._request("GET", f"/learners/{learner_id}", headers=headers)

    # ---------------- Enrollment ----------------
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/enrollments", payload, headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def get_enrollment_analytics(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}/analytics", headers=headers)

    def activate_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/activate", {}, headers)

    def restructure_financing(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/restructure-financing", payload, headers)

    def withdraw_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/withdraw", {}, headers)

    def certify_exam(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/certify-exam", payload, headers)

    # ---------------- Installment ----------------
    def list_installments(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/enrollments/{enrollment_id}/installments", headers=headers, params=params)

    def pay_installment(self, enrollment_id, installment_id, headers):
        return self._request(
            "POST",
            f"/enrollments/{enrollment_id}/installments/{installment_id}/pay",
            {},
            headers,
        )

    # ---------------- StudyPlanDomain ----------------
    def list_domains(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/enrollments/{enrollment_id}/domains", headers=headers, params=params)

    # ---------------- PracticeSession ----------------
    def create_practice_session(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/practice-sessions", payload, headers)

    def list_practice_sessions(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/enrollments/{enrollment_id}/practice-sessions", headers=headers, params=params)

    # ---------------- MockExam ----------------
    def create_mock_exam(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/mock-exams", payload, headers)

    def list_mock_exams(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/enrollments/{enrollment_id}/mock-exams", headers=headers, params=params)

    # ---------------- CECreditAward ----------------
    def create_ce_award(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/ce-awards", payload, headers)

    def list_ce_awards(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/enrollments/{enrollment_id}/ce-awards", headers=headers, params=params)

    # ---------------- PassGuaranteeClaim ----------------
    def create_pass_guarantee_claim(self, payload, headers):
        return self._request("POST", "/pass-guarantee-claims", payload, headers)

    def get_pass_guarantee_claim(self, claim_id, headers):
        return self._request("GET", f"/pass-guarantee-claims/{claim_id}", headers=headers)

    def list_pass_guarantee_claims(self, headers, params=None):
        return self._request("GET", "/pass-guarantee-claims", headers=headers, params=params)

    def decide_pass_guarantee_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/pass-guarantee-claims/{claim_id}/decide", payload, headers)

    # ---------------- Cohort / live-review ----------------
    def create_cohort(self, payload, headers):
        return self._request("POST", "/cohorts", payload, headers)

    def get_cohort(self, cohort_id, headers):
        return self._request("GET", f"/cohorts/{cohort_id}", headers=headers)

    def list_cohorts(self, headers, params=None):
        return self._request("GET", "/cohorts", headers=headers, params=params)

    def close_cohort(self, cohort_id, headers):
        return self._request("POST", f"/cohorts/{cohort_id}/close", {}, headers)

    def create_cohort_session(self, cohort_id, payload, headers):
        return self._request("POST", f"/cohorts/{cohort_id}/sessions", payload, headers)

    def list_cohort_sessions(self, cohort_id, headers, params=None):
        return self._request("GET", f"/cohorts/{cohort_id}/sessions", headers=headers, params=params)

    def create_cohort_membership(self, cohort_id, payload, headers):
        return self._request("POST", f"/cohorts/{cohort_id}/memberships", payload, headers)

    def list_cohort_memberships(self, cohort_id, headers, params=None):
        return self._request("GET", f"/cohorts/{cohort_id}/memberships", headers=headers, params=params)

    def get_cohort_membership(self, membership_id, headers):
        return self._request("GET", f"/cohort-memberships/{membership_id}", headers=headers)

    def list_memberships_by_enrollment(self, headers, params=None):
        return self._request("GET", "/cohort-memberships", headers=headers, params=params)

    def drop_cohort_membership(self, cohort_id, membership_id, headers):
        return self._request("DELETE", f"/cohorts/{cohort_id}/memberships/{membership_id}", headers=headers)

    # ---------------- Logical clock (test-driving) ----------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
