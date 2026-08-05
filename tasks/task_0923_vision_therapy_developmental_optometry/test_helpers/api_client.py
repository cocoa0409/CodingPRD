"""API client: one method per endpoint published by the Vision Therapy API.

Every route is mounted beneath the `/vision-therapy` prefix.
"""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/vision-therapy"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Patients
    # ------------------------------------------------------------------
    def create_patient(self, payload, headers):
        return self._request("POST", f"{PREFIX}/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"{PREFIX}/patients/{patient_id}", headers=headers)

    def discharge_patient(self, patient_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/patients/{patient_id}/discharge", payload, headers
        )

    # ------------------------------------------------------------------
    # Payers
    # ------------------------------------------------------------------
    def create_payer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/payers", payload, headers)

    def get_payer(self, payer_id, headers):
        return self._request("GET", f"{PREFIX}/payers/{payer_id}", headers=headers)

    # ------------------------------------------------------------------
    # Coverages
    # ------------------------------------------------------------------
    def create_coverage(self, payload, headers):
        return self._request("POST", f"{PREFIX}/coverages", payload, headers)

    def get_coverage(self, coverage_id, headers):
        return self._request("GET", f"{PREFIX}/coverages/{coverage_id}", headers=headers)

    def list_coverages(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/coverages", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Authorizations
    # ------------------------------------------------------------------
    def create_authorization(self, payload, headers):
        return self._request("POST", f"{PREFIX}/authorizations", payload, headers)

    def get_authorization(self, authorization_id, headers):
        return self._request(
            "GET", f"{PREFIX}/authorizations/{authorization_id}", headers=headers
        )

    def list_authorizations(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/authorizations", headers=headers, params=params
        )

    def reauthorize(self, authorization_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/authorizations/{authorization_id}/reauthorize",
            payload,
            headers,
        )

    def close_authorization(self, authorization_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/authorizations/{authorization_id}/close", payload, headers
        )

    # ------------------------------------------------------------------
    # Therapists and rooms
    # ------------------------------------------------------------------
    def create_therapist(self, payload, headers):
        return self._request("POST", f"{PREFIX}/therapists", payload, headers)

    def get_therapist(self, therapist_id, headers):
        return self._request(
            "GET", f"{PREFIX}/therapists/{therapist_id}", headers=headers
        )

    def create_room(self, payload, headers):
        return self._request("POST", f"{PREFIX}/rooms", payload, headers)

    # ------------------------------------------------------------------
    # Assessments and measurements
    # ------------------------------------------------------------------
    def create_assessment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/assessments", payload, headers)

    def get_assessment(self, assessment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/assessments/{assessment_id}", headers=headers
        )

    def list_assessments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/assessments", headers=headers, params=params
        )

    def create_measurement(self, assessment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/assessments/{assessment_id}/measurements", payload, headers
        )

    def list_measurements(self, assessment_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/assessments/{assessment_id}/measurements",
            headers=headers,
            params=params,
        )

    def finalize_assessment(self, assessment_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/assessments/{assessment_id}/finalize", payload or {}, headers
        )

    def sign_assessment(self, assessment_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/assessments/{assessment_id}/sign", payload or {}, headers
        )

    def amend_assessment(self, assessment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/assessments/{assessment_id}/amend", payload, headers
        )

    # ------------------------------------------------------------------
    # Therapy plans and phases
    # ------------------------------------------------------------------
    def create_therapy_plan(self, payload, headers):
        return self._request("POST", f"{PREFIX}/therapy-plans", payload, headers)

    def get_therapy_plan(self, plan_id, headers):
        return self._request("GET", f"{PREFIX}/therapy-plans/{plan_id}", headers=headers)

    def list_therapy_plans(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/therapy-plans", headers=headers, params=params
        )

    def activate_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/therapy-plans/{plan_id}/activate", payload, headers
        )

    def advance_phase(self, plan_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/therapy-plans/{plan_id}/advance-phase", payload or {}, headers
        )

    def revise_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/therapy-plans/{plan_id}/revise", payload, headers
        )

    def suspend_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/therapy-plans/{plan_id}/suspend", payload, headers
        )

    def resume_plan(self, plan_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/therapy-plans/{plan_id}/resume", payload or {}, headers
        )

    def create_phase(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/therapy-plans/{plan_id}/phases", payload, headers
        )

    def list_phases(self, plan_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/therapy-plans/{plan_id}/phases", headers=headers, params=params
        )

    def record_mastery(self, phase_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/phases/{phase_id}/mastery", payload, headers
        )

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------
    def create_session(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/therapy-plans/{plan_id}/sessions", payload, headers
        )

    def create_home_session(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/therapy-plans/{plan_id}/home-sessions", payload, headers
        )

    def get_session(self, session_id, headers):
        return self._request("GET", f"{PREFIX}/sessions/{session_id}", headers=headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/sessions", headers=headers, params=params)

    def check_in_session(self, session_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/sessions/{session_id}/check-in", payload or {}, headers
        )

    def complete_session(self, session_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/sessions/{session_id}/complete", payload, headers
        )

    def cancel_session(self, session_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/sessions/{session_id}/cancel", payload, headers
        )

    def no_show_session(self, session_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/sessions/{session_id}/no-show", payload or {}, headers
        )

    def attest_session(self, session_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/sessions/{session_id}/attest", payload, headers
        )

    # ------------------------------------------------------------------
    # Kit items and loans
    # ------------------------------------------------------------------
    def create_kit_item(self, payload, headers):
        return self._request("POST", f"{PREFIX}/kit-items", payload, headers)

    def get_kit_item(self, kit_item_id, headers):
        return self._request("GET", f"{PREFIX}/kit-items/{kit_item_id}", headers=headers)

    def create_kit_loan(self, payload, headers):
        return self._request("POST", f"{PREFIX}/kit-loans", payload, headers)

    def get_kit_loan(self, loan_id, headers):
        return self._request("GET", f"{PREFIX}/kit-loans/{loan_id}", headers=headers)

    def list_kit_loans(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/kit-loans", headers=headers, params=params)

    def fulfill_kit_loan(self, loan_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/kit-loans/{loan_id}/fulfill", payload or {}, headers
        )

    def return_kit_loan(self, loan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/kit-loans/{loan_id}/return", payload, headers
        )

    # ------------------------------------------------------------------
    # Claims
    # ------------------------------------------------------------------
    def create_claim(self, payload, headers):
        return self._request("POST", f"{PREFIX}/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"{PREFIX}/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/claims", headers=headers, params=params)

    def submit_claim(self, claim_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/claims/{claim_id}/submit", payload or {}, headers
        )

    def adjudicate_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/claims/{claim_id}/adjudicate", payload, headers
        )

    def appeal_claim(self, claim_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/claims/{claim_id}/appeal", payload or {}, headers
        )

    def correct_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/claims/{claim_id}/correct", payload, headers
        )

    # ------------------------------------------------------------------
    # Referrals
    # ------------------------------------------------------------------
    def create_referral(self, payload, headers):
        return self._request("POST", f"{PREFIX}/referrals", payload, headers)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"{PREFIX}/referrals/{referral_id}", headers=headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/referrals", headers=headers, params=params)

    def respond_referral(self, referral_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/referrals/{referral_id}/respond", payload, headers
        )

    def re_refer(self, referral_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/referrals/{referral_id}/re-refer", payload, headers
        )

    # ------------------------------------------------------------------
    # Occlusion prescriptions
    # ------------------------------------------------------------------
    def create_occlusion_prescription(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/occlusion-prescriptions", payload, headers
        )

    def get_occlusion_prescription(self, prescription_id, headers):
        return self._request(
            "GET", f"{PREFIX}/occlusion-prescriptions/{prescription_id}", headers=headers
        )

    def list_occlusion_prescriptions(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/occlusion-prescriptions", headers=headers, params=params
        )

    def log_adherence(self, prescription_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/occlusion-prescriptions/{prescription_id}/adherence",
            payload,
            headers,
        )

    def taper_occlusion(self, prescription_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/occlusion-prescriptions/{prescription_id}/taper",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST",
            f"{PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601},
            headers,
        )


api_client = ApiClient()
