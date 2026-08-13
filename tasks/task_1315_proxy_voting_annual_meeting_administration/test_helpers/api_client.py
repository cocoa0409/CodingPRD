"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Meetings ----
    def create_meeting(self, payload, headers):
        return self._request("POST", "/proxy/meetings", payload, headers)

    def list_meetings(self, headers, params=None):
        return self._request("GET", "/proxy/meetings", headers=headers, params=params)

    def get_meeting(self, meeting_id, headers):
        return self._request("GET", f"/proxy/meetings/{meeting_id}", headers=headers)

    def patch_meeting(self, meeting_id, payload, headers):
        return self._request("PATCH", f"/proxy/meetings/{meeting_id}", payload, headers)

    def lock_record_date(self, meeting_id, headers):
        return self._request("POST", f"/proxy/meetings/{meeting_id}/lock-record-date", {}, headers)

    def open_voting(self, meeting_id, headers):
        return self._request("POST", f"/proxy/meetings/{meeting_id}/open-voting", {}, headers)

    def convene(self, meeting_id, headers):
        return self._request("POST", f"/proxy/meetings/{meeting_id}/convene", {}, headers)

    def adjourn(self, meeting_id, headers):
        return self._request("POST", f"/proxy/meetings/{meeting_id}/adjourn", {}, headers)

    def reconvene(self, meeting_id, headers):
        return self._request("POST", f"/proxy/meetings/{meeting_id}/reconvene", {}, headers)

    def conclude(self, meeting_id, headers, payload=None):
        return self._request("POST", f"/proxy/meetings/{meeting_id}/conclude", payload or {}, headers)

    def cancel_meeting(self, meeting_id, headers):
        return self._request("POST", f"/proxy/meetings/{meeting_id}/cancel", {}, headers)

    def file_8k(self, meeting_id, payload, headers):
        return self._request("POST", f"/proxy/meetings/{meeting_id}/file-8k", payload, headers)

    def get_quorum(self, meeting_id, headers, variant=None):
        params = {"variant": variant} if variant is not None else None
        return self._request("GET", f"/proxy/meetings/{meeting_id}/quorum", headers=headers, params=params)

    # ---- Shareholder accounts ----
    def create_shareholder_account(self, payload, headers):
        return self._request("POST", "/proxy/shareholder-accounts", payload, headers)

    def list_shareholder_accounts(self, headers, params=None):
        return self._request("GET", "/proxy/shareholder-accounts", headers=headers, params=params)

    def get_shareholder_account(self, account_id, headers):
        return self._request("GET", f"/proxy/shareholder-accounts/{account_id}", headers=headers)

    def patch_shareholder_account(self, account_id, payload, headers):
        return self._request("PATCH", f"/proxy/shareholder-accounts/{account_id}", payload, headers)

    # ---- Broker search ----
    def create_broker_search(self, payload, headers):
        return self._request("POST", "/proxy/broker-searches", payload, headers)

    def list_broker_searches(self, headers, params=None):
        return self._request("GET", "/proxy/broker-searches", headers=headers, params=params)

    def get_broker_search(self, search_id, headers):
        return self._request("GET", f"/proxy/broker-searches/{search_id}", headers=headers)

    def respond_broker_search(self, search_id, payload, headers):
        return self._request("POST", f"/proxy/broker-searches/{search_id}/respond", payload, headers)

    # ---- Material distribution ----
    def generate_material_distributions(self, payload, headers):
        return self._request("POST", "/proxy/material-distributions/generate", payload, headers)

    def list_material_distributions(self, headers, params=None):
        return self._request("GET", "/proxy/material-distributions", headers=headers, params=params)

    def get_material_distribution(self, package_id, headers):
        return self._request("GET", f"/proxy/material-distributions/{package_id}", headers=headers)

    def patch_material_distribution(self, package_id, payload, headers):
        return self._request("PATCH", f"/proxy/material-distributions/{package_id}", payload, headers)

    # ---- Proposals ----
    def create_proposal(self, payload, headers):
        return self._request("POST", "/proxy/proposals", payload, headers)

    def list_proposals(self, headers, params=None):
        return self._request("GET", "/proxy/proposals", headers=headers, params=params)

    def get_proposal(self, proposal_id, headers):
        return self._request("GET", f"/proxy/proposals/{proposal_id}", headers=headers)

    def withdraw_proposal(self, proposal_id, headers):
        return self._request("POST", f"/proxy/proposals/{proposal_id}/withdraw", {}, headers)

    def get_tabulation(self, proposal_id, headers, variant=None):
        params = {"variant": variant} if variant is not None else None
        return self._request("GET", f"/proxy/proposals/{proposal_id}/tabulation", headers=headers, params=params)

    # ---- Vote instructions ----
    def create_vote_instruction(self, payload, headers):
        return self._request("POST", "/proxy/vote-instructions", payload, headers)

    def list_vote_instructions(self, headers, params=None):
        return self._request("GET", "/proxy/vote-instructions", headers=headers, params=params)

    def get_vote_instruction(self, vote_id, headers):
        return self._request("GET", f"/proxy/vote-instructions/{vote_id}", headers=headers)

    def revoke_vote(self, vote_id, headers):
        return self._request("POST", f"/proxy/vote-instructions/{vote_id}/revoke", {}, headers)

    # ---- Virtual meeting platform sessions ----
    def create_platform_session(self, payload, headers):
        return self._request("POST", "/proxy/platform-sessions", payload, headers)

    def list_platform_sessions(self, headers, params=None):
        return self._request("GET", "/proxy/platform-sessions", headers=headers, params=params)

    def get_platform_session(self, session_id, headers):
        return self._request("GET", f"/proxy/platform-sessions/{session_id}", headers=headers)

    # ---- Question moderation ----
    def create_question_submission(self, payload, headers):
        return self._request("POST", "/proxy/question-submissions", payload, headers)

    def list_question_submissions(self, headers, params=None):
        return self._request("GET", "/proxy/question-submissions", headers=headers, params=params)

    def get_question_submission(self, question_id, headers):
        return self._request("GET", f"/proxy/question-submissions/{question_id}", headers=headers)

    def moderate_question(self, question_id, payload, headers):
        return self._request("POST", f"/proxy/question-submissions/{question_id}/moderate", payload, headers)

    def resubmit_question(self, question_id, payload, headers):
        return self._request("POST", f"/proxy/question-submissions/{question_id}/resubmit", payload, headers)

    # ---- Vote challenges ----
    def create_vote_challenge(self, payload, headers):
        return self._request("POST", "/proxy/vote-challenges", payload, headers)

    def list_vote_challenges(self, headers, params=None):
        return self._request("GET", "/proxy/vote-challenges", headers=headers, params=params)

    def get_vote_challenge(self, challenge_id, headers):
        return self._request("GET", f"/proxy/vote-challenges/{challenge_id}", headers=headers)

    def adjudicate_challenge(self, challenge_id, payload, headers):
        return self._request("POST", f"/proxy/vote-challenges/{challenge_id}/adjudicate", payload, headers)

    # ---- Solicitation campaigns ----
    def create_solicitation_campaign(self, payload, headers):
        return self._request("POST", "/proxy/solicitation-campaigns", payload, headers)

    def list_solicitation_campaigns(self, headers, params=None):
        return self._request("GET", "/proxy/solicitation-campaigns", headers=headers, params=params)

    def get_solicitation_campaign(self, campaign_id, headers):
        return self._request("GET", f"/proxy/solicitation-campaigns/{campaign_id}", headers=headers)

    # ---- Inspector certification ----
    def create_inspector_certification(self, payload, headers):
        return self._request("POST", "/proxy/inspector-certifications", payload, headers)

    def list_inspector_certifications(self, headers, params=None):
        return self._request("GET", "/proxy/inspector-certifications", headers=headers, params=params)

    def get_inspector_certification(self, certification_id, headers):
        return self._request("GET", f"/proxy/inspector-certifications/{certification_id}", headers=headers)

    def sign_certification(self, certification_id, payload, headers):
        return self._request("POST", f"/proxy/inspector-certifications/{certification_id}/sign", payload, headers)

    # ---- Test-driving clock ----
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/proxy/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
