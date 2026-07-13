"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Contact ----
    def create_contact(self, payload, headers):
        return self._request("POST", "/contacts", payload, headers)

    def get_contact(self, contact_id, headers):
        return self._request("GET", f"/contacts/{contact_id}", headers=headers)

    def list_contacts(self, headers, params=None):
        return self._request("GET", "/contacts", headers=headers, params=params)

    def contact_state(self, contact_id, payload, headers):
        return self._request("POST", f"/contacts/{contact_id}/state", payload, headers)

    # ---- RiskScreening ----
    def create_risk_screening(self, payload, headers):
        return self._request("POST", "/risk-screenings", payload, headers)

    def get_risk_screening(self, screening_id, headers):
        return self._request("GET", f"/risk-screenings/{screening_id}", headers=headers)

    def list_risk_screenings(self, headers, params=None):
        return self._request("GET", "/risk-screenings", headers=headers, params=params)

    # ---- SafetyPlan ----
    def create_safety_plan(self, payload, headers):
        return self._request("POST", "/safety-plans", payload, headers)

    def get_safety_plan(self, safety_plan_id, headers):
        return self._request("GET", f"/safety-plans/{safety_plan_id}", headers=headers)

    def list_safety_plans(self, headers, params=None):
        return self._request("GET", "/safety-plans", headers=headers, params=params)

    def safety_plan_state(self, safety_plan_id, payload, headers):
        return self._request("POST", f"/safety-plans/{safety_plan_id}/state", payload, headers)

    # ---- MobileCrisisTeam ----
    def create_team(self, payload, headers):
        return self._request("POST", "/mobile-crisis-teams", payload, headers)

    def get_team(self, team_id, headers):
        return self._request("GET", f"/mobile-crisis-teams/{team_id}", headers=headers)

    # ---- MobileDispatch ----
    def create_dispatch(self, payload, headers):
        return self._request("POST", "/mobile-dispatches", payload, headers)

    def get_dispatch(self, dispatch_id, headers):
        return self._request("GET", f"/mobile-dispatches/{dispatch_id}", headers=headers)

    def list_dispatches(self, headers, params=None):
        return self._request("GET", "/mobile-dispatches", headers=headers, params=params)

    def dispatch_state(self, dispatch_id, payload, headers):
        return self._request("POST", f"/mobile-dispatches/{dispatch_id}/state", payload, headers)

    # ---- CrisisCenter ----
    def create_center(self, payload, headers):
        return self._request("POST", "/crisis-centers", payload, headers)

    def get_center(self, center_id, headers):
        return self._request("GET", f"/crisis-centers/{center_id}", headers=headers)

    def center_state(self, center_id, payload, headers):
        return self._request("POST", f"/crisis-centers/{center_id}/state", payload, headers)

    # ---- BedReferral ----
    def create_bed_referral(self, payload, headers):
        return self._request("POST", "/bed-referrals", payload, headers)

    def get_bed_referral(self, referral_id, headers):
        return self._request("GET", f"/bed-referrals/{referral_id}", headers=headers)

    def list_bed_referrals(self, headers, params=None):
        return self._request("GET", "/bed-referrals", headers=headers, params=params)

    def bed_referral_state(self, referral_id, payload, headers):
        return self._request("POST", f"/bed-referrals/{referral_id}/state", payload, headers)

    # ---- FollowUpTask ----
    def get_follow_up_task(self, task_id, headers):
        return self._request("GET", f"/follow-up-tasks/{task_id}", headers=headers)

    def list_follow_up_tasks(self, headers, params=None):
        return self._request("GET", "/follow-up-tasks", headers=headers, params=params)

    def follow_up_attempt(self, task_id, payload, headers):
        return self._request("POST", f"/follow-up-tasks/{task_id}/attempt", payload, headers)

    # ---- EmergencyCoordination ----
    def get_emergency_coordination(self, coord_id, headers):
        return self._request("GET", f"/emergency-coordinations/{coord_id}", headers=headers)

    def list_emergency_coordinations(self, headers, params=None):
        return self._request("GET", "/emergency-coordinations", headers=headers, params=params)

    # ---- RepeatCaller ----
    def list_repeat_callers(self, headers, params=None):
        return self._request("GET", "/repeat-callers", headers=headers, params=params)

    # ---- Clock (test-driving) ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # ---- Reporting ----
    def get_operations_report(self, headers, params=None):
        return self._request("GET", "/reports/operations", headers=headers, params=params)


api_client = ApiClient()
