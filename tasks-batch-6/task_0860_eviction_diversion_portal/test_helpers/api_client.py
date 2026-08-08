"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (test-driving) ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers=headers)

    # --- Court ---
    def create_court(self, payload, headers):
        return self._request("POST", "/courts", payload, headers=headers)

    def get_court(self, court_id, headers):
        return self._request("GET", f"/courts/{court_id}", headers=headers)

    # --- Landlord ---
    def create_landlord(self, payload, headers):
        return self._request("POST", "/landlords", payload, headers=headers)

    def get_landlord(self, landlord_id, headers):
        return self._request("GET", f"/landlords/{landlord_id}", headers=headers)

    # --- Tenant ---
    def create_tenant(self, payload, headers):
        return self._request("POST", "/tenants", payload, headers=headers)

    def get_tenant(self, tenant_id, headers):
        return self._request("GET", f"/tenants/{tenant_id}", headers=headers)

    # --- Officer ---
    def create_officer(self, payload, headers):
        return self._request("POST", "/officers", payload, headers=headers)

    def get_officer(self, officer_id, headers):
        return self._request("GET", f"/officers/{officer_id}", headers=headers)

    # --- Case ---
    def create_case(self, payload, headers):
        return self._request("POST", "/cases", payload, headers=headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/cases", headers=headers, params=params)

    def transition_case(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/transition", payload, headers=headers)

    # --- Answer ---
    def create_answer(self, payload, headers):
        return self._request("POST", "/answers", payload, headers=headers)

    def get_answer(self, answer_id, headers):
        return self._request("GET", f"/answers/{answer_id}", headers=headers)

    def list_answers(self, headers, params=None):
        return self._request("GET", "/answers", headers=headers, params=params)

    # --- Referral ---
    def create_referral(self, payload, headers):
        return self._request("POST", "/referrals", payload, headers=headers)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/referrals/{referral_id}", headers=headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/referrals", headers=headers, params=params)

    def transition_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/referrals/{referral_id}/transition", payload, headers=headers)

    # --- Mediation session ---
    def create_mediation_session(self, payload, headers):
        return self._request("POST", "/mediation-sessions", payload, headers=headers)

    def get_mediation_session(self, session_id, headers):
        return self._request("GET", f"/mediation-sessions/{session_id}", headers=headers)

    def list_mediation_sessions(self, headers, params=None):
        return self._request("GET", "/mediation-sessions", headers=headers, params=params)

    def transition_mediation_session(self, session_id, payload, headers):
        return self._request("POST", f"/mediation-sessions/{session_id}/transition", payload, headers=headers)

    # --- Payment plan ---
    def create_payment_plan(self, payload, headers):
        return self._request("POST", "/payment-plans", payload, headers=headers)

    def get_payment_plan(self, plan_id, headers):
        return self._request("GET", f"/payment-plans/{plan_id}", headers=headers)

    def list_payment_plans(self, headers, params=None):
        return self._request("GET", "/payment-plans", headers=headers, params=params)

    def respond_payment_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/payment-plans/{plan_id}/respond", payload, headers=headers)

    # --- Installment ---
    def get_installment(self, installment_id, headers):
        return self._request("GET", f"/installments/{installment_id}", headers=headers)

    def list_installments(self, headers, params=None):
        return self._request("GET", "/installments", headers=headers, params=params)

    def transition_installment(self, installment_id, payload, headers):
        return self._request("POST", f"/installments/{installment_id}/transition", payload, headers=headers)

    # --- Hearing ---
    def create_hearing(self, payload, headers):
        return self._request("POST", "/hearings", payload, headers=headers)

    def get_hearing(self, hearing_id, headers):
        return self._request("GET", f"/hearings/{hearing_id}", headers=headers)

    def list_hearings(self, headers, params=None):
        return self._request("GET", "/hearings", headers=headers, params=params)

    def transition_hearing(self, hearing_id, payload, headers):
        return self._request("POST", f"/hearings/{hearing_id}/transition", payload, headers=headers)

    # --- Judgment ---
    def create_judgment(self, payload, headers):
        return self._request("POST", "/judgments", payload, headers=headers)

    def get_judgment(self, judgment_id, headers):
        return self._request("GET", f"/judgments/{judgment_id}", headers=headers)

    def list_judgments(self, headers, params=None):
        return self._request("GET", "/judgments", headers=headers, params=params)

    def transition_judgment(self, judgment_id, payload, headers):
        return self._request("POST", f"/judgments/{judgment_id}/transition", payload, headers=headers)

    # --- Lockout order ---
    def create_lockout_order(self, payload, headers):
        return self._request("POST", "/lockout-orders", payload, headers=headers)

    def get_lockout_order(self, lockout_id, headers):
        return self._request("GET", f"/lockout-orders/{lockout_id}", headers=headers)

    def list_lockout_orders(self, headers, params=None):
        return self._request("GET", "/lockout-orders", headers=headers, params=params)

    def transition_lockout_order(self, lockout_id, payload, headers):
        return self._request("POST", f"/lockout-orders/{lockout_id}/transition", payload, headers=headers)

    # --- Sealing request ---
    def create_sealing_request(self, payload, headers):
        return self._request("POST", "/sealing-requests", payload, headers=headers)

    def get_sealing_request(self, sealing_id, headers):
        return self._request("GET", f"/sealing-requests/{sealing_id}", headers=headers)

    def list_sealing_requests(self, headers, params=None):
        return self._request("GET", "/sealing-requests", headers=headers, params=params)

    def transition_sealing_request(self, sealing_id, payload, headers):
        return self._request("POST", f"/sealing-requests/{sealing_id}/transition", payload, headers=headers)


api_client = ApiClient()
