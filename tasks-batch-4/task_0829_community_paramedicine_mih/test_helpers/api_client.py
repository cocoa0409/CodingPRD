"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Payer ----
    def create_payer(self, payload, headers):
        return self._request("POST", "/mih/payers", payload, headers)

    def get_payer(self, payer_id, headers):
        return self._request("GET", f"/mih/payers/{payer_id}", headers=headers)

    # ---- PilotProgram ----
    def create_program(self, payload, headers):
        return self._request("POST", "/mih/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/mih/programs/{program_id}", headers=headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/mih/programs", headers=headers, params=params)

    def close_program(self, program_id, headers):
        return self._request("POST", f"/mih/programs/{program_id}/close", {}, headers)

    # ---- Provider ----
    def create_provider(self, payload, headers):
        return self._request("POST", "/mih/providers", payload, headers)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/mih/providers/{provider_id}", headers=headers)

    def list_providers(self, headers, params=None):
        return self._request("GET", "/mih/providers", headers=headers, params=params)

    # ---- Patient ----
    def create_patient(self, payload, headers):
        return self._request("POST", "/mih/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/mih/patients/{patient_id}", headers=headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/mih/patients", headers=headers, params=params)

    # ---- Referral ----
    def create_referral(self, payload, headers):
        return self._request("POST", "/mih/referrals", payload, headers)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/mih/referrals/{referral_id}", headers=headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/mih/referrals", headers=headers, params=params)

    def screen_referral(self, referral_id, headers):
        return self._request("POST", f"/mih/referrals/{referral_id}/screen", {}, headers)

    def accept_referral(self, referral_id, headers):
        return self._request("POST", f"/mih/referrals/{referral_id}/accept", {}, headers)

    def decline_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/mih/referrals/{referral_id}/decline", payload, headers)

    # ---- Enrollment ----
    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/mih/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/mih/enrollments", headers=headers, params=params)

    def discharge_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/mih/enrollments/{enrollment_id}/discharge", {}, headers)

    def withdraw_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/mih/enrollments/{enrollment_id}/withdraw", {}, headers)

    def get_cost_outcome(self, enrollment_id, headers):
        return self._request("GET", f"/mih/enrollments/{enrollment_id}/cost-outcome", headers=headers)

    # ---- CarePlan ----
    def create_care_plan(self, enrollment_id, payload, headers):
        return self._request("POST", f"/mih/enrollments/{enrollment_id}/care-plans", payload, headers)

    def get_care_plan(self, care_plan_id, headers):
        return self._request("GET", f"/mih/care-plans/{care_plan_id}", headers=headers)

    def list_care_plans(self, headers, params=None):
        return self._request("GET", "/mih/care-plans", headers=headers, params=params)

    def activate_care_plan(self, care_plan_id, headers):
        return self._request("POST", f"/mih/care-plans/{care_plan_id}/activate", {}, headers)

    def revise_care_plan(self, care_plan_id, headers):
        return self._request("POST", f"/mih/care-plans/{care_plan_id}/revise", {}, headers)

    def close_care_plan(self, care_plan_id, headers):
        return self._request("POST", f"/mih/care-plans/{care_plan_id}/close", {}, headers)

    # ---- HomeVisit ----
    def create_home_visit(self, payload, headers):
        return self._request("POST", "/mih/home-visits", payload, headers)

    def get_home_visit(self, home_visit_id, headers):
        return self._request("GET", f"/mih/home-visits/{home_visit_id}", headers=headers)

    def list_home_visits(self, headers, params=None):
        return self._request("GET", "/mih/home-visits", headers=headers, params=params)

    def complete_home_visit(self, home_visit_id, payload, headers):
        return self._request("POST", f"/mih/home-visits/{home_visit_id}/complete", payload, headers)

    def cancel_home_visit(self, home_visit_id, headers):
        return self._request("POST", f"/mih/home-visits/{home_visit_id}/cancel", {}, headers)

    def no_show_home_visit(self, home_visit_id, headers):
        return self._request("POST", f"/mih/home-visits/{home_visit_id}/no-show", {}, headers)

    # ---- TelehealthSession ----
    def create_telehealth_session(self, payload, headers):
        return self._request("POST", "/mih/telehealth-sessions", payload, headers)

    def get_telehealth_session(self, session_id, headers):
        return self._request("GET", f"/mih/telehealth-sessions/{session_id}", headers=headers)

    def list_telehealth_sessions(self, headers, params=None):
        return self._request("GET", "/mih/telehealth-sessions", headers=headers, params=params)

    def complete_telehealth_session(self, session_id, payload, headers):
        return self._request("POST", f"/mih/telehealth-sessions/{session_id}/complete", payload, headers)

    def cancel_telehealth_session(self, session_id, headers):
        return self._request("POST", f"/mih/telehealth-sessions/{session_id}/cancel", {}, headers)

    # ---- MedReconciliation ----
    def create_med_reconciliation(self, payload, headers):
        return self._request("POST", "/mih/med-reconciliations", payload, headers)

    def get_med_reconciliation(self, mr_id, headers):
        return self._request("GET", f"/mih/med-reconciliations/{mr_id}", headers=headers)

    def list_med_reconciliations(self, headers, params=None):
        return self._request("GET", "/mih/med-reconciliations", headers=headers, params=params)

    def submit_med_reconciliation(self, mr_id, headers):
        return self._request("POST", f"/mih/med-reconciliations/{mr_id}/submit", {}, headers)

    def review_med_reconciliation(self, mr_id, payload, headers):
        return self._request("POST", f"/mih/med-reconciliations/{mr_id}/review", payload, headers)

    # ---- SocialNeedsReferral ----
    def create_social_referral(self, payload, headers):
        return self._request("POST", "/mih/social-referrals", payload, headers)

    def get_social_referral(self, sr_id, headers):
        return self._request("GET", f"/mih/social-referrals/{sr_id}", headers=headers)

    def list_social_referrals(self, headers, params=None):
        return self._request("GET", "/mih/social-referrals", headers=headers, params=params)

    def refer_social_referral(self, sr_id, payload, headers):
        return self._request("POST", f"/mih/social-referrals/{sr_id}/refer", payload, headers)

    def resolve_social_referral(self, sr_id, payload, headers):
        return self._request("POST", f"/mih/social-referrals/{sr_id}/resolve", payload, headers)

    # ---- EDEvent ----
    def create_ed_event(self, payload, headers):
        return self._request("POST", "/mih/ed-events", payload, headers)

    def get_ed_event(self, ed_event_id, headers):
        return self._request("GET", f"/mih/ed-events/{ed_event_id}", headers=headers)

    def list_ed_events(self, headers, params=None):
        return self._request("GET", "/mih/ed-events", headers=headers, params=params)

    # ---- BillingClaim ----
    def create_billing_claim(self, payload, headers):
        return self._request("POST", "/mih/billing-claims", payload, headers)

    def get_billing_claim(self, claim_id, headers):
        return self._request("GET", f"/mih/billing-claims/{claim_id}", headers=headers)

    def list_billing_claims(self, headers, params=None):
        return self._request("GET", "/mih/billing-claims", headers=headers, params=params)

    def submit_billing_claim(self, claim_id, headers):
        return self._request("POST", f"/mih/billing-claims/{claim_id}/submit", {}, headers)

    def adjudicate_billing_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/mih/billing-claims/{claim_id}/adjudicate", payload, headers)

    def resubmit_billing_claim(self, claim_id, headers):
        return self._request("POST", f"/mih/billing-claims/{claim_id}/resubmit", {}, headers)

    # ---- Logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/mih/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
