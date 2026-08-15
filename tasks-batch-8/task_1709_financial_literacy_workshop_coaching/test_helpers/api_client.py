"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock -------------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- curriculum modules --------------------------------------------------
    def create_curriculum_module(self, payload, headers):
        return self._request("POST", "/curriculum-modules", payload, headers)

    def get_curriculum_module(self, module_id, headers):
        return self._request("GET", f"/curriculum-modules/{module_id}", headers=headers)

    def retire_curriculum_module(self, module_id, headers):
        return self._request("POST", f"/curriculum-modules/{module_id}/retire", {}, headers)

    # --- coaches -------------------------------------------------------------
    def create_coach(self, payload, headers):
        return self._request("POST", "/coaches", payload, headers)

    def get_coach(self, coach_id, headers):
        return self._request("GET", f"/coaches/{coach_id}", headers=headers)

    def certify_coach(self, coach_id, headers):
        return self._request("POST", f"/coaches/{coach_id}/certify", {}, headers)

    def suspend_coach(self, coach_id, headers):
        return self._request("POST", f"/coaches/{coach_id}/suspend", {}, headers)

    def reinstate_coach(self, coach_id, headers):
        return self._request("POST", f"/coaches/{coach_id}/reinstate", {}, headers)

    # --- participants ----------------------------------------------------------
    def create_participant(self, payload, headers):
        return self._request("POST", "/participants", payload, headers)

    def get_participant(self, participant_id, headers):
        return self._request("GET", f"/participants/{participant_id}", headers=headers)

    def clear_participant_restriction(self, participant_id, headers):
        return self._request("POST", f"/participants/{participant_id}/clear-restriction", {}, headers)

    def exit_participant(self, participant_id, headers):
        return self._request("POST", f"/participants/{participant_id}/exit", {}, headers)

    def get_incentive_summary(self, participant_id, headers):
        return self._request("GET", f"/participants/{participant_id}/incentive-summary", headers=headers)

    # --- workshops -------------------------------------------------------------
    def create_workshop(self, payload, headers):
        return self._request("POST", "/workshops", payload, headers)

    def list_workshops(self, headers, params=None):
        return self._request("GET", "/workshops", headers=headers, params=params)

    def get_workshop(self, workshop_id, headers):
        return self._request("GET", f"/workshops/{workshop_id}", headers=headers)

    def patch_workshop(self, workshop_id, payload, headers):
        return self._request("PATCH", f"/workshops/{workshop_id}", payload, headers)

    def cancel_workshop(self, workshop_id, headers):
        return self._request("POST", f"/workshops/{workshop_id}/cancel", {}, headers)

    # --- registrations -----------------------------------------------------------
    def create_registration(self, payload, headers):
        return self._request("POST", "/registrations", payload, headers)

    def list_registrations(self, headers, params=None):
        return self._request("GET", "/registrations", headers=headers, params=params)

    def get_registration(self, registration_id, headers):
        return self._request("GET", f"/registrations/{registration_id}", headers=headers)

    def cancel_registration(self, registration_id, headers):
        return self._request("POST", f"/registrations/{registration_id}/cancel", {}, headers)

    def mark_attendance(self, registration_id, payload, headers):
        return self._request("POST", f"/registrations/{registration_id}/mark-attendance", payload, headers)

    # --- coaching cases ------------------------------------------------------------
    def create_coaching_case(self, payload, headers):
        return self._request("POST", "/coaching-cases", payload, headers)

    def list_coaching_cases(self, headers, params=None):
        return self._request("GET", "/coaching-cases", headers=headers, params=params)

    def get_coaching_case(self, case_id, headers):
        return self._request("GET", f"/coaching-cases/{case_id}", headers=headers)

    def transition_coaching_case(self, case_id, payload, headers):
        return self._request("POST", f"/coaching-cases/{case_id}/transition", payload, headers)

    # --- goal plans ------------------------------------------------------------------
    def create_goal_plan(self, payload, headers):
        return self._request("POST", "/goal-plans", payload, headers)

    def list_goal_plans(self, headers, params=None):
        return self._request("GET", "/goal-plans", headers=headers, params=params)

    def get_goal_plan(self, plan_id, headers):
        return self._request("GET", f"/goal-plans/{plan_id}", headers=headers)

    # --- outcome snapshots -------------------------------------------------------------
    def create_outcome_snapshot(self, payload, headers):
        return self._request("POST", "/outcome-snapshots", payload, headers)

    def list_outcome_snapshots(self, headers, params=None):
        return self._request("GET", "/outcome-snapshots", headers=headers, params=params)

    def get_outcome_snapshot(self, snapshot_id, headers):
        return self._request("GET", f"/outcome-snapshots/{snapshot_id}", headers=headers)

    # --- match pools ---------------------------------------------------------------------
    def create_match_pool(self, payload, headers):
        return self._request("POST", "/match-pools", payload, headers)

    def get_match_pool(self, pool_id, headers):
        return self._request("GET", f"/match-pools/{pool_id}", headers=headers)

    def close_match_pool(self, pool_id, headers):
        return self._request("POST", f"/match-pools/{pool_id}/close", {}, headers)

    # --- match enrollments ------------------------------------------------------------------
    def create_match_enrollment(self, payload, headers):
        return self._request("POST", "/match-enrollments", payload, headers)

    def list_match_enrollments(self, headers, params=None):
        return self._request("GET", "/match-enrollments", headers=headers, params=params)

    def get_match_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/match-enrollments/{enrollment_id}", headers=headers)

    def create_deposit(self, enrollment_id, payload, headers):
        return self._request("POST", f"/match-enrollments/{enrollment_id}/deposits", payload, headers)

    def payout_match_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/match-enrollments/{enrollment_id}/payout", {}, headers)

    def forfeit_match_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/match-enrollments/{enrollment_id}/forfeit", {}, headers)

    # --- referrals ---------------------------------------------------------------------------
    def create_referral(self, payload, headers):
        return self._request("POST", "/referrals", payload, headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/referrals", headers=headers, params=params)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/referrals/{referral_id}", headers=headers)

    def transition_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/referrals/{referral_id}/transition", payload, headers)

    # --- funder reports -------------------------------------------------------------------------
    def create_funder_report(self, payload, headers):
        return self._request("POST", "/funder-reports", payload, headers)

    def get_funder_report(self, report_id, headers):
        return self._request("GET", f"/funder-reports/{report_id}", headers=headers)


api_client = ApiClient()
