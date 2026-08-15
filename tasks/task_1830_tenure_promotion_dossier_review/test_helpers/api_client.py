"""API client: one method per endpoint defined in the PRD (§4 routing table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- test-driving logical clock (PRD §2.4) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # --- candidates (PRD §3.1) ---
    def create_candidate(self, payload, headers):
        return self._request("POST", "/api/candidates", payload, headers)

    def get_candidate(self, candidate_id, headers):
        return self._request("GET", f"/api/candidates/{candidate_id}", headers=headers)

    # --- tenure cases (PRD §3.1, §3.2, §3.7, §3.9) ---
    def create_case(self, payload, headers):
        return self._request("POST", "/api/cases", payload, headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/api/cases", headers=headers, params=params)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/api/cases/{case_id}", headers=headers)

    def submit_dossier(self, case_id, headers):
        return self._request("POST", f"/api/cases/{case_id}/submit-dossier", headers=headers)

    def return_for_revision(self, case_id, headers):
        return self._request("POST", f"/api/cases/{case_id}/return-for-revision", headers=headers)

    def resume_assembly(self, case_id, headers):
        return self._request("POST", f"/api/cases/{case_id}/resume-assembly", headers=headers)

    def close_solicitation(self, case_id, headers):
        return self._request("POST", f"/api/cases/{case_id}/close-solicitation", headers=headers)

    def advance_stage(self, case_id, headers):
        return self._request("POST", f"/api/cases/{case_id}/advance-stage", headers=headers)

    def withdraw_case(self, case_id, headers):
        return self._request("POST", f"/api/cases/{case_id}/withdraw", headers=headers)

    def notify_case(self, case_id, headers):
        return self._request("POST", f"/api/cases/{case_id}/notify", headers=headers)

    def close_case(self, case_id, headers):
        return self._request("POST", f"/api/cases/{case_id}/close", headers=headers)

    def archive_case(self, case_id, headers):
        return self._request("POST", f"/api/cases/{case_id}/archive", headers=headers)

    def purge_case(self, case_id, headers):
        return self._request("POST", f"/api/cases/{case_id}/purge", headers=headers)

    # --- dossier items (PRD §3.2) ---
    def create_dossier_item(self, payload, headers):
        return self._request("POST", "/api/dossier-items", payload, headers)

    def list_dossier_items(self, headers, params=None):
        return self._request("GET", "/api/dossier-items", headers=headers, params=params)

    def get_dossier_item(self, item_id, headers):
        return self._request("GET", f"/api/dossier-items/{item_id}", headers=headers)

    def submit_dossier_item(self, item_id, headers):
        return self._request("POST", f"/api/dossier-items/{item_id}/submit", headers=headers)

    def return_dossier_item(self, item_id, headers):
        return self._request("POST", f"/api/dossier-items/{item_id}/return", headers=headers)

    def withdraw_dossier_item(self, item_id, headers):
        return self._request("POST", f"/api/dossier-items/{item_id}/withdraw", headers=headers)

    # --- external reviewers (PRD §3.4) ---
    def create_reviewer(self, payload, headers):
        return self._request("POST", "/api/reviewers", payload, headers)

    def get_reviewer(self, reviewer_id, headers):
        return self._request("GET", f"/api/reviewers/{reviewer_id}", headers=headers)

    # --- reviewer invitations (PRD §3.4) ---
    def create_invitation(self, payload, headers):
        return self._request("POST", "/api/invitations", payload, headers)

    def list_invitations(self, headers, params=None):
        return self._request("GET", "/api/invitations", headers=headers, params=params)

    def get_invitation(self, invitation_id, headers):
        return self._request("GET", f"/api/invitations/{invitation_id}", headers=headers)

    def accept_invitation(self, invitation_id, headers):
        return self._request("POST", f"/api/invitations/{invitation_id}/accept", headers=headers)

    def decline_invitation(self, invitation_id, headers):
        return self._request("POST", f"/api/invitations/{invitation_id}/decline", headers=headers)

    def submit_letter(self, invitation_id, payload, headers):
        return self._request("POST", f"/api/invitations/{invitation_id}/submit-letter", payload, headers)

    def withdraw_invitation(self, invitation_id, headers):
        return self._request("POST", f"/api/invitations/{invitation_id}/withdraw", headers=headers)

    # --- committees (PRD §3.5) ---
    def create_committee(self, payload, headers):
        return self._request("POST", "/api/committees", payload, headers)

    def get_committee(self, committee_id, headers):
        return self._request("GET", f"/api/committees/{committee_id}", headers=headers)

    # --- committee members (PRD §3.5) ---
    def create_member(self, payload, headers):
        return self._request("POST", "/api/members", payload, headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/api/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/api/members/{member_id}", headers=headers)

    def deactivate_member(self, member_id, headers):
        return self._request("POST", f"/api/members/{member_id}/deactivate", headers=headers)

    # --- review rounds (PRD §3.5, §3.6) ---
    def list_rounds(self, headers, params=None):
        return self._request("GET", "/api/rounds", headers=headers, params=params)

    def get_round(self, round_id, headers):
        return self._request("GET", f"/api/rounds/{round_id}", headers=headers)

    def open_round(self, round_id, headers):
        return self._request("POST", f"/api/rounds/{round_id}/open", headers=headers)

    def close_voting(self, round_id, headers):
        return self._request("POST", f"/api/rounds/{round_id}/close-voting", headers=headers)

    def certify_round(self, round_id, payload, headers):
        return self._request("POST", f"/api/rounds/{round_id}/certify", payload, headers)

    def reopen_round(self, round_id, headers):
        return self._request("POST", f"/api/rounds/{round_id}/reopen", headers=headers)

    # --- votes (PRD §3.5) ---
    def create_vote(self, payload, headers):
        return self._request("POST", "/api/votes", payload, headers)

    def list_votes(self, headers, params=None):
        return self._request("GET", "/api/votes", headers=headers, params=params)

    def get_vote(self, vote_id, headers):
        return self._request("GET", f"/api/votes/{vote_id}", headers=headers)

    def patch_vote(self, vote_id, payload, headers):
        return self._request("PATCH", f"/api/votes/{vote_id}", payload, headers)

    def retract_vote(self, vote_id, headers):
        return self._request("POST", f"/api/votes/{vote_id}/retract", headers=headers)

    # --- clock-extension requests (PRD §3.3) ---
    def create_clock_extension(self, payload, headers):
        return self._request("POST", "/api/clock-extensions", payload, headers)

    def list_clock_extensions(self, headers, params=None):
        return self._request("GET", "/api/clock-extensions", headers=headers, params=params)

    def get_clock_extension(self, extension_id, headers):
        return self._request("GET", f"/api/clock-extensions/{extension_id}", headers=headers)

    def approve_clock_extension(self, extension_id, headers):
        return self._request("POST", f"/api/clock-extensions/{extension_id}/approve", headers=headers)

    def deny_clock_extension(self, extension_id, headers):
        return self._request("POST", f"/api/clock-extensions/{extension_id}/deny", headers=headers)

    def rescind_clock_extension(self, extension_id, headers):
        return self._request("POST", f"/api/clock-extensions/{extension_id}/rescind", headers=headers)

    # --- mid-tenure reviews (PRD §3.3) ---
    def create_midterm_review(self, payload, headers):
        return self._request("POST", "/api/midterm-reviews", payload, headers)

    def list_midterm_reviews(self, headers, params=None):
        return self._request("GET", "/api/midterm-reviews", headers=headers, params=params)

    def get_midterm_review(self, review_id, headers):
        return self._request("GET", f"/api/midterm-reviews/{review_id}", headers=headers)

    def complete_midterm_review(self, review_id, payload, headers):
        return self._request("POST", f"/api/midterm-reviews/{review_id}/complete", payload, headers)

    # --- provost decisions (PRD §3.7) ---
    def create_decision(self, payload, headers):
        return self._request("POST", "/api/decisions", payload, headers)

    def list_decisions(self, headers, params=None):
        return self._request("GET", "/api/decisions", headers=headers, params=params)

    def get_decision(self, decision_id, headers):
        return self._request("GET", f"/api/decisions/{decision_id}", headers=headers)

    # --- appeals (PRD §3.8) ---
    def create_appeal(self, payload, headers):
        return self._request("POST", "/api/appeals", payload, headers)

    def list_appeals(self, headers, params=None):
        return self._request("GET", "/api/appeals", headers=headers, params=params)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/api/appeals/{appeal_id}", headers=headers)

    def begin_review_appeal(self, appeal_id, headers):
        return self._request("POST", f"/api/appeals/{appeal_id}/begin-review", headers=headers)

    def resolve_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/api/appeals/{appeal_id}/resolve", payload, headers)

    def withdraw_appeal(self, appeal_id, headers):
        return self._request("POST", f"/api/appeals/{appeal_id}/withdraw", headers=headers)


api_client = ApiClient()
