"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # per-test-server isolation hard-kills (SIGKILL) and reboots the API
        # server before every test. A pooled keep-alive connection can still
        # point at the dead process and fail mid-test with
        # ConnectionResetError ("Connection reset by peer"). Send
        # `Connection: close` so urllib3 never reuses a stale socket.
        self.session.headers["Connection"] = "close"
        self.session.keep_alive = False

    # --- Client ---
    def create_client(self, payload, headers):
        return self._request("POST", "/api/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/api/clients/{client_id}", headers=headers)

    def list_client_referrals(self, client_id, headers, params=None):
        return self._request("GET", f"/api/clients/{client_id}/referrals", headers=headers, params=params)

    def list_client_outcome_assessments(self, client_id, headers, params=None):
        return self._request("GET", f"/api/clients/{client_id}/outcome-assessments", headers=headers, params=params)

    # --- Referral ---
    def create_referral(self, payload, headers):
        return self._request("POST", "/api/referrals", payload, headers)

    def decide_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/api/referrals/{referral_id}/decide", payload, headers)

    # --- Evaluation ---
    def create_evaluation(self, payload, headers):
        return self._request("POST", "/api/evaluations", payload, headers)

    def get_evaluation(self, evaluation_id, headers):
        return self._request("GET", f"/api/evaluations/{evaluation_id}", headers=headers)

    def list_evaluations(self, headers, params=None):
        return self._request("GET", "/api/evaluations", headers=headers, params=params)

    def finalize_evaluation(self, evaluation_id, headers):
        return self._request("POST", f"/api/evaluations/{evaluation_id}/finalize", {}, headers)

    def revise_evaluation(self, evaluation_id, payload, headers):
        return self._request("POST", f"/api/evaluations/{evaluation_id}/revise", payload, headers)

    # --- DeviceModel / DeviceUnit ---
    def create_device_model(self, payload, headers):
        return self._request("POST", "/api/device-models", payload, headers)

    def get_device_model(self, model_id, headers):
        return self._request("GET", f"/api/device-models/{model_id}", headers=headers)

    def list_model_predecessors(self, model_id, headers, params=None):
        return self._request("GET", f"/api/device-models/{model_id}/predecessors", headers=headers, params=params)

    def create_device_unit(self, payload, headers):
        return self._request("POST", "/api/device-units", payload, headers)

    def get_device_unit(self, unit_id, headers):
        return self._request("GET", f"/api/device-units/{unit_id}", headers=headers)

    def list_device_units(self, headers, params=None):
        return self._request("GET", "/api/device-units", headers=headers, params=params)

    def list_unit_repair_tickets(self, unit_id, headers, params=None):
        return self._request("GET", f"/api/device-units/{unit_id}/repair-tickets", headers=headers, params=params)

    def retire_device_unit(self, unit_id, headers):
        return self._request("POST", f"/api/device-units/{unit_id}/retire", {}, headers)

    # --- DeviceOrder ---
    def create_device_order(self, payload, headers):
        return self._request("POST", "/api/device-orders", payload, headers)

    def get_device_order(self, order_id, headers):
        return self._request("GET", f"/api/device-orders/{order_id}", headers=headers)

    def list_device_orders(self, headers, params=None):
        return self._request("GET", "/api/device-orders", headers=headers, params=params)

    def allocate_device_order(self, order_id, payload, headers):
        return self._request("POST", f"/api/device-orders/{order_id}/allocate", payload, headers)

    def convert_device_order(self, order_id, headers):
        return self._request("POST", f"/api/device-orders/{order_id}/convert", {}, headers)

    def return_device_order(self, order_id, headers):
        return self._request("POST", f"/api/device-orders/{order_id}/return", {}, headers)

    # --- LoanAgreement ---
    def get_loan_agreement(self, loan_id, headers):
        return self._request("GET", f"/api/loan-agreements/{loan_id}", headers=headers)

    def list_loan_agreements(self, headers, params=None):
        return self._request("GET", "/api/loan-agreements", headers=headers, params=params)

    def return_loan_agreement(self, loan_id, headers):
        return self._request("POST", f"/api/loan-agreements/{loan_id}/return", {}, headers)

    def list_loan_repair_tickets(self, loan_id, headers, params=None):
        return self._request("GET", f"/api/loan-agreements/{loan_id}/repair-tickets", headers=headers, params=params)

    # --- Training ---
    def create_training_plan(self, payload, headers):
        return self._request("POST", "/api/training-plans", payload, headers)

    def get_training_plan(self, plan_id, headers):
        return self._request("GET", f"/api/training-plans/{plan_id}", headers=headers)

    def list_training_plans(self, headers, params=None):
        return self._request("GET", "/api/training-plans", headers=headers, params=params)

    def create_training_session(self, plan_id, payload, headers):
        return self._request("POST", f"/api/training-plans/{plan_id}/sessions", payload, headers)

    def list_plan_sessions(self, plan_id, headers, params=None):
        return self._request("GET", f"/api/training-plans/{plan_id}/sessions", headers=headers, params=params)

    def resolve_training_session(self, session_id, payload, headers):
        return self._request("POST", f"/api/training-sessions/{session_id}/resolve", payload, headers)

    # --- FundingAuthorization ---
    def create_funding_authorization(self, payload, headers):
        return self._request("POST", "/api/funding-authorizations", payload, headers)

    def get_funding_authorization(self, auth_id, headers):
        return self._request("GET", f"/api/funding-authorizations/{auth_id}", headers=headers)

    def list_funding_authorizations(self, headers, params=None):
        return self._request("GET", "/api/funding-authorizations", headers=headers, params=params)

    def submit_funding_authorization(self, auth_id, headers):
        return self._request("POST", f"/api/funding-authorizations/{auth_id}/submit", {}, headers)

    def adjudicate_funding_authorization(self, auth_id, payload, headers):
        return self._request("POST", f"/api/funding-authorizations/{auth_id}/adjudicate", payload, headers)

    def appeal_funding_authorization(self, auth_id, headers):
        return self._request("POST", f"/api/funding-authorizations/{auth_id}/appeal", {}, headers)

    # --- Claim ---
    def create_claim(self, payload, headers):
        return self._request("POST", "/api/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/api/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/api/claims", headers=headers, params=params)

    def submit_claim(self, claim_id, headers):
        return self._request("POST", f"/api/claims/{claim_id}/submit", {}, headers)

    def adjudicate_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/api/claims/{claim_id}/adjudicate", payload, headers)

    def void_claim(self, claim_id, headers):
        return self._request("POST", f"/api/claims/{claim_id}/void", {}, headers)

    # --- RepairTicket ---
    def create_repair_ticket(self, payload, headers):
        return self._request("POST", "/api/repair-tickets", payload, headers)

    def get_repair_ticket(self, ticket_id, headers):
        return self._request("GET", f"/api/repair-tickets/{ticket_id}", headers=headers)

    def advance_repair_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/api/repair-tickets/{ticket_id}/advance", payload, headers)

    # --- Subscription ---
    def create_subscription(self, payload, headers):
        return self._request("POST", "/api/subscriptions", payload, headers)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/api/subscriptions/{subscription_id}", headers=headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/api/subscriptions", headers=headers, params=params)

    def renew_subscription(self, subscription_id, headers):
        return self._request("POST", f"/api/subscriptions/{subscription_id}/renew", {}, headers)

    def cancel_subscription(self, subscription_id, headers):
        return self._request("POST", f"/api/subscriptions/{subscription_id}/cancel", {}, headers)

    # --- OutcomeAssessment ---
    def create_outcome_assessment(self, payload, headers):
        return self._request("POST", "/api/outcome-assessments", payload, headers)

    def get_outcome_assessment(self, assessment_id, headers):
        return self._request("GET", f"/api/outcome-assessments/{assessment_id}", headers=headers)

    def finalize_outcome_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"/api/outcome-assessments/{assessment_id}/finalize", payload, headers)

    # --- Ops / clock ---
    def run_daily(self, headers):
        return self._request("POST", "/api/ops/run_daily", {}, headers)

    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
