"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ───── TestCenter ─────────────────────────────────────────────────────────
    def create_test_center(self, payload, headers):
        return self._request("POST", "/test-centers", payload, headers)

    def get_test_center(self, center_id, headers):
        return self._request("GET", f"/test-centers/{center_id}", headers=headers)

    # ───── TestSession ────────────────────────────────────────────────────────
    def create_test_session(self, payload, headers):
        return self._request("POST", "/test-sessions", payload, headers)

    def get_test_session(self, session_id, headers):
        return self._request("GET", f"/test-sessions/{session_id}", headers=headers)

    def list_test_sessions(self, headers, params=None):
        return self._request("GET", "/test-sessions", headers=headers, params=params)

    def close_test_session(self, session_id, headers):
        return self._request("POST", f"/test-sessions/{session_id}/close", {}, headers)

    # ───── Candidate ──────────────────────────────────────────────────────────
    def create_candidate(self, payload, headers):
        return self._request("POST", "/candidates", payload, headers)

    def get_candidate(self, candidate_id, headers):
        return self._request("GET", f"/candidates/{candidate_id}", headers=headers)

    def list_candidate_clep_claims(self, candidate_id, headers, params=None):
        return self._request(
            "GET", f"/candidates/{candidate_id}/clep-claims", headers=headers, params=params
        )

    # ───── Registration ───────────────────────────────────────────────────────
    def create_registration(self, payload, headers):
        return self._request("POST", "/registrations", payload, headers)

    def get_registration(self, registration_id, headers):
        return self._request("GET", f"/registrations/{registration_id}", headers=headers)

    def list_registrations(self, headers, params=None):
        return self._request("GET", "/registrations", headers=headers, params=params)

    def confirm_registration(self, registration_id, headers):
        return self._request("POST", f"/registrations/{registration_id}/confirm", {}, headers)

    def cancel_registration(self, registration_id, headers):
        return self._request("POST", f"/registrations/{registration_id}/cancel", {}, headers)

    def check_in_registration(self, registration_id, headers):
        return self._request("POST", f"/registrations/{registration_id}/check-in", {}, headers)

    # ───── Registration AXIS 2: scoring ───────────────────────────────────────
    def create_score_report(self, registration_id, payload, headers):
        return self._request(
            "POST", f"/registrations/{registration_id}/score-reports", payload, headers
        )

    def release_score(self, registration_id, headers):
        return self._request("POST", f"/registrations/{registration_id}/release-score", {}, headers)

    def cancel_score(self, registration_id, headers):
        return self._request("POST", f"/registrations/{registration_id}/cancel-score", {}, headers)

    # ───── IDVerification ─────────────────────────────────────────────────────
    def create_id_verification(self, registration_id, payload, headers):
        return self._request(
            "POST", f"/registrations/{registration_id}/id-verifications", payload, headers
        )

    def list_id_verifications(self, registration_id, headers, params=None):
        return self._request(
            "GET", f"/registrations/{registration_id}/id-verifications", headers=headers, params=params
        )

    # ───── AccommodationRequest ───────────────────────────────────────────────
    def create_accommodation_request(self, payload, headers):
        return self._request("POST", "/accommodation-requests", payload, headers)

    def get_accommodation_request(self, request_id, headers):
        return self._request("GET", f"/accommodation-requests/{request_id}", headers=headers)

    def list_accommodation_requests(self, headers, params=None):
        return self._request("GET", "/accommodation-requests", headers=headers, params=params)

    def begin_review_accommodation(self, request_id, headers):
        return self._request("POST", f"/accommodation-requests/{request_id}/begin-review", {}, headers)

    def request_info_accommodation(self, request_id, payload, headers):
        return self._request("POST", f"/accommodation-requests/{request_id}/request-info", payload, headers)

    def resubmit_accommodation(self, request_id, headers):
        return self._request("POST", f"/accommodation-requests/{request_id}/resubmit", {}, headers)

    def approve_accommodation(self, request_id, headers):
        return self._request("POST", f"/accommodation-requests/{request_id}/approve", {}, headers)

    def deny_accommodation(self, request_id, payload, headers):
        return self._request("POST", f"/accommodation-requests/{request_id}/deny", payload, headers)

    # ───── StandbyEntry ───────────────────────────────────────────────────────
    def create_standby_entry(self, payload, headers):
        return self._request("POST", "/standby-entries", payload, headers)

    def get_standby_entry(self, entry_id, headers):
        return self._request("GET", f"/standby-entries/{entry_id}", headers=headers)

    def list_standby_entries(self, headers, params=None):
        return self._request("GET", "/standby-entries", headers=headers, params=params)

    def claim_standby_entry(self, entry_id, payload, headers):
        return self._request("POST", f"/standby-entries/{entry_id}/claim", payload, headers)

    def decline_standby_entry(self, entry_id, headers):
        return self._request("POST", f"/standby-entries/{entry_id}/decline", {}, headers)

    # ───── ScoreReport ────────────────────────────────────────────────────────
    def get_score_report(self, report_id, headers):
        return self._request("GET", f"/score-reports/{report_id}", headers=headers)

    def list_score_reports(self, headers, params=None):
        return self._request("GET", "/score-reports", headers=headers, params=params)

    # ───── ScoreSend ──────────────────────────────────────────────────────────
    def create_score_send(self, payload, headers):
        return self._request("POST", "/score-sends", payload, headers)

    def list_score_sends(self, registration_id, headers, params=None):
        return self._request(
            "GET", f"/registrations/{registration_id}/score-sends", headers=headers, params=params
        )

    # ───── CLEPClaim ──────────────────────────────────────────────────────────
    def create_clep_claim(self, payload, headers):
        return self._request("POST", "/clep-claims", payload, headers)

    def get_clep_claim(self, claim_id, headers):
        return self._request("GET", f"/clep-claims/{claim_id}", headers=headers)

    def adjudicate_clep_claim(self, claim_id, headers):
        return self._request("POST", f"/clep-claims/{claim_id}/adjudicate", {}, headers)

    # ───── Test-driving clock ─────────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
