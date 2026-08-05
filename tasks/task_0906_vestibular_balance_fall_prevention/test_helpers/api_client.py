"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock -------------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Patients ------------------------------------------------------------
    def create_patient(self, payload, headers):
        return self._request("POST", "/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    # --- Referrals -----------------------------------------------------------
    def create_referral(self, payload, headers):
        return self._request("POST", "/referrals", payload, headers)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/referrals/{referral_id}", headers=headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/referrals", headers=headers, params=params)

    def decide_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/referrals/{referral_id}/decision", payload, headers)

    # --- Clinicians ----------------------------------------------------------
    def create_clinician(self, payload, headers):
        return self._request("POST", "/clinicians", payload, headers)

    def get_clinician(self, clinician_id, headers):
        return self._request("GET", f"/clinicians/{clinician_id}", headers=headers)

    # --- Rooms ---------------------------------------------------------------
    def create_room(self, payload, headers):
        return self._request("POST", "/rooms", payload, headers)

    def get_room(self, room_id, headers):
        return self._request("GET", f"/rooms/{room_id}", headers=headers)

    # --- Assessments ---------------------------------------------------------
    def create_assessment(self, payload, headers):
        return self._request("POST", "/assessments", payload, headers)

    def get_assessment(self, assessment_id, headers):
        return self._request("GET", f"/assessments/{assessment_id}", headers=headers)

    def list_assessments(self, headers, params=None):
        return self._request("GET", "/assessments", headers=headers, params=params)

    def finalize_assessment(self, assessment_id, headers):
        return self._request("POST", f"/assessments/{assessment_id}/finalize", {}, headers)

    # --- Care plans ----------------------------------------------------------
    def create_care_plan(self, payload, headers):
        return self._request("POST", "/care-plans", payload, headers)

    def get_care_plan(self, care_plan_id, headers):
        return self._request("GET", f"/care-plans/{care_plan_id}", headers=headers)

    def list_care_plans(self, headers, params=None):
        return self._request("GET", "/care-plans", headers=headers, params=params)

    def activate_care_plan(self, care_plan_id, headers):
        return self._request("POST", f"/care-plans/{care_plan_id}/activate", {}, headers)

    def discharge_care_plan(self, care_plan_id, headers):
        return self._request("POST", f"/care-plans/{care_plan_id}/discharge", {}, headers)

    def get_care_plan_outcome(self, care_plan_id, headers):
        return self._request("GET", f"/care-plans/{care_plan_id}/outcome", headers=headers)

    def create_reassessment(self, care_plan_id, payload, headers):
        return self._request("POST", f"/care-plans/{care_plan_id}/reassessments", payload, headers)

    # --- Reassessments -------------------------------------------------------
    def get_reassessment(self, reassessment_id, headers):
        return self._request("GET", f"/reassessments/{reassessment_id}", headers=headers)

    def list_reassessments(self, headers, params=None):
        return self._request("GET", "/reassessments", headers=headers, params=params)

    def finalize_reassessment(self, reassessment_id, headers):
        return self._request("POST", f"/reassessments/{reassessment_id}/finalize", {}, headers)

    # --- Authorizations ------------------------------------------------------
    def create_authorization(self, payload, headers):
        return self._request("POST", "/authorizations", payload, headers)

    def get_authorization(self, authorization_id, headers):
        return self._request("GET", f"/authorizations/{authorization_id}", headers=headers)

    def list_authorizations(self, headers, params=None):
        return self._request("GET", "/authorizations", headers=headers, params=params)

    def decide_authorization(self, authorization_id, payload, headers):
        return self._request("POST", f"/authorizations/{authorization_id}/decision", payload, headers)

    # --- Sessions ------------------------------------------------------------
    def create_session(self, payload, headers):
        return self._request("POST", "/sessions", payload, headers)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/sessions/{session_id}", headers=headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/sessions", headers=headers, params=params)

    def attend_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/attend", {}, headers)

    def no_show_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/no-show", {}, headers)

    def cancel_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/cancel", {}, headers)

    # --- Home-safety evaluations ---------------------------------------------
    def create_home_safety_evaluation(self, payload, headers):
        return self._request("POST", "/home-safety-evaluations", payload, headers)

    def get_home_safety_evaluation(self, evaluation_id, headers):
        return self._request("GET", f"/home-safety-evaluations/{evaluation_id}", headers=headers)

    def list_home_safety_evaluations(self, headers, params=None):
        return self._request("GET", "/home-safety-evaluations", headers=headers, params=params)

    def finalize_home_safety_evaluation(self, evaluation_id, headers):
        return self._request("POST", f"/home-safety-evaluations/{evaluation_id}/finalize", {}, headers)

    # --- Device referrals ----------------------------------------------------
    def create_device_referral(self, payload, headers):
        return self._request("POST", "/device-referrals", payload, headers)

    def get_device_referral(self, referral_id, headers):
        return self._request("GET", f"/device-referrals/{referral_id}", headers=headers)

    def list_device_referrals(self, headers, params=None):
        return self._request("GET", "/device-referrals", headers=headers, params=params)

    def decide_device_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/device-referrals/{referral_id}/decision", payload, headers)

    # --- Community linkages --------------------------------------------------
    def create_community_linkage(self, payload, headers):
        return self._request("POST", "/community-linkages", payload, headers)

    def get_community_linkage(self, linkage_id, headers):
        return self._request("GET", f"/community-linkages/{linkage_id}", headers=headers)

    def list_community_linkages(self, headers, params=None):
        return self._request("GET", "/community-linkages", headers=headers, params=params)

    def update_linkage_status(self, linkage_id, payload, headers):
        return self._request("POST", f"/community-linkages/{linkage_id}/status", payload, headers)


api_client = ApiClient()
