"""API client: one method per endpoint defined in the PRD (all under /coop)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The runner restarts the server before every test (per-test-server
        # isolation). A pooled keep-alive connection outlives the server
        # process that accepted it, so the first request of the next test can
        # hit a half-open socket and fail with ConnectionResetError /
        # RemoteDisconnected. Sending Connection: close forces a fresh TCP
        # connection per request, making every test talk only to its own
        # freshly booted server instance.
        self.session.headers["Connection"] = "close"

    # --- Clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/coop/_clock/set_current_utc", payload, headers)

    # --- Members ---
    def create_member(self, payload, headers):
        return self._request("POST", "/coop/members", payload, headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/coop/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/coop/members/{member_id}", headers=headers)

    def accept_liability(self, member_id, headers):
        return self._request("POST", f"/coop/members/{member_id}/accept-liability", {}, headers)

    def submit_references(self, member_id, headers):
        return self._request("POST", f"/coop/members/{member_id}/submit-references", {}, headers)

    def finalize_vetting(self, member_id, headers):
        return self._request("POST", f"/coop/members/{member_id}/finalize-vetting", {}, headers)

    def suspend_member(self, member_id, payload, headers):
        return self._request("POST", f"/coop/members/{member_id}/suspend", payload, headers)

    def reinstate_member(self, member_id, headers):
        return self._request("POST", f"/coop/members/{member_id}/reinstate", {}, headers)

    def remove_member(self, member_id, payload, headers):
        return self._request("POST", f"/coop/members/{member_id}/remove", payload, headers)

    # --- Member references ---
    def create_reference(self, member_id, payload, headers):
        return self._request("POST", f"/coop/members/{member_id}/references", payload, headers)

    def list_references(self, member_id, headers, params=None):
        return self._request("GET", f"/coop/members/{member_id}/references", headers=headers, params=params)

    def get_reference(self, reference_id, headers):
        return self._request("GET", f"/coop/member-references/{reference_id}", headers=headers)

    def accept_reference(self, reference_id, headers):
        return self._request("POST", f"/coop/member-references/{reference_id}/accept", {}, headers)

    def reject_reference(self, reference_id, headers):
        return self._request("POST", f"/coop/member-references/{reference_id}/reject", {}, headers)

    def withdraw_reference(self, reference_id, headers):
        return self._request("POST", f"/coop/member-references/{reference_id}/withdraw", {}, headers)

    # --- Pet profiles ---
    def create_pet_profile(self, member_id, payload, headers):
        return self._request("POST", f"/coop/members/{member_id}/pet-profiles", payload, headers)

    def list_pet_profiles(self, member_id, headers, params=None):
        return self._request("GET", f"/coop/members/{member_id}/pet-profiles", headers=headers, params=params)

    def get_pet_profile(self, pet_profile_id, headers):
        return self._request("GET", f"/coop/pet-profiles/{pet_profile_id}", headers=headers)

    def deactivate_pet_profile(self, pet_profile_id, headers):
        return self._request("POST", f"/coop/pet-profiles/{pet_profile_id}/deactivate", {}, headers)

    # --- Holiday windows ---
    def create_holiday_window(self, payload, headers):
        return self._request("POST", "/coop/holiday-windows", payload, headers)

    def list_holiday_windows(self, headers, params=None):
        return self._request("GET", "/coop/holiday-windows", headers=headers, params=params)

    def get_holiday_window(self, window_id, headers):
        return self._request("GET", f"/coop/holiday-windows/{window_id}", headers=headers)

    def disable_holiday_window(self, window_id, headers):
        return self._request("POST", f"/coop/holiday-windows/{window_id}/disable", {}, headers)

    # --- Sitting requests ---
    def create_sitting_request(self, payload, headers):
        return self._request("POST", "/coop/sitting-requests", payload, headers)

    def list_sitting_requests(self, headers, params=None):
        return self._request("GET", "/coop/sitting-requests", headers=headers, params=params)

    def get_sitting_request(self, request_id, headers):
        return self._request("GET", f"/coop/sitting-requests/{request_id}", headers=headers)

    def cancel_sitting_request(self, request_id, payload, headers):
        return self._request("POST", f"/coop/sitting-requests/{request_id}/cancel", payload, headers)

    # --- Claims ---
    def create_claim(self, request_id, payload, headers):
        return self._request("POST", f"/coop/sitting-requests/{request_id}/claims", payload, headers)

    def list_claims(self, request_id, headers, params=None):
        return self._request("GET", f"/coop/sitting-requests/{request_id}/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/coop/sitting-claims/{claim_id}", headers=headers)

    def accept_claim(self, request_id, claim_id, payload, headers):
        return self._request(
            "POST", f"/coop/sitting-requests/{request_id}/claims/{claim_id}/accept", payload, headers
        )

    def reject_claim(self, request_id, claim_id, headers):
        return self._request("POST", f"/coop/sitting-requests/{request_id}/claims/{claim_id}/reject", {}, headers)

    def withdraw_claim(self, request_id, claim_id, headers):
        return self._request("POST", f"/coop/sitting-requests/{request_id}/claims/{claim_id}/withdraw", {}, headers)

    # --- Assignments ---
    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/coop/sitting-assignments/{assignment_id}", headers=headers)

    def get_request_assignment(self, request_id, headers):
        return self._request("GET", f"/coop/sitting-requests/{request_id}/assignment", headers=headers)

    def checkout_assignment(self, assignment_id, headers):
        return self._request("POST", f"/coop/sitting-assignments/{assignment_id}/checkout", {}, headers)

    def settle_assignment(self, assignment_id, headers):
        return self._request("POST", f"/coop/sitting-assignments/{assignment_id}/settle", {}, headers)

    # --- Access handoffs ---
    def get_assignment_handoff(self, assignment_id, headers):
        return self._request("GET", f"/coop/sitting-assignments/{assignment_id}/access-handoff", headers=headers)

    def confirm_handoff(self, handoff_id, headers):
        return self._request("POST", f"/coop/access-handoffs/{handoff_id}/confirm-handoff", {}, headers)

    def confirm_return(self, handoff_id, headers):
        return self._request("POST", f"/coop/access-handoffs/{handoff_id}/confirm-return", {}, headers)

    def report_lost(self, handoff_id, headers):
        return self._request("POST", f"/coop/access-handoffs/{handoff_id}/report-lost", {}, headers)

    def update_handoff(self, handoff_id, payload, headers):
        return self._request("PUT", f"/coop/access-handoffs/{handoff_id}", payload, headers)

    # --- Entry logs ---
    def create_entry_log(self, assignment_id, payload, headers):
        return self._request("POST", f"/coop/sitting-assignments/{assignment_id}/entry-logs", payload, headers)

    def list_entry_logs(self, assignment_id, headers, params=None):
        return self._request(
            "GET", f"/coop/sitting-assignments/{assignment_id}/entry-logs", headers=headers, params=params
        )

    # --- Incidents ---
    def create_incident(self, assignment_id, payload, headers):
        return self._request("POST", f"/coop/sitting-assignments/{assignment_id}/incidents", payload, headers)

    def list_incidents(self, assignment_id, headers, params=None):
        return self._request(
            "GET", f"/coop/sitting-assignments/{assignment_id}/incidents", headers=headers, params=params
        )

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/coop/incidents/{incident_id}", headers=headers)

    def begin_review_incident(self, incident_id, headers):
        return self._request("POST", f"/coop/incidents/{incident_id}/begin-review", {}, headers)

    def resolve_incident(self, incident_id, payload, headers):
        return self._request("POST", f"/coop/incidents/{incident_id}/resolve", payload, headers)

    def dismiss_incident(self, incident_id, headers):
        return self._request("POST", f"/coop/incidents/{incident_id}/dismiss", {}, headers)

    # --- Disputes ---
    def create_dispute(self, payload, headers):
        return self._request("POST", "/coop/disputes", payload, headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/coop/disputes", headers=headers, params=params)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/coop/disputes/{dispute_id}", headers=headers)

    def assign_mediator(self, dispute_id, payload, headers):
        return self._request("POST", f"/coop/disputes/{dispute_id}/assign-mediator", payload, headers)

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/coop/disputes/{dispute_id}/resolve", payload, headers)

    def escalate_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/coop/disputes/{dispute_id}/escalate", payload, headers)

    # --- Credit ledger ---
    def list_credit_ledger(self, member_id, headers, params=None):
        return self._request("GET", f"/coop/members/{member_id}/credit-ledger", headers=headers, params=params)


api_client = ApiClient()
