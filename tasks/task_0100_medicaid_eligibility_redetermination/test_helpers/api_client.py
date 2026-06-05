"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; the base _request() handles the
HTTP transport and envelope. Each method maps to a single row in the PRD's
endpoint table.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- StateRule (configuration) ---
    def create_state_rule(self, payload, headers):
        return self._request("POST", "/state-rules", payload, headers)

    def get_state_rule(self, state_code, headers):
        return self._request("GET", f"/state-rules/{state_code}", headers=headers)

    def update_state_rule(self, state_code, payload, headers):
        return self._request("PATCH", f"/state-rules/{state_code}", payload, headers)

    # --- FplSchedule (configuration) ---
    def create_fpl_schedule(self, payload, headers):
        return self._request("POST", "/fpl-schedules", payload, headers)

    # --- Household ---
    def create_household(self, payload, headers):
        return self._request("POST", "/households", payload, headers)

    def get_household(self, household_id, headers):
        return self._request("GET", f"/households/{household_id}", headers=headers)

    # --- HouseholdMember ---
    def add_member(self, household_id, payload, headers):
        return self._request("POST", f"/households/{household_id}/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def list_members(self, household_id, headers, params=None):
        return self._request("GET", f"/households/{household_id}/members", headers=headers, params=params)

    def exclude_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/exclude", {}, headers)

    # --- IncomeSource ---
    def add_income_source(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/income-sources", payload, headers)

    def list_income_sources(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/income-sources", headers=headers, params=params)

    # --- Asset ---
    def add_asset(self, household_id, payload, headers):
        return self._request("POST", f"/households/{household_id}/assets", payload, headers)

    def list_assets(self, household_id, headers, params=None):
        return self._request("GET", f"/households/{household_id}/assets", headers=headers, params=params)

    # --- Application ---
    def create_application(self, household_id, payload, headers):
        return self._request("POST", f"/households/{household_id}/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def list_applications(self, household_id, headers, params=None):
        return self._request("GET", f"/households/{household_id}/applications", headers=headers, params=params)

    def submit_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/submit", {}, headers)

    def claim_review(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/claim-review", {}, headers)

    def request_docs(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/request-docs", {}, headers)

    def verify_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/verify", {}, headers)

    def run_determination(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/determinations", {}, headers)

    def list_determinations(self, application_id, headers, params=None):
        return self._request("GET", f"/applications/{application_id}/determinations", headers=headers, params=params)

    def decide_application(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/decide", payload, headers)

    # --- Enrollment ---
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def activate_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/activate", {}, headers)

    # --- Redetermination ---
    def create_redetermination(self, payload, headers):
        return self._request("POST", "/redeterminations", payload, headers)

    def get_redetermination(self, redetermination_id, headers):
        return self._request("GET", f"/redeterminations/{redetermination_id}", headers=headers)

    def list_redeterminations(self, headers, params=None):
        return self._request("GET", "/redeterminations", headers=headers, params=params)

    def request_info(self, redetermination_id, headers):
        return self._request("POST", f"/redeterminations/{redetermination_id}/request-info", {}, headers)

    def finalize_redetermination(self, redetermination_id, payload, headers):
        return self._request("POST", f"/redeterminations/{redetermination_id}/finalize", payload, headers)

    # --- Appeal ---
    def create_appeal(self, payload, headers):
        return self._request("POST", "/appeals", payload, headers)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/appeals/{appeal_id}", headers=headers)

    def list_appeals(self, headers, params=None):
        return self._request("GET", "/appeals", headers=headers, params=params)

    def schedule_appeal(self, appeal_id, headers):
        return self._request("POST", f"/appeals/{appeal_id}/schedule", {}, headers)

    def hear_appeal(self, appeal_id, headers):
        return self._request("POST", f"/appeals/{appeal_id}/hear", {}, headers)

    def rule_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/appeals/{appeal_id}/rule", payload, headers)

    def withdraw_appeal(self, appeal_id, headers):
        return self._request("POST", f"/appeals/{appeal_id}/withdraw", {}, headers)


api_client = ApiClient()
