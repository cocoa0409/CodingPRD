"""API client: one method per endpoint defined in the PRD.

Subclasses the framework GenericApiClient; only the teletherapy-specific
endpoint methods are declared here. The base _request() handles envelope
construction, headers, and HTTP transport.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clients ----
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/clients", headers=headers, params=params)

    def submit_intake(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/intake", payload, headers)

    def get_intake(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}/intake", headers=headers)

    def clear_intake(self, client_id, headers):
        return self._request("POST", f"/clients/{client_id}/clear-intake", headers=headers)

    def list_client_subscriptions(self, client_id, headers, params=None):
        return self._request("GET", f"/clients/{client_id}/subscriptions", headers=headers, params=params)

    def list_client_session_credits(self, client_id, headers, params=None):
        return self._request("GET", f"/clients/{client_id}/session-credits", headers=headers, params=params)

    def list_client_crisis_escalations(self, client_id, headers, params=None):
        return self._request("GET", f"/clients/{client_id}/crisis-escalations", headers=headers, params=params)

    def list_client_financial_aid_applications(self, client_id, headers, params=None):
        return self._request("GET", f"/clients/{client_id}/financial-aid-applications", headers=headers, params=params)

    def list_client_superbills(self, client_id, headers, params=None):
        return self._request("GET", f"/clients/{client_id}/superbills", headers=headers, params=params)

    def create_crisis_escalation(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/crisis-escalations", payload, headers)

    def create_financial_aid_application(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/financial-aid-applications", payload, headers)

    def create_superbill(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/superbills", payload, headers)

    # ---- Therapists & licenses ----
    def create_therapist(self, payload, headers):
        return self._request("POST", "/therapists", payload, headers)

    def get_therapist(self, therapist_id, headers):
        return self._request("GET", f"/therapists/{therapist_id}", headers=headers)

    def list_therapists(self, headers, params=None):
        return self._request("GET", "/therapists", headers=headers, params=params)

    def create_license(self, therapist_id, payload, headers):
        return self._request("POST", f"/therapists/{therapist_id}/licenses", payload, headers)

    def list_licenses(self, therapist_id, headers, params=None):
        return self._request("GET", f"/therapists/{therapist_id}/licenses", headers=headers, params=params)

    def activate_therapist(self, therapist_id, headers):
        return self._request("POST", f"/therapists/{therapist_id}/activate", headers=headers)

    def deactivate_therapist(self, therapist_id, headers):
        return self._request("POST", f"/therapists/{therapist_id}/deactivate", headers=headers)

    def list_therapist_matches(self, therapist_id, headers, params=None):
        return self._request("GET", f"/therapists/{therapist_id}/matches", headers=headers, params=params)

    # ---- Matches ----
    def create_match(self, payload, headers):
        return self._request("POST", "/matches", payload, headers)

    def get_match(self, match_id, headers):
        return self._request("GET", f"/matches/{match_id}", headers=headers)

    def list_matches(self, headers, params=None):
        return self._request("GET", "/matches", headers=headers, params=params)

    def accept_match(self, match_id, headers):
        return self._request("POST", f"/matches/{match_id}/accept", headers=headers)

    def request_switch(self, match_id, payload, headers):
        return self._request("POST", f"/matches/{match_id}/request-switch", payload, headers)

    def reassign_match(self, match_id, headers):
        return self._request("POST", f"/matches/{match_id}/reassign", headers=headers)

    def get_match_thread(self, match_id, headers):
        return self._request("GET", f"/matches/{match_id}/thread", headers=headers)

    def list_match_live_sessions(self, match_id, headers, params=None):
        return self._request("GET", f"/matches/{match_id}/live-sessions", headers=headers, params=params)

    def schedule_live_session(self, match_id, payload, headers):
        return self._request("POST", f"/matches/{match_id}/live-sessions", payload, headers)

    # ---- Live sessions ----
    def get_live_session(self, live_session_id, headers):
        return self._request("GET", f"/live-sessions/{live_session_id}", headers=headers)

    def list_live_session_credits(self, live_session_id, headers, params=None):
        return self._request("GET", f"/live-sessions/{live_session_id}/session-credits", headers=headers, params=params)

    def complete_live_session(self, live_session_id, headers):
        return self._request("POST", f"/live-sessions/{live_session_id}/complete", headers=headers)

    def cancel_live_session(self, live_session_id, headers):
        return self._request("POST", f"/live-sessions/{live_session_id}/cancel", headers=headers)

    def no_show_live_session(self, live_session_id, headers):
        return self._request("POST", f"/live-sessions/{live_session_id}/no-show", headers=headers)

    # ---- Threads & messages ----
    def get_thread(self, thread_id, headers):
        return self._request("GET", f"/threads/{thread_id}", headers=headers)

    def post_message(self, thread_id, payload, headers):
        return self._request("POST", f"/threads/{thread_id}/messages", payload, headers)

    def list_messages(self, thread_id, headers, params=None):
        return self._request("GET", f"/threads/{thread_id}/messages", headers=headers, params=params)

    # ---- Subscriptions & billing ----
    def create_subscription(self, payload, headers):
        return self._request("POST", "/subscriptions", payload, headers)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/subscriptions/{subscription_id}", headers=headers)

    def charge_cycle(self, subscription_id, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/charge-cycle", headers=headers)

    def list_billing_cycles(self, subscription_id, headers, params=None):
        return self._request("GET", f"/subscriptions/{subscription_id}/billing-cycles", headers=headers, params=params)

    def pause_subscription(self, subscription_id, payload, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/pause", payload, headers)

    def resume_subscription(self, subscription_id, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/resume", headers=headers)

    def cancel_subscription(self, subscription_id, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/cancel", headers=headers)

    def finalize_cancel_subscription(self, subscription_id, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/finalize-cancel", headers=headers)

    def get_billing_cycle(self, billing_cycle_id, headers):
        return self._request("GET", f"/billing-cycles/{billing_cycle_id}", headers=headers)

    def list_billing_cycle_session_credits(self, billing_cycle_id, headers, params=None):
        return self._request("GET", f"/billing-cycles/{billing_cycle_id}/session-credits", headers=headers, params=params)

    def get_session_credit(self, session_credit_id, headers):
        return self._request("GET", f"/session-credits/{session_credit_id}", headers=headers)

    def list_session_credit_live_sessions(self, session_credit_id, headers, params=None):
        return self._request("GET", f"/session-credits/{session_credit_id}/live-sessions", headers=headers, params=params)

    # ---- Crisis escalations ----
    def get_crisis_escalation(self, escalation_id, headers):
        return self._request("GET", f"/crisis-escalations/{escalation_id}", headers=headers)

    def acknowledge_escalation(self, escalation_id, headers):
        return self._request("POST", f"/crisis-escalations/{escalation_id}/acknowledge", headers=headers)

    def resolve_escalation(self, escalation_id, headers):
        return self._request("POST", f"/crisis-escalations/{escalation_id}/resolve", headers=headers)

    # ---- Financial aid ----
    def get_financial_aid_application(self, application_id, headers):
        return self._request("GET", f"/financial-aid-applications/{application_id}", headers=headers)

    def approve_financial_aid(self, application_id, headers):
        return self._request("POST", f"/financial-aid-applications/{application_id}/approve", headers=headers)

    def deny_financial_aid(self, application_id, headers):
        return self._request("POST", f"/financial-aid-applications/{application_id}/deny", headers=headers)

    # ---- Superbills ----
    def get_superbill(self, superbill_id, headers):
        return self._request("GET", f"/superbills/{superbill_id}", headers=headers)

    def issue_superbill(self, superbill_id, headers):
        return self._request("POST", f"/superbills/{superbill_id}/issue", headers=headers)

    def void_superbill(self, superbill_id, headers):
        return self._request("POST", f"/superbills/{superbill_id}/void", headers=headers)

    # ---- Test-driving clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
