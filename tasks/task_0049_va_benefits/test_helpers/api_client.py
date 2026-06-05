"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Veteran ----
    def create_veteran(self, payload, headers):
        return self._request("POST", "/veterans", payload, headers)

    def get_veteran(self, veteran_id, headers):
        return self._request("GET", f"/veterans/{veteran_id}", headers=headers)

    def list_veterans(self, headers, params=None):
        return self._request("GET", "/veterans", headers=headers, params=params)

    def update_veteran(self, veteran_id, payload, headers):
        return self._request("PATCH", f"/veterans/{veteran_id}", payload, headers)

    def activate_award(self, veteran_id, payload, headers):
        return self._request(
            "POST", f"/veterans/{veteran_id}/activate-award", payload, headers
        )

    def suspend_award(self, veteran_id, headers):
        return self._request(
            "POST", f"/veterans/{veteran_id}/suspend-award", {}, headers
        )

    def get_compensation_summary(self, veteran_id, headers):
        return self._request(
            "GET", f"/veterans/{veteran_id}/compensation-summary", headers=headers
        )

    # ---- Dependent ----
    def add_dependent(self, veteran_id, payload, headers):
        return self._request(
            "POST", f"/veterans/{veteran_id}/dependents", payload, headers
        )

    def list_veteran_dependents(self, veteran_id, headers, params=None):
        return self._request(
            "GET", f"/veterans/{veteran_id}/dependents", headers=headers, params=params
        )

    def get_dependent(self, dependent_id, headers):
        return self._request("GET", f"/dependents/{dependent_id}", headers=headers)

    def list_dependents(self, headers, params=None):
        return self._request("GET", "/dependents", headers=headers, params=params)

    def remove_dependent(self, veteran_id, dependent_id, headers):
        return self._request(
            "POST",
            f"/veterans/{veteran_id}/dependents/{dependent_id}/remove",
            {},
            headers,
        )

    # ---- Claim ----
    def create_claim(self, payload, headers):
        return self._request("POST", "/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def open_development(self, claim_id, headers):
        return self._request(
            "POST", f"/claims/{claim_id}/open-development", {}, headers
        )

    def rate_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/rate", {}, headers)

    def grant_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/grant", payload, headers)

    def deny_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/deny", payload, headers)

    def remand_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/remand", {}, headers)

    def close_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/close", {}, headers)

    # ---- Condition ----
    def add_condition(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/claims/{claim_id}/conditions", payload, headers
        )

    def list_conditions(self, headers, params=None):
        return self._request("GET", "/conditions", headers=headers, params=params)

    def get_condition(self, condition_id, headers):
        return self._request("GET", f"/conditions/{condition_id}", headers=headers)

    def update_condition(self, condition_id, payload, headers):
        return self._request(
            "PATCH", f"/conditions/{condition_id}", payload, headers
        )

    # ---- School ----
    def create_school(self, payload, headers):
        return self._request("POST", "/schools", payload, headers)

    def get_school(self, school_id, headers):
        return self._request("GET", f"/schools/{school_id}", headers=headers)

    # ---- Enrollment ----
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request(
            "GET", f"/enrollments/{enrollment_id}", headers=headers
        )

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def certify_enrollment(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/certify", payload, headers
        )

    def complete_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/complete", {}, headers
        )

    def cancel_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/cancel", {}, headers
        )

    # ---- VocRehabPlan ----
    def create_voc_rehab_plan(self, payload, headers):
        return self._request("POST", "/voc-rehab-plans", payload, headers)

    def get_voc_rehab_plan(self, plan_id, headers):
        return self._request("GET", f"/voc-rehab-plans/{plan_id}", headers=headers)

    def list_voc_rehab_plans(self, headers, params=None):
        return self._request(
            "GET", "/voc-rehab-plans", headers=headers, params=params
        )

    def approve_voc_rehab_plan(self, plan_id, headers):
        return self._request(
            "POST", f"/voc-rehab-plans/{plan_id}/approve", {}, headers
        )

    def complete_voc_rehab_plan(self, plan_id, headers):
        return self._request(
            "POST", f"/voc-rehab-plans/{plan_id}/complete", {}, headers
        )

    def reject_voc_rehab_plan(self, plan_id, headers):
        return self._request(
            "POST", f"/voc-rehab-plans/{plan_id}/reject", {}, headers
        )


api_client = ApiClient()
