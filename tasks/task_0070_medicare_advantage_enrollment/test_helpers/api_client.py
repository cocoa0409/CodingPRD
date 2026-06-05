"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ---- Beneficiary ----
    def create_beneficiary(self, payload, headers):
        return self._request("POST", "/beneficiaries", payload, headers)

    def get_beneficiary(self, beneficiary_id, headers):
        return self._request("GET", f"/beneficiaries/{beneficiary_id}", headers=headers)

    def list_beneficiaries(self, headers, params=None):
        return self._request("GET", "/beneficiaries", headers=headers, params=params)

    def establish_part_a(self, beneficiary_id, headers):
        return self._request("POST", f"/beneficiaries/{beneficiary_id}/establish-part-a",
                             {}, headers)

    def fraud_hold(self, beneficiary_id, headers):
        return self._request("POST", f"/beneficiaries/{beneficiary_id}/fraud-hold", {}, headers)

    def clear_hold(self, beneficiary_id, headers):
        return self._request("POST", f"/beneficiaries/{beneficiary_id}/clear-hold", {}, headers)

    def record_death(self, beneficiary_id, headers):
        return self._request("POST", f"/beneficiaries/{beneficiary_id}/record-death", {}, headers)

    # ---- EnrollmentPeriod ----
    def create_enrollment_period(self, beneficiary_id, payload, headers):
        return self._request("POST", f"/beneficiaries/{beneficiary_id}/enrollment-periods",
                             payload, headers)

    def list_enrollment_periods(self, beneficiary_id, headers, params=None):
        return self._request("GET", f"/beneficiaries/{beneficiary_id}/enrollment-periods",
                             headers=headers, params=params)

    def get_enrollment_period(self, period_id, headers):
        return self._request("GET", f"/enrollment-periods/{period_id}", headers=headers)

    # ---- Plan ----
    def create_plan(self, payload, headers):
        return self._request("POST", "/plans", payload, headers)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/plans/{plan_id}", headers=headers)

    def retire_plan(self, plan_id, headers):
        return self._request("POST", f"/plans/{plan_id}/retire", {}, headers)

    # ---- PartBEnrollment ----
    def create_part_b_enrollment(self, payload, headers):
        return self._request("POST", "/part-b-enrollments", payload, headers)

    def list_part_b_enrollments(self, headers, params=None):
        return self._request("GET", "/part-b-enrollments", headers=headers, params=params)

    def get_part_b_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/part-b-enrollments/{enrollment_id}", headers=headers)

    def activate_part_b_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/part-b-enrollments/{enrollment_id}/activate", {}, headers)

    def drop_part_b_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/part-b-enrollments/{enrollment_id}/drop", {}, headers)

    # ---- PartCEnrollment ----
    def create_part_c_enrollment(self, payload, headers):
        return self._request("POST", "/part-c-enrollments", payload, headers)

    def list_part_c_enrollments(self, headers, params=None):
        return self._request("GET", "/part-c-enrollments", headers=headers, params=params)

    def get_part_c_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/part-c-enrollments/{enrollment_id}", headers=headers)

    def confirm_part_c_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"/part-c-enrollments/{enrollment_id}/confirm",
                             payload, headers)

    def disenroll_part_c_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/part-c-enrollments/{enrollment_id}/disenroll", {}, headers)

    # ---- PartDEnrollment ----
    def create_part_d_enrollment(self, payload, headers):
        return self._request("POST", "/part-d-enrollments", payload, headers)

    def list_part_d_enrollments(self, headers, params=None):
        return self._request("GET", "/part-d-enrollments", headers=headers, params=params)

    def get_part_d_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/part-d-enrollments/{enrollment_id}", headers=headers)

    def confirm_part_d_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/part-d-enrollments/{enrollment_id}/confirm", {}, headers)

    def disenroll_part_d_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/part-d-enrollments/{enrollment_id}/disenroll", {}, headers)

    def post_drug_claim(self, enrollment_id, payload, headers):
        return self._request("POST", f"/part-d-enrollments/{enrollment_id}/claims",
                             payload, headers)

    def list_drug_claims(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/part-d-enrollments/{enrollment_id}/claims",
                             headers=headers, params=params)

    # ---- MedigapPolicy ----
    def create_medigap_policy(self, payload, headers):
        return self._request("POST", "/medigap-policies", payload, headers)

    def list_medigap_policies(self, headers, params=None):
        return self._request("GET", "/medigap-policies", headers=headers, params=params)

    def get_medigap_policy(self, policy_id, headers):
        return self._request("GET", f"/medigap-policies/{policy_id}", headers=headers)

    def lapse_medigap_policy(self, policy_id, headers):
        return self._request("POST", f"/medigap-policies/{policy_id}/lapse", {}, headers)

    # ---- PenaltyAssessment ----
    def create_penalty_assessment(self, payload, headers):
        return self._request("POST", "/penalty-assessments", payload, headers)

    def list_penalty_assessments(self, headers, params=None):
        return self._request("GET", "/penalty-assessments", headers=headers, params=params)

    def get_penalty_assessment(self, assessment_id, headers):
        return self._request("GET", f"/penalty-assessments/{assessment_id}", headers=headers)

    def waive_penalty_assessment(self, assessment_id, headers):
        return self._request("POST", f"/penalty-assessments/{assessment_id}/waive", {}, headers)


api_client = ApiClient()
