"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Household ──
    def create_household(self, payload, headers):
        return self._request("POST", "/households", payload, headers)

    def get_household(self, household_id, headers):
        return self._request("GET", f"/households/{household_id}", headers=headers)

    def list_households(self, headers, params=None):
        return self._request("GET", "/households", headers=headers, params=params)

    # ── HouseholdMember ──
    def create_member(self, household_id, payload, headers):
        return self._request("POST", f"/households/{household_id}/members", payload, headers)

    def update_member(self, household_id, member_id, payload, headers):
        return self._request("PATCH", f"/households/{household_id}/members/{member_id}", payload, headers)

    def list_members(self, household_id, headers, params=None):
        return self._request("GET", f"/households/{household_id}/members", headers=headers, params=params)

    # ── Application ──
    def create_application(self, payload, headers):
        return self._request("POST", "/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def submit_application(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/submit", payload, headers)

    def determine_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/determine", headers=headers)

    def reopen_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/reopen", headers=headers)

    def cancel_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/cancel", headers=headers)

    def get_determination(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}/determination", headers=headers)

    # ── HealthPlan ──
    def create_health_plan(self, payload, headers):
        return self._request("POST", "/health-plans", payload, headers)

    def list_health_plans(self, headers, params=None):
        return self._request("GET", "/health-plans", headers=headers, params=params)

    def get_health_plan(self, plan_id, headers):
        return self._request("GET", f"/health-plans/{plan_id}", headers=headers)

    # ── SepRequest ──
    def create_sep_request(self, payload, headers):
        return self._request("POST", "/sep-requests", payload, headers)

    def get_sep_request(self, sep_id, headers):
        return self._request("GET", f"/sep-requests/{sep_id}", headers=headers)

    def list_sep_requests(self, headers, params=None):
        return self._request("GET", "/sep-requests", headers=headers, params=params)

    def approve_sep_request(self, sep_id, headers):
        return self._request("POST", f"/sep-requests/{sep_id}/approve", headers=headers)

    def deny_sep_request(self, sep_id, headers):
        return self._request("POST", f"/sep-requests/{sep_id}/deny", headers=headers)

    # ── Enrollment ──
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def pay_binder(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/pay-binder", headers=headers)

    def effectuate(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/effectuate", headers=headers)

    def mark_delinquent(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/mark-delinquent", headers=headers)

    def terminate_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/terminate", headers=headers)

    # ── ReconciliationRecord ──
    def create_reconciliation(self, payload, headers):
        return self._request("POST", "/reconciliations", payload, headers)

    def get_reconciliation(self, rec_id, headers):
        return self._request("GET", f"/reconciliations/{rec_id}", headers=headers)

    def list_reconciliations(self, headers, params=None):
        return self._request("GET", "/reconciliations", headers=headers, params=params)

    # ── test-driving clock ──
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
