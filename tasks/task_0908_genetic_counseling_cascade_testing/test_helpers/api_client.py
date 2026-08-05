"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- Family ----
    def create_family(self, payload, headers):
        return self._request("POST", "/families", payload, headers)

    def get_family(self, family_id, headers):
        return self._request("GET", f"/families/{family_id}", headers=headers)

    # ---- Counselor ----
    def create_counselor(self, payload, headers):
        return self._request("POST", "/counselors", payload, headers)

    def get_counselor(self, counselor_id, headers):
        return self._request("GET", f"/counselors/{counselor_id}", headers=headers)

    # ---- Lab ----
    def create_lab(self, payload, headers):
        return self._request("POST", "/labs", payload, headers)

    def get_lab(self, lab_id, headers):
        return self._request("GET", f"/labs/{lab_id}", headers=headers)

    # ---- CounselingCase ----
    def create_case(self, payload, headers):
        return self._request("POST", "/counseling-cases", payload, headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/counseling-cases", headers=headers, params=params)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/counseling-cases/{case_id}", headers=headers)

    def assess_risk(self, case_id, headers):
        return self._request("POST", f"/counseling-cases/{case_id}/assess-risk", {}, headers)

    def withdraw_case(self, case_id, headers):
        return self._request("POST", f"/counseling-cases/{case_id}/withdraw", {}, headers)

    # ---- PedigreeMember ----
    def create_pedigree_member(self, payload, headers):
        return self._request("POST", "/pedigree-members", payload, headers)

    def list_pedigree_members(self, headers, params=None):
        return self._request("GET", "/pedigree-members", headers=headers, params=params)

    def get_pedigree_member(self, member_id, headers):
        return self._request("GET", f"/pedigree-members/{member_id}", headers=headers)

    # ---- ConsentRecord ----
    def create_consent(self, payload, headers):
        return self._request("POST", "/consent-records", payload, headers)

    def list_consents(self, headers, params=None):
        return self._request("GET", "/consent-records", headers=headers, params=params)

    def get_consent(self, consent_id, headers):
        return self._request("GET", f"/consent-records/{consent_id}", headers=headers)

    def sign_consent(self, consent_id, headers):
        return self._request("POST", f"/consent-records/{consent_id}/sign", {}, headers)

    def revoke_consent(self, consent_id, headers):
        return self._request("POST", f"/consent-records/{consent_id}/revoke", {}, headers)

    # ---- CounselingSession ----
    def create_session(self, payload, headers):
        return self._request("POST", "/counseling-sessions", payload, headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/counseling-sessions", headers=headers, params=params)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/counseling-sessions/{session_id}", headers=headers)

    def complete_session(self, session_id, headers):
        return self._request("POST", f"/counseling-sessions/{session_id}/complete", {}, headers)

    def cancel_session(self, session_id, headers):
        return self._request("POST", f"/counseling-sessions/{session_id}/cancel", {}, headers)

    def no_show_session(self, session_id, headers):
        return self._request("POST", f"/counseling-sessions/{session_id}/no-show", {}, headers)

    # ---- TestOrder ----
    def create_order(self, payload, headers):
        return self._request("POST", "/test-orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/test-orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/test-orders/{order_id}", headers=headers)

    def submit_order(self, order_id, headers):
        return self._request("POST", f"/test-orders/{order_id}/submit", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/test-orders/{order_id}/cancel", {}, headers)

    # ---- TestResult ----
    def create_result(self, payload, headers):
        return self._request("POST", "/test-results", payload, headers)

    def list_results(self, headers, params=None):
        return self._request("GET", "/test-results", headers=headers, params=params)

    def get_result(self, result_id, headers):
        return self._request("GET", f"/test-results/{result_id}", headers=headers)

    def release_result(self, result_id, headers):
        return self._request("POST", f"/test-results/{result_id}/release", {}, headers)

    def disclose_result(self, result_id, headers):
        return self._request("POST", f"/test-results/{result_id}/disclose", {}, headers)

    # ---- CascadeInvitation ----
    def create_invitation(self, payload, headers):
        return self._request("POST", "/cascade-invitations", payload, headers)

    def list_invitations(self, headers, params=None):
        return self._request("GET", "/cascade-invitations", headers=headers, params=params)

    def get_invitation(self, invitation_id, headers):
        return self._request("GET", f"/cascade-invitations/{invitation_id}", headers=headers)

    def send_invitation(self, invitation_id, headers):
        return self._request("POST", f"/cascade-invitations/{invitation_id}/send", {}, headers)

    def decline_invitation(self, invitation_id, headers):
        return self._request("POST", f"/cascade-invitations/{invitation_id}/decline", {}, headers)

    def accept_invitation(self, invitation_id, headers, payload=None):
        return self._request("POST", f"/cascade-invitations/{invitation_id}/accept",
                             payload if payload is not None else {}, headers)

    def expire_invitation(self, invitation_id, headers):
        return self._request("POST", f"/cascade-invitations/{invitation_id}/expire", {}, headers)

    # ---- InsuranceClaim ----
    def create_claim(self, payload, headers):
        return self._request("POST", "/insurance-claims", payload, headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/insurance-claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/insurance-claims/{claim_id}", headers=headers)

    def authorize_claim(self, claim_id, headers):
        return self._request("POST", f"/insurance-claims/{claim_id}/authorize", {}, headers)

    def submit_claim(self, claim_id, headers):
        return self._request("POST", f"/insurance-claims/{claim_id}/submit", {}, headers)

    def adjudicate_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/insurance-claims/{claim_id}/adjudicate", payload, headers)

    def void_claim(self, claim_id, headers):
        return self._request("POST", f"/insurance-claims/{claim_id}/void", {}, headers)

    # ---- SurveillancePlan ----
    def create_surveillance_plan(self, payload, headers):
        return self._request("POST", "/surveillance-plans", payload, headers)

    def list_surveillance_plans(self, headers, params=None):
        return self._request("GET", "/surveillance-plans", headers=headers, params=params)

    def get_surveillance_plan(self, plan_id, headers):
        return self._request("GET", f"/surveillance-plans/{plan_id}", headers=headers)

    def close_surveillance_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/surveillance-plans/{plan_id}/close", payload, headers)

    # ---- Referral ----
    def create_referral(self, payload, headers):
        return self._request("POST", "/referrals", payload, headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/referrals", headers=headers, params=params)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/referrals/{referral_id}", headers=headers)

    def close_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/referrals/{referral_id}/close", payload, headers)


api_client = ApiClient()
