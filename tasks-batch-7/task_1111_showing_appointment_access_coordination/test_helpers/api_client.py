"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/showing-desk"


class ApiClient(GenericApiClient):
    # ----- ops / clock -----
    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    def run_expiration_sweep(self, headers):
        return self._request("POST", f"{PREFIX}/_ops/run_expiration_sweep", {}, headers)

    # ----- sellers -----
    def create_seller(self, payload, headers):
        return self._request("POST", f"{PREFIX}/sellers", payload, headers)

    def get_seller(self, seller_id, headers):
        return self._request("GET", f"{PREFIX}/sellers/{seller_id}", headers=headers)

    def update_seller_approval_settings(self, seller_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/sellers/{seller_id}/approval-settings", payload, headers)

    # ----- agents / verification -----
    def create_agent(self, payload, headers):
        return self._request("POST", f"{PREFIX}/agents", payload, headers)

    def get_agent(self, agent_id, headers):
        return self._request("GET", f"{PREFIX}/agents/{agent_id}", headers=headers)

    def create_verification_case(self, agent_id, payload, headers):
        return self._request("POST", f"{PREFIX}/agents/{agent_id}/verification-cases", payload, headers)

    def list_verification_cases(self, agent_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/agents/{agent_id}/verification-cases", headers=headers, params=params)

    def review_verification_case(self, case_id, payload, headers):
        return self._request("POST", f"{PREFIX}/verification-cases/{case_id}/review", payload, headers)

    def resubmit_verification_case(self, case_id, payload, headers):
        return self._request("POST", f"{PREFIX}/verification-cases/{case_id}/resubmit", payload, headers)

    def list_agent_strikes(self, agent_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/agents/{agent_id}/strikes", headers=headers, params=params)

    def forgive_strike(self, strike_id, payload, headers):
        return self._request("POST", f"{PREFIX}/strikes/{strike_id}/forgive", payload, headers)

    # ----- listings -----
    def create_listing(self, payload, headers):
        return self._request("POST", f"{PREFIX}/listings", payload, headers)

    def get_listing(self, listing_id, headers):
        return self._request("GET", f"{PREFIX}/listings/{listing_id}", headers=headers)

    def list_listings(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/listings", headers=headers, params=params)

    def update_listing_policy(self, listing_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/listings/{listing_id}/policy", payload, headers)

    def pause_listing(self, listing_id, headers):
        return self._request("POST", f"{PREFIX}/listings/{listing_id}/pause", {}, headers)

    def resume_listing(self, listing_id, headers):
        return self._request("POST", f"{PREFIX}/listings/{listing_id}/resume", {}, headers)

    def withdraw_listing(self, listing_id, headers):
        return self._request("POST", f"{PREFIX}/listings/{listing_id}/withdraw", {}, headers)

    # ----- blackout windows -----
    def create_blackout_window(self, listing_id, payload, headers):
        return self._request("POST", f"{PREFIX}/listings/{listing_id}/blackout-windows", payload, headers)

    def list_blackout_windows(self, listing_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/listings/{listing_id}/blackout-windows", headers=headers, params=params)

    def delete_blackout_window(self, window_id, headers):
        return self._request("DELETE", f"{PREFIX}/blackout-windows/{window_id}", None, headers)

    # ----- showing requests -----
    def create_showing_request(self, payload, headers):
        return self._request("POST", f"{PREFIX}/showing-requests", payload, headers)

    def get_showing_request(self, request_id, headers):
        return self._request("GET", f"{PREFIX}/showing-requests/{request_id}", headers=headers)

    def list_showing_requests(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/showing-requests", headers=headers, params=params)

    def approve_showing_request(self, request_id, headers):
        return self._request("POST", f"{PREFIX}/showing-requests/{request_id}/approve", {}, headers)

    def decline_showing_request(self, request_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/showing-requests/{request_id}/decline", payload or {}, headers)

    def confirm_showing_request(self, request_id, headers):
        return self._request("POST", f"{PREFIX}/showing-requests/{request_id}/confirm", {}, headers)

    def cancel_showing_request(self, request_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/showing-requests/{request_id}/cancel", payload or {}, headers)

    def reschedule_showing_request(self, request_id, payload, headers):
        return self._request("POST", f"{PREFIX}/showing-requests/{request_id}/reschedule", payload, headers)

    def declare_no_show(self, request_id, headers):
        return self._request("POST", f"{PREFIX}/showing-requests/{request_id}/declare-no-show", {}, headers)

    # ----- access credentials -----
    def issue_access_credential(self, request_id, payload, headers):
        return self._request("POST", f"{PREFIX}/showing-requests/{request_id}/access-credentials", payload, headers)

    def list_access_credentials(self, request_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/showing-requests/{request_id}/access-credentials", headers=headers, params=params)

    def redeem_access_credential(self, credential_id, headers):
        return self._request("POST", f"{PREFIX}/access-credentials/{credential_id}/redeem", {}, headers)

    def revoke_access_credential(self, credential_id, headers):
        return self._request("POST", f"{PREFIX}/access-credentials/{credential_id}/revoke", {}, headers)

    # ----- strikes under a request -----
    def list_showing_request_strikes(self, request_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/showing-requests/{request_id}/strikes", headers=headers, params=params)

    # ----- feedback -----
    def get_feedback_request_of_showing(self, request_id, headers):
        return self._request("GET", f"{PREFIX}/showing-requests/{request_id}/feedback-request", headers=headers)

    def submit_feedback(self, feedback_id, payload, headers):
        return self._request("POST", f"{PREFIX}/feedback-requests/{feedback_id}/submit", payload, headers)

    # ----- activity trail / report -----
    def list_listing_activity_events(self, listing_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/listings/{listing_id}/activity-events", headers=headers, params=params)

    def list_showing_request_activity_events(self, request_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/showing-requests/{request_id}/activity-events", headers=headers, params=params)

    def get_activity_report(self, listing_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/listings/{listing_id}/activity-report", headers=headers, params=params)


api_client = ApiClient()
