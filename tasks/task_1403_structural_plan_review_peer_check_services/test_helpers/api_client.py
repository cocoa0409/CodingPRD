"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Jurisdictions ---
    def create_jurisdiction(self, payload, headers):
        return self._request("POST", "/plan-review/jurisdictions", payload, headers)

    def get_jurisdiction(self, jurisdiction_id, headers):
        return self._request("GET", f"/plan-review/jurisdictions/{jurisdiction_id}", headers=headers)

    def update_jurisdiction(self, jurisdiction_id, payload, headers):
        return self._request("PUT", f"/plan-review/jurisdictions/{jurisdiction_id}", payload, headers)

    # --- Reviewers ---
    def create_reviewer(self, payload, headers):
        return self._request("POST", "/plan-review/reviewers", payload, headers)

    def get_reviewer(self, reviewer_id, headers):
        return self._request("GET", f"/plan-review/reviewers/{reviewer_id}", headers=headers)

    # --- Engagements ---
    def create_engagement(self, payload, headers):
        return self._request("POST", "/plan-review/engagements", payload, headers)

    def list_engagements(self, headers, params=None):
        return self._request("GET", "/plan-review/engagements", headers=headers, params=params)

    def get_engagement(self, engagement_id, headers):
        return self._request("GET", f"/plan-review/engagements/{engagement_id}", headers=headers)

    def update_engagement(self, engagement_id, payload, headers):
        return self._request("PUT", f"/plan-review/engagements/{engagement_id}", payload, headers)

    def cancel_engagement(self, engagement_id, headers):
        return self._request("POST", f"/plan-review/engagements/{engagement_id}/cancel", {}, headers)

    # --- Review cycles ---
    def create_cycle(self, payload, headers):
        return self._request("POST", "/plan-review/cycles", payload, headers)

    def list_cycles(self, headers, params=None):
        return self._request("GET", "/plan-review/cycles", headers=headers, params=params)

    def get_cycle(self, cycle_id, headers):
        return self._request("GET", f"/plan-review/cycles/{cycle_id}", headers=headers)

    def issue_comments(self, cycle_id, headers):
        return self._request("POST", f"/plan-review/cycles/{cycle_id}/issue-comments", {}, headers)

    def approve_cycle(self, cycle_id, payload, headers):
        return self._request("POST", f"/plan-review/cycles/{cycle_id}/approve", payload, headers)

    # --- Review assignments ---
    def create_assignment(self, payload, headers):
        return self._request("POST", "/plan-review/assignments", payload, headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/plan-review/assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/plan-review/assignments/{assignment_id}", headers=headers)

    def release_assignment(self, assignment_id, headers):
        return self._request("POST", f"/plan-review/assignments/{assignment_id}/release", {}, headers)

    # --- Deficiency comments / responses ---
    def create_comment(self, payload, headers):
        return self._request("POST", "/plan-review/comments", payload, headers)

    def list_comments(self, headers, params=None):
        return self._request("GET", "/plan-review/comments", headers=headers, params=params)

    def get_comment(self, comment_id, headers):
        return self._request("GET", f"/plan-review/comments/{comment_id}", headers=headers)

    def create_response(self, comment_id, payload, headers):
        return self._request("POST", f"/plan-review/comments/{comment_id}/responses", payload, headers)

    def list_responses(self, comment_id, headers, params=None):
        return self._request("GET", f"/plan-review/comments/{comment_id}/responses", headers=headers, params=params)

    def verify_comment(self, comment_id, headers):
        return self._request("POST", f"/plan-review/comments/{comment_id}/verify", {}, headers)

    def reopen_comment(self, comment_id, payload, headers):
        return self._request("POST", f"/plan-review/comments/{comment_id}/reopen", payload, headers)

    def waive_comment(self, comment_id, payload, headers):
        return self._request("POST", f"/plan-review/comments/{comment_id}/waive", payload, headers)

    # --- Deferred submittals ---
    def create_deferred(self, payload, headers):
        return self._request("POST", "/plan-review/deferred-submittals", payload, headers)

    def list_deferred(self, headers, params=None):
        return self._request("GET", "/plan-review/deferred-submittals", headers=headers, params=params)

    def get_deferred(self, deferred_id, headers):
        return self._request("GET", f"/plan-review/deferred-submittals/{deferred_id}", headers=headers)

    def submit_deferred(self, deferred_id, payload, headers):
        return self._request("POST", f"/plan-review/deferred-submittals/{deferred_id}/submit", payload, headers)

    def approve_deferred(self, deferred_id, headers):
        return self._request("POST", f"/plan-review/deferred-submittals/{deferred_id}/approve", {}, headers)

    def reject_deferred(self, deferred_id, payload, headers):
        return self._request("POST", f"/plan-review/deferred-submittals/{deferred_id}/reject", payload, headers)

    # --- Review records ---
    def list_records(self, headers, params=None):
        return self._request("GET", "/plan-review/records", headers=headers, params=params)

    def get_record(self, record_id, headers):
        return self._request("GET", f"/plan-review/records/{record_id}", headers=headers)

    def seal_record(self, record_id, headers):
        return self._request("POST", f"/plan-review/records/{record_id}/seal", {}, headers)

    def transmit_record(self, record_id, headers):
        return self._request("POST", f"/plan-review/records/{record_id}/transmit", {}, headers)

    # --- Test-driving logical clock (PRD §2.8) ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
