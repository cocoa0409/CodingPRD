"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # ------------------------------------------------------------------
    # Code cycles
    # ------------------------------------------------------------------
    def create_code_cycle(self, payload, headers):
        return self._request("POST", "/code-cycles", payload, headers)

    def list_code_cycles(self, headers, params=None):
        return self._request("GET", "/code-cycles", headers=headers, params=params)

    def get_code_cycle(self, code_cycle_id, headers):
        return self._request("GET", f"/code-cycles/{code_cycle_id}", headers=headers)

    def set_code_cycle_status(self, code_cycle_id, payload, headers):
        return self._request(
            "POST", f"/code-cycles/{code_cycle_id}/status", payload, headers
        )

    def create_discipline_committee(self, code_cycle_id, payload, headers):
        return self._request(
            "POST",
            f"/code-cycles/{code_cycle_id}/discipline-committees",
            payload,
            headers,
        )

    def list_cycle_discipline_committees(self, code_cycle_id, headers, params=None):
        return self._request(
            "GET",
            f"/code-cycles/{code_cycle_id}/discipline-committees",
            headers=headers,
            params=params,
        )

    def list_cycle_amendment_proposals(self, code_cycle_id, headers, params=None):
        return self._request(
            "GET",
            f"/code-cycles/{code_cycle_id}/amendment-proposals",
            headers=headers,
            params=params,
        )

    def list_cycle_adoption_rules(self, code_cycle_id, headers, params=None):
        return self._request(
            "GET",
            f"/code-cycles/{code_cycle_id}/adoption-rules",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Discipline committees and members
    # ------------------------------------------------------------------
    def list_discipline_committees(self, headers, params=None):
        return self._request(
            "GET", "/discipline-committees", headers=headers, params=params
        )

    def get_discipline_committee(self, committee_id, headers):
        return self._request(
            "GET", f"/discipline-committees/{committee_id}", headers=headers
        )

    def create_committee_member(self, committee_id, payload, headers):
        return self._request(
            "POST", f"/discipline-committees/{committee_id}/members", payload, headers
        )

    def list_committee_members_of_committee(self, committee_id, headers, params=None):
        return self._request(
            "GET",
            f"/discipline-committees/{committee_id}/members",
            headers=headers,
            params=params,
        )

    def list_committee_amendment_proposals(self, committee_id, headers, params=None):
        return self._request(
            "GET",
            f"/discipline-committees/{committee_id}/amendment-proposals",
            headers=headers,
            params=params,
        )

    def list_committee_hearings(self, committee_id, headers, params=None):
        return self._request(
            "GET",
            f"/discipline-committees/{committee_id}/hearings",
            headers=headers,
            params=params,
        )

    def list_committee_interpretation_requests(
        self, committee_id, headers, params=None
    ):
        return self._request(
            "GET",
            f"/discipline-committees/{committee_id}/interpretation-requests",
            headers=headers,
            params=params,
        )

    def list_committee_members(self, headers, params=None):
        return self._request(
            "GET", "/committee-members", headers=headers, params=params
        )

    def get_committee_member(self, member_id, headers):
        return self._request(
            "GET", f"/committee-members/{member_id}", headers=headers
        )

    def act_on_committee_member_recusal(self, member_id, payload, headers):
        return self._request(
            "POST", f"/committee-members/{member_id}/recusal", payload, headers
        )

    # ------------------------------------------------------------------
    # Amendment proposals
    # ------------------------------------------------------------------
    def create_amendment_proposal(self, payload, headers):
        return self._request("POST", "/amendment-proposals", payload, headers)

    def list_amendment_proposals(self, headers, params=None):
        return self._request(
            "GET", "/amendment-proposals", headers=headers, params=params
        )

    def get_amendment_proposal(self, proposal_id, headers):
        return self._request(
            "GET", f"/amendment-proposals/{proposal_id}", headers=headers
        )

    def screen_amendment_proposal(self, proposal_id, payload, headers):
        return self._request(
            "POST", f"/amendment-proposals/{proposal_id}/screening", payload, headers
        )

    def create_impact_analysis(self, proposal_id, payload, headers):
        return self._request(
            "POST",
            f"/amendment-proposals/{proposal_id}/impact-analyses",
            payload,
            headers,
        )

    def list_proposal_impact_analyses(self, proposal_id, headers, params=None):
        return self._request(
            "GET",
            f"/amendment-proposals/{proposal_id}/impact-analyses",
            headers=headers,
            params=params,
        )

    def act_on_comment_window(self, proposal_id, payload, headers):
        return self._request(
            "POST",
            f"/amendment-proposals/{proposal_id}/comment-window",
            payload,
            headers,
        )

    def create_public_comment(self, proposal_id, payload, headers):
        return self._request(
            "POST", f"/amendment-proposals/{proposal_id}/comments", payload, headers
        )

    def list_proposal_comments(self, proposal_id, headers, params=None):
        return self._request(
            "GET",
            f"/amendment-proposals/{proposal_id}/comments",
            headers=headers,
            params=params,
        )

    def list_proposal_vote_records(self, proposal_id, headers, params=None):
        return self._request(
            "GET",
            f"/amendment-proposals/{proposal_id}/vote-records",
            headers=headers,
            params=params,
        )

    def reopen_amendment_proposal(self, proposal_id, payload, headers):
        return self._request(
            "POST", f"/amendment-proposals/{proposal_id}/reopen", payload, headers
        )

    # ------------------------------------------------------------------
    # Impact analyses
    # ------------------------------------------------------------------
    def list_impact_analyses(self, headers, params=None):
        return self._request("GET", "/impact-analyses", headers=headers, params=params)

    def get_impact_analysis(self, analysis_id, headers):
        return self._request("GET", f"/impact-analyses/{analysis_id}", headers=headers)

    def review_impact_analysis(self, analysis_id, payload, headers):
        return self._request(
            "POST", f"/impact-analyses/{analysis_id}/review", payload, headers
        )

    # ------------------------------------------------------------------
    # Public comments
    # ------------------------------------------------------------------
    def list_public_comments(self, headers, params=None):
        return self._request("GET", "/public-comments", headers=headers, params=params)

    def get_public_comment(self, comment_id, headers):
        return self._request("GET", f"/public-comments/{comment_id}", headers=headers)

    # ------------------------------------------------------------------
    # Hearings and votes
    # ------------------------------------------------------------------
    def create_hearing(self, payload, headers):
        return self._request("POST", "/hearings", payload, headers)

    def list_hearings(self, headers, params=None):
        return self._request("GET", "/hearings", headers=headers, params=params)

    def get_hearing(self, hearing_id, headers):
        return self._request("GET", f"/hearings/{hearing_id}", headers=headers)

    def fill_hearing_agenda(self, hearing_id, payload, headers):
        return self._request(
            "POST", f"/hearings/{hearing_id}/agenda", payload, headers
        )

    def convene_hearing(self, hearing_id, payload, headers):
        return self._request(
            "POST", f"/hearings/{hearing_id}/convene", payload, headers
        )

    def adjourn_hearing(self, hearing_id, headers, payload=None):
        return self._request(
            "POST", f"/hearings/{hearing_id}/adjourn", payload, headers
        )

    def record_vote(self, hearing_id, payload, headers):
        return self._request("POST", f"/hearings/{hearing_id}/votes", payload, headers)

    def list_hearing_votes(self, hearing_id, headers, params=None):
        return self._request(
            "GET", f"/hearings/{hearing_id}/votes", headers=headers, params=params
        )

    def list_vote_records(self, headers, params=None):
        return self._request("GET", "/vote-records", headers=headers, params=params)

    def get_vote_record(self, vote_record_id, headers):
        return self._request("GET", f"/vote-records/{vote_record_id}", headers=headers)

    # ------------------------------------------------------------------
    # Adoption rules
    # ------------------------------------------------------------------
    def create_adoption_rule(self, payload, headers):
        return self._request("POST", "/adoption-rules", payload, headers)

    def list_adoption_rules(self, headers, params=None):
        return self._request("GET", "/adoption-rules", headers=headers, params=params)

    def get_adoption_rule(self, adoption_rule_id, headers):
        return self._request(
            "GET", f"/adoption-rules/{adoption_rule_id}", headers=headers
        )

    def set_adoption_rule_status(self, adoption_rule_id, payload, headers):
        return self._request(
            "POST", f"/adoption-rules/{adoption_rule_id}/status", payload, headers
        )

    def list_rule_local_amendments(self, adoption_rule_id, headers, params=None):
        return self._request(
            "GET",
            f"/adoption-rules/{adoption_rule_id}/local-amendments",
            headers=headers,
            params=params,
        )

    def list_rule_interpretation_requests(self, adoption_rule_id, headers, params=None):
        return self._request(
            "GET",
            f"/adoption-rules/{adoption_rule_id}/interpretation-requests",
            headers=headers,
            params=params,
        )

    def list_rule_training_sessions(self, adoption_rule_id, headers, params=None):
        return self._request(
            "GET",
            f"/adoption-rules/{adoption_rule_id}/training-sessions",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Jurisdictions
    # ------------------------------------------------------------------
    def create_jurisdiction(self, payload, headers):
        return self._request("POST", "/jurisdictions", payload, headers)

    def list_jurisdictions(self, headers, params=None):
        return self._request("GET", "/jurisdictions", headers=headers, params=params)

    def get_jurisdiction(self, jurisdiction_id, headers):
        return self._request(
            "GET", f"/jurisdictions/{jurisdiction_id}", headers=headers
        )

    def list_jurisdiction_local_amendments(self, jurisdiction_id, headers, params=None):
        return self._request(
            "GET",
            f"/jurisdictions/{jurisdiction_id}/local-amendments",
            headers=headers,
            params=params,
        )

    def list_jurisdiction_interpretation_requests(
        self, jurisdiction_id, headers, params=None
    ):
        return self._request(
            "GET",
            f"/jurisdictions/{jurisdiction_id}/interpretation-requests",
            headers=headers,
            params=params,
        )

    def list_jurisdiction_hosted_training_sessions(
        self, jurisdiction_id, headers, params=None
    ):
        return self._request(
            "GET",
            f"/jurisdictions/{jurisdiction_id}/hosted-training-sessions",
            headers=headers,
            params=params,
        )

    def list_jurisdiction_training_enrollments(
        self, jurisdiction_id, headers, params=None
    ):
        return self._request(
            "GET",
            f"/jurisdictions/{jurisdiction_id}/training-enrollments",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Local amendments
    # ------------------------------------------------------------------
    def create_local_amendment(self, payload, headers):
        return self._request("POST", "/local-amendments", payload, headers)

    def list_local_amendments(self, headers, params=None):
        return self._request(
            "GET", "/local-amendments", headers=headers, params=params
        )

    def get_local_amendment(self, local_amendment_id, headers):
        return self._request(
            "GET", f"/local-amendments/{local_amendment_id}", headers=headers
        )

    def review_local_amendment(self, local_amendment_id, payload, headers):
        return self._request(
            "POST", f"/local-amendments/{local_amendment_id}/review", payload, headers
        )

    def resubmit_local_amendment(self, local_amendment_id, payload, headers):
        return self._request(
            "POST",
            f"/local-amendments/{local_amendment_id}/resubmit",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Interpretation requests
    # ------------------------------------------------------------------
    def create_interpretation_request(self, payload, headers):
        return self._request("POST", "/interpretation-requests", payload, headers)

    def list_interpretation_requests(self, headers, params=None):
        return self._request(
            "GET", "/interpretation-requests", headers=headers, params=params
        )

    def get_interpretation_request(self, request_id, headers):
        return self._request(
            "GET", f"/interpretation-requests/{request_id}", headers=headers
        )

    def act_on_interpretation_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/interpretation-requests/{request_id}/actions", payload, headers
        )

    def list_superseding_requests(self, request_id, headers, params=None):
        return self._request(
            "GET",
            f"/interpretation-requests/{request_id}/superseding-requests",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Training sessions and enrollments
    # ------------------------------------------------------------------
    def create_training_session(self, payload, headers):
        return self._request("POST", "/training-sessions", payload, headers)

    def list_training_sessions(self, headers, params=None):
        return self._request(
            "GET", "/training-sessions", headers=headers, params=params
        )

    def get_training_session(self, training_session_id, headers):
        return self._request(
            "GET", f"/training-sessions/{training_session_id}", headers=headers
        )

    def set_training_session_status(self, training_session_id, payload, headers):
        return self._request(
            "POST",
            f"/training-sessions/{training_session_id}/status",
            payload,
            headers,
        )

    def create_training_enrollment(self, training_session_id, payload, headers):
        return self._request(
            "POST",
            f"/training-sessions/{training_session_id}/enrollments",
            payload,
            headers,
        )

    def list_session_enrollments(self, training_session_id, headers, params=None):
        return self._request(
            "GET",
            f"/training-sessions/{training_session_id}/enrollments",
            headers=headers,
            params=params,
        )

    def record_attendance(self, training_session_id, payload, headers):
        return self._request(
            "POST",
            f"/training-sessions/{training_session_id}/attendance",
            payload,
            headers,
        )

    def list_training_enrollments(self, headers, params=None):
        return self._request(
            "GET", "/training-enrollments", headers=headers, params=params
        )

    def get_training_enrollment(self, enrollment_id, headers):
        return self._request(
            "GET", f"/training-enrollments/{enrollment_id}", headers=headers
        )

    def cancel_training_enrollment(self, enrollment_id, headers, payload=None):
        return self._request(
            "POST", f"/training-enrollments/{enrollment_id}/cancel", payload, headers
        )


api_client = ApiClient()
