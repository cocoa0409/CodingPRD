"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- system clock ----------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set", {"to_iso8601": to_iso8601}, headers)

    # ---- caseworkers -----------------------------------------------------
    def create_caseworker(self, payload, headers):
        return self._request("POST", "/caseworkers", payload, headers)

    def get_caseworker(self, caseworker_id, headers):
        return self._request("GET", f"/caseworkers/{caseworker_id}", headers=headers)

    def list_caseworkers(self, headers, params=None):
        return self._request("GET", "/caseworkers", headers=headers, params=params)

    # ---- referrals -------------------------------------------------------
    def create_referral(self, payload, headers):
        return self._request("POST", "/referrals", payload, headers)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/referrals/{referral_id}", headers=headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/referrals", headers=headers, params=params)

    def screen_referral(self, referral_id, headers, payload=None):
        return self._request("POST", f"/referrals/{referral_id}/screen", payload or {}, headers)

    # ---- investigations --------------------------------------------------
    def create_investigation(self, payload, headers):
        return self._request("POST", "/investigations", payload, headers)

    def get_investigation(self, investigation_id, headers):
        return self._request("GET", f"/investigations/{investigation_id}", headers=headers)

    def list_investigations(self, headers, params=None):
        return self._request("GET", "/investigations", headers=headers, params=params)

    def start_investigation(self, investigation_id, headers, payload=None):
        return self._request("POST", f"/investigations/{investigation_id}/start", payload or {}, headers)

    def decide_investigation(self, investigation_id, payload, headers):
        return self._request("POST", f"/investigations/{investigation_id}/decision", payload, headers)

    # ---- cases -----------------------------------------------------------
    def create_case(self, payload, headers):
        return self._request("POST", "/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/cases", headers=headers, params=params)

    def recompute_clock(self, case_id, headers, payload=None):
        return self._request("POST", f"/cases/{case_id}/recompute-clock", payload or {}, headers)

    def advance_permanency(self, case_id, headers, payload=None):
        return self._request("POST", f"/cases/{case_id}/advance-permanency", payload or {}, headers)

    def close_case(self, case_id, headers, payload=None):
        return self._request("POST", f"/cases/{case_id}/close", payload or {}, headers)

    # ---- children --------------------------------------------------------
    def create_child(self, payload, headers):
        return self._request("POST", "/children", payload, headers)

    def get_child(self, child_id, headers):
        return self._request("GET", f"/children/{child_id}", headers=headers)

    def list_children(self, headers, params=None):
        return self._request("GET", "/children", headers=headers, params=params)

    def trial_home_visit(self, child_id, headers, payload=None):
        return self._request("POST", f"/children/{child_id}/trial-home-visit", payload or {}, headers)

    def revoke_trial(self, child_id, headers, payload=None):
        return self._request("POST", f"/children/{child_id}/revoke-trial", payload or {}, headers)

    def age_out(self, child_id, headers, payload=None):
        return self._request("POST", f"/children/{child_id}/age-out", payload or {}, headers)

    # ---- foster homes ----------------------------------------------------
    def create_foster_home(self, payload, headers):
        return self._request("POST", "/foster-homes", payload, headers)

    def get_foster_home(self, home_id, headers):
        return self._request("GET", f"/foster-homes/{home_id}", headers=headers)

    def list_foster_homes(self, headers, params=None):
        return self._request("GET", "/foster-homes", headers=headers, params=params)

    def license_home(self, home_id, payload, headers):
        return self._request("POST", f"/foster-homes/{home_id}/license", payload, headers)

    def license_provisional(self, home_id, headers, payload=None):
        return self._request("POST", f"/foster-homes/{home_id}/license-provisional", payload or {}, headers)

    def suspend_home(self, home_id, headers, payload=None):
        return self._request("POST", f"/foster-homes/{home_id}/suspend", payload or {}, headers)

    def reinstate_home(self, home_id, headers, payload=None):
        return self._request("POST", f"/foster-homes/{home_id}/reinstate", payload or {}, headers)

    def expire_check(self, home_id, headers, payload=None):
        return self._request("POST", f"/foster-homes/{home_id}/expire-check", payload or {}, headers)

    # ---- caregiver screenings -------------------------------------------
    def create_screening(self, payload, headers):
        return self._request("POST", "/caregiver-screenings", payload, headers)

    def get_screening(self, screening_id, headers):
        return self._request("GET", f"/caregiver-screenings/{screening_id}", headers=headers)

    def list_screenings(self, headers, params=None):
        return self._request("GET", "/caregiver-screenings", headers=headers, params=params)

    def resolve_screening(self, screening_id, headers, payload=None):
        return self._request("POST", f"/caregiver-screenings/{screening_id}/resolve", payload or {}, headers)

    # ---- placements ------------------------------------------------------
    def create_placement(self, payload, headers):
        return self._request("POST", "/placements", payload, headers)

    def get_placement(self, placement_id, headers):
        return self._request("GET", f"/placements/{placement_id}", headers=headers)

    def list_placements(self, headers, params=None):
        return self._request("GET", "/placements", headers=headers, params=params)

    def disrupt_placement(self, placement_id, headers, payload=None):
        return self._request("POST", f"/placements/{placement_id}/disrupt", payload or {}, headers)

    def end_reunified(self, placement_id, headers, payload=None):
        return self._request("POST", f"/placements/{placement_id}/end-reunified", payload or {}, headers)

    def end_adopted(self, placement_id, headers, payload=None):
        return self._request("POST", f"/placements/{placement_id}/end-adopted", payload or {}, headers)

    # ---- case plans ------------------------------------------------------
    def create_case_plan(self, payload, headers):
        return self._request("POST", "/case-plans", payload, headers)

    def get_case_plan(self, plan_id, headers):
        return self._request("GET", f"/case-plans/{plan_id}", headers=headers)

    def list_case_plans(self, headers, params=None):
        return self._request("GET", "/case-plans", headers=headers, params=params)

    def update_objectives(self, plan_id, payload, headers):
        return self._request("POST", f"/case-plans/{plan_id}/objectives", payload, headers)

    def activate_case_plan(self, plan_id, headers, payload=None):
        return self._request("POST", f"/case-plans/{plan_id}/activate", payload or {}, headers)

    def revise_case_plan(self, plan_id, headers, payload=None):
        return self._request("POST", f"/case-plans/{plan_id}/revise", payload or {}, headers)

    def complete_case_plan(self, plan_id, headers, payload=None):
        return self._request("POST", f"/case-plans/{plan_id}/complete", payload or {}, headers)

    # ---- visitations -----------------------------------------------------
    def create_visitation(self, payload, headers):
        return self._request("POST", "/visitations", payload, headers)

    def get_visitation(self, visitation_id, headers):
        return self._request("GET", f"/visitations/{visitation_id}", headers=headers)

    def list_visitations(self, headers, params=None):
        return self._request("GET", "/visitations", headers=headers, params=params)

    def mark_occurred(self, visitation_id, headers, payload=None):
        return self._request("POST", f"/visitations/{visitation_id}/mark-occurred", payload or {}, headers)

    def mark_missed(self, visitation_id, headers, payload=None):
        return self._request("POST", f"/visitations/{visitation_id}/mark-missed", payload or {}, headers)

    def cancel_visitation(self, visitation_id, headers, payload=None):
        return self._request("POST", f"/visitations/{visitation_id}/cancel", payload or {}, headers)

    # ---- hearings --------------------------------------------------------
    def create_hearing(self, payload, headers):
        return self._request("POST", "/hearings", payload, headers)

    def get_hearing(self, hearing_id, headers):
        return self._request("GET", f"/hearings/{hearing_id}", headers=headers)

    def list_hearings(self, headers, params=None):
        return self._request("GET", "/hearings", headers=headers, params=params)

    def hold_hearing(self, hearing_id, payload, headers):
        return self._request("POST", f"/hearings/{hearing_id}/hold", payload, headers)

    def continue_hearing(self, hearing_id, headers, payload=None):
        return self._request("POST", f"/hearings/{hearing_id}/continue", payload or {}, headers)

    def reschedule_hearing(self, hearing_id, payload, headers):
        return self._request("POST", f"/hearings/{hearing_id}/reschedule", payload, headers)

    def vacate_hearing(self, hearing_id, headers, payload=None):
        return self._request("POST", f"/hearings/{hearing_id}/vacate", payload or {}, headers)


api_client = ApiClient()
