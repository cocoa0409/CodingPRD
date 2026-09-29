"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient

BASE = "/care-management"


class ApiClient(GenericApiClient):
    # ─── Members (PRD §3.1) ───────────────────────────────────────────

    def create_member(self, payload, headers):
        return self._request("POST", f"{BASE}/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"{BASE}/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", f"{BASE}/members", headers=headers, params=params)

    def set_member_consent(self, member_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/members/{member_id}/consent", payload, headers
        )

    # ─── Risk stratification (PRD §3.2) ───────────────────────────────

    def create_stratification(self, member_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/members/{member_id}/stratifications", payload, headers
        )

    def list_stratifications(self, member_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/members/{member_id}/stratifications",
            headers=headers, params=params,
        )

    # ─── Utilization feed (PRD §3.1, §3.7) ────────────────────────────

    def create_transition_event(self, payload, headers):
        return self._request("POST", f"{BASE}/transition-events", payload, headers)

    def get_transition_event(self, event_id, headers):
        return self._request(
            "GET", f"{BASE}/transition-events/{event_id}", headers=headers
        )

    def list_transition_events(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/transition-events", headers=headers, params=params
        )

    # ─── Programs (PRD §3.3, §3.9) ────────────────────────────────────

    def create_program(self, payload, headers):
        return self._request("POST", f"{BASE}/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"{BASE}/programs/{program_id}", headers=headers)

    def get_accreditation_file(self, program_id, headers):
        return self._request(
            "GET", f"{BASE}/programs/{program_id}/accreditation-file", headers=headers
        )

    # ─── Care managers (PRD §3.3) ─────────────────────────────────────

    def create_care_manager(self, payload, headers):
        return self._request("POST", f"{BASE}/care-managers", payload, headers)

    def get_care_manager(self, care_manager_id, headers):
        return self._request(
            "GET", f"{BASE}/care-managers/{care_manager_id}", headers=headers
        )

    def list_care_managers(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/care-managers", headers=headers, params=params
        )

    # ─── Enrollments (PRD §3.3, §3.4, §3.9) ───────────────────────────

    def create_enrollment(self, payload, headers):
        return self._request("POST", f"{BASE}/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request(
            "GET", f"{BASE}/enrollments/{enrollment_id}", headers=headers
        )

    def list_enrollments(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/enrollments", headers=headers, params=params
        )

    def activate_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"{BASE}/enrollments/{enrollment_id}/activate", {}, headers
        )

    def transfer_enrollment(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/enrollments/{enrollment_id}/transfer", payload, headers
        )

    def disenroll_enrollment(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/enrollments/{enrollment_id}/disenroll", payload, headers
        )

    def create_roi_measurement(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/enrollments/{enrollment_id}/roi-measurements",
            payload, headers,
        )

    def list_roi_measurements(self, enrollment_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/enrollments/{enrollment_id}/roi-measurements",
            headers=headers, params=params,
        )

    # ─── Care plans, goals and interventions (PRD §3.5) ───────────────

    def create_care_plan(self, payload, headers):
        return self._request("POST", f"{BASE}/care-plans", payload, headers)

    def get_care_plan(self, care_plan_id, headers):
        return self._request("GET", f"{BASE}/care-plans/{care_plan_id}", headers=headers)

    def list_care_plans(self, headers, params=None):
        return self._request("GET", f"{BASE}/care-plans", headers=headers, params=params)

    def submit_care_plan(self, care_plan_id, headers):
        return self._request(
            "POST", f"{BASE}/care-plans/{care_plan_id}/submit", {}, headers
        )

    def review_care_plan(self, care_plan_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/care-plans/{care_plan_id}/review", payload, headers
        )

    def create_goal(self, care_plan_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/care-plans/{care_plan_id}/goals", payload, headers
        )

    def list_goals(self, care_plan_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/care-plans/{care_plan_id}/goals",
            headers=headers, params=params,
        )

    def get_goal(self, goal_id, headers):
        return self._request("GET", f"{BASE}/goals/{goal_id}", headers=headers)

    def create_intervention(self, goal_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/goals/{goal_id}/interventions", payload, headers
        )

    def list_interventions(self, goal_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/goals/{goal_id}/interventions",
            headers=headers, params=params,
        )

    def complete_intervention(self, intervention_id, headers):
        return self._request(
            "POST", f"{BASE}/interventions/{intervention_id}/complete", {}, headers
        )

    def void_intervention(self, intervention_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/interventions/{intervention_id}/void", payload, headers
        )

    # ─── Touches (PRD §3.6) ───────────────────────────────────────────

    def create_touch(self, payload, headers):
        return self._request("POST", f"{BASE}/touches", payload, headers)

    def get_touch(self, touch_id, headers):
        return self._request("GET", f"{BASE}/touches/{touch_id}", headers=headers)

    def list_touches(self, headers, params=None):
        return self._request("GET", f"{BASE}/touches", headers=headers, params=params)

    def complete_touch(self, touch_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/touches/{touch_id}/complete", payload, headers
        )

    def cancel_touch(self, touch_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/touches/{touch_id}/cancel", payload, headers
        )

    # ─── Social needs, community resources, referrals (PRD §3.8) ──────

    def create_social_need(self, payload, headers):
        return self._request("POST", f"{BASE}/social-needs", payload, headers)

    def get_social_need(self, social_need_id, headers):
        return self._request(
            "GET", f"{BASE}/social-needs/{social_need_id}", headers=headers
        )

    def list_social_needs(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/social-needs", headers=headers, params=params
        )

    def create_community_resource(self, payload, headers):
        return self._request("POST", f"{BASE}/community-resources", payload, headers)

    def get_community_resource(self, resource_id, headers):
        return self._request(
            "GET", f"{BASE}/community-resources/{resource_id}", headers=headers
        )

    def create_referral(self, payload, headers):
        return self._request("POST", f"{BASE}/referrals", payload, headers)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"{BASE}/referrals/{referral_id}", headers=headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", f"{BASE}/referrals", headers=headers, params=params)

    def decide_referral(self, referral_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/referrals/{referral_id}/decision", payload, headers
        )

    def close_referral_loop(self, referral_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/referrals/{referral_id}/close-loop", payload, headers
        )

    # ─── Logical clock (PRD §2.5) ─────────────────────────────────────

    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", f"{BASE}/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
