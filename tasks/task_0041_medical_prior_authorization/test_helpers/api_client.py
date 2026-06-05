"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- registration surface (Anonymous) ---
    def create_provider(self, payload, headers=None):
        return self._request("POST", "/providers", payload, headers=headers)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/providers/{provider_id}", headers=headers)

    def create_payer(self, payload, headers=None):
        return self._request("POST", "/payers", payload, headers=headers)

    def get_payer(self, payer_id, headers):
        return self._request("GET", f"/payers/{payer_id}", headers=headers)

    def create_member(self, payload, headers=None):
        return self._request("POST", "/members", payload, headers=headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def create_reviewer(self, payload, headers=None):
        return self._request("POST", "/reviewers", payload, headers=headers)

    def get_reviewer(self, reviewer_id, headers):
        return self._request("GET", f"/reviewers/{reviewer_id}", headers=headers)

    def list_reviewers(self, headers, params=None):
        return self._request("GET", "/reviewers", headers=headers, params=params)

    # --- authorization requests ---
    def create_authorization_request(self, payload, headers):
        return self._request("POST", "/authorization-requests", payload, headers=headers)

    def get_authorization_request(self, request_id, headers):
        return self._request("GET", f"/authorization-requests/{request_id}", headers=headers)

    def list_authorization_requests(self, headers, params=None):
        return self._request("GET", "/authorization-requests", headers=headers, params=params)

    def submit_request(self, request_id, headers):
        return self._request("POST", f"/authorization-requests/{request_id}/submit", {}, headers=headers)

    def start_review(self, request_id, headers):
        return self._request("POST", f"/authorization-requests/{request_id}/start-review", {}, headers=headers)

    def resume_review(self, request_id, headers):
        return self._request("POST", f"/authorization-requests/{request_id}/resume-review", {}, headers=headers)

    def expire_request(self, request_id, headers):
        return self._request("POST", f"/authorization-requests/{request_id}/expire", {}, headers=headers)

    # --- evidence ---
    def create_clinical_evidence(self, payload, headers):
        return self._request("POST", "/clinical-evidence", payload, headers=headers)

    def get_clinical_evidence(self, evidence_id, headers):
        return self._request("GET", f"/clinical-evidence/{evidence_id}", headers=headers)

    def list_clinical_evidence(self, headers, params=None):
        return self._request("GET", "/clinical-evidence", headers=headers, params=params)

    # --- review decisions ---
    def create_review_decision(self, payload, headers):
        return self._request("POST", "/review-decisions", payload, headers=headers)

    def get_review_decision(self, decision_id, headers):
        return self._request("GET", f"/review-decisions/{decision_id}", headers=headers)

    def list_review_decisions(self, headers, params=None):
        return self._request("GET", "/review-decisions", headers=headers, params=params)

    # --- peer to peer ---
    def create_peer_to_peer_session(self, payload, headers):
        return self._request("POST", "/peer-to-peer-sessions", payload, headers=headers)

    def get_peer_to_peer_session(self, session_id, headers):
        return self._request("GET", f"/peer-to-peer-sessions/{session_id}", headers=headers)

    def list_peer_to_peer_sessions(self, headers, params=None):
        return self._request("GET", "/peer-to-peer-sessions", headers=headers, params=params)

    def complete_peer_to_peer_session(self, session_id, headers):
        return self._request("POST", f"/peer-to-peer-sessions/{session_id}/complete", {}, headers=headers)

    def cancel_peer_to_peer_session(self, session_id, headers):
        return self._request("POST", f"/peer-to-peer-sessions/{session_id}/cancel", {}, headers=headers)

    # --- appeals ---
    def create_appeal(self, payload, headers):
        return self._request("POST", "/appeals", payload, headers=headers)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/appeals/{appeal_id}", headers=headers)

    def list_appeals(self, headers, params=None):
        return self._request("GET", "/appeals", headers=headers, params=params)

    def decide_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/appeals/{appeal_id}/decide", payload, headers=headers)

    def external_decide_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/appeals/{appeal_id}/external-decide", payload, headers=headers)

    def withdraw_appeal(self, appeal_id, headers):
        return self._request("POST", f"/appeals/{appeal_id}/withdraw", {}, headers=headers)

    # --- test-driving clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers=headers)


api_client = ApiClient()
