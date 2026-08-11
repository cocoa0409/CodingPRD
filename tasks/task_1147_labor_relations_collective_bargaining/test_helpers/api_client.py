"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Union ---
    def create_union(self, payload, headers):
        return self._request("POST", "/labor-relations/unions", payload, headers)

    def list_unions(self, headers, params=None):
        return self._request("GET", "/labor-relations/unions", headers=headers, params=params)

    def get_union(self, union_id, headers):
        return self._request("GET", f"/labor-relations/unions/{union_id}", headers=headers)

    def transition_union(self, union_id, payload, headers):
        return self._request("POST", f"/labor-relations/unions/{union_id}/state", payload, headers)

    # --- CollectiveAgreement ---
    def create_agreement(self, payload, headers):
        return self._request("POST", "/labor-relations/agreements", payload, headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/labor-relations/agreements", headers=headers, params=params)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/labor-relations/agreements/{agreement_id}", headers=headers)

    def activate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/labor-relations/agreements/{agreement_id}/activate", {}, headers)

    def extend_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/labor-relations/agreements/{agreement_id}/extend", payload, headers)

    def archive_agreement(self, agreement_id, headers):
        return self._request("POST", f"/labor-relations/agreements/{agreement_id}/archive", {}, headers)

    # --- Clause ---
    def create_clause(self, payload, headers):
        return self._request("POST", "/labor-relations/clauses", payload, headers)

    def list_clauses(self, headers, params=None):
        return self._request("GET", "/labor-relations/clauses", headers=headers, params=params)

    def get_clause(self, clause_id, headers):
        return self._request("GET", f"/labor-relations/clauses/{clause_id}", headers=headers)

    def interpret_clause(self, clause_id, payload, headers):
        return self._request("POST", f"/labor-relations/clauses/{clause_id}/interpretation", payload, headers)

    # --- BargainingSession ---
    def create_session(self, payload, headers):
        return self._request("POST", "/labor-relations/sessions", payload, headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/labor-relations/sessions", headers=headers, params=params)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/labor-relations/sessions/{session_id}", headers=headers)

    def transition_session(self, session_id, payload, headers):
        return self._request("POST", f"/labor-relations/sessions/{session_id}/state", payload, headers)

    # --- Proposal ---
    def create_proposal(self, payload, headers):
        return self._request("POST", "/labor-relations/proposals", payload, headers)

    def list_proposals(self, headers, params=None):
        return self._request("GET", "/labor-relations/proposals", headers=headers, params=params)

    def get_proposal(self, proposal_id, headers):
        return self._request("GET", f"/labor-relations/proposals/{proposal_id}", headers=headers)

    def transition_proposal(self, proposal_id, payload, headers):
        return self._request("POST", f"/labor-relations/proposals/{proposal_id}/state", payload, headers)

    def counter_proposal(self, proposal_id, payload, headers):
        return self._request("POST", f"/labor-relations/proposals/{proposal_id}/counter", payload, headers)

    def void_implementation(self, proposal_id, headers):
        return self._request("POST", f"/labor-relations/proposals/{proposal_id}/void-implementation", {}, headers)

    # --- CostingScenario ---
    def create_costing_scenario(self, payload, headers):
        return self._request("POST", "/labor-relations/costing-scenarios", payload, headers)

    def list_costing_scenarios(self, headers, params=None):
        return self._request("GET", "/labor-relations/costing-scenarios", headers=headers, params=params)

    def get_costing_scenario(self, scenario_id, headers):
        return self._request("GET", f"/labor-relations/costing-scenarios/{scenario_id}", headers=headers)

    def transition_costing_scenario(self, scenario_id, payload, headers):
        return self._request("POST", f"/labor-relations/costing-scenarios/{scenario_id}/state", payload, headers)

    def lock_costing_scenario(self, scenario_id, payload, headers):
        return self._request("POST", f"/labor-relations/costing-scenarios/{scenario_id}/lock", payload, headers)

    # --- RatificationVote ---
    def create_ratification_vote(self, payload, headers):
        return self._request("POST", "/labor-relations/ratification-votes", payload, headers)

    def list_ratification_votes(self, headers, params=None):
        return self._request("GET", "/labor-relations/ratification-votes", headers=headers, params=params)

    def get_ratification_vote(self, vote_id, headers):
        return self._request("GET", f"/labor-relations/ratification-votes/{vote_id}", headers=headers)

    def transition_ratification_vote(self, vote_id, payload, headers):
        return self._request("POST", f"/labor-relations/ratification-votes/{vote_id}/state", payload, headers)

    def tally_vote(self, vote_id, payload, headers):
        return self._request("POST", f"/labor-relations/ratification-votes/{vote_id}/tally", payload, headers)

    # --- SideLetter ---
    def create_side_letter(self, payload, headers):
        return self._request("POST", "/labor-relations/side-letters", payload, headers)

    def list_side_letters(self, headers, params=None):
        return self._request("GET", "/labor-relations/side-letters", headers=headers, params=params)

    def get_side_letter(self, letter_id, headers):
        return self._request("GET", f"/labor-relations/side-letters/{letter_id}", headers=headers)

    def transition_side_letter(self, letter_id, payload, headers):
        return self._request("POST", f"/labor-relations/side-letters/{letter_id}/state", payload, headers)

    # --- PastPractice ---
    def create_past_practice(self, payload, headers):
        return self._request("POST", "/labor-relations/past-practices", payload, headers)

    def list_past_practices(self, headers, params=None):
        return self._request("GET", "/labor-relations/past-practices", headers=headers, params=params)

    def get_past_practice(self, practice_id, headers):
        return self._request("GET", f"/labor-relations/past-practices/{practice_id}", headers=headers)

    def transition_past_practice(self, practice_id, payload, headers):
        return self._request("POST", f"/labor-relations/past-practices/{practice_id}/state", payload, headers)

    # --- InformationRequest ---
    def create_information_request(self, payload, headers):
        return self._request("POST", "/labor-relations/information-requests", payload, headers)

    def list_information_requests(self, headers, params=None):
        return self._request("GET", "/labor-relations/information-requests", headers=headers, params=params)

    def get_information_request(self, request_id, headers):
        return self._request("GET", f"/labor-relations/information-requests/{request_id}", headers=headers)

    def transition_information_request(self, request_id, payload, headers):
        return self._request("POST", f"/labor-relations/information-requests/{request_id}/state", payload, headers)

    def extend_information_request(self, request_id, payload, headers):
        return self._request("POST", f"/labor-relations/information-requests/{request_id}/extend", payload, headers)

    # --- ExpirationTask ---
    def create_expiration_task(self, payload, headers):
        return self._request("POST", "/labor-relations/expiration-tasks", payload, headers)

    def list_expiration_tasks(self, headers, params=None):
        return self._request("GET", "/labor-relations/expiration-tasks", headers=headers, params=params)

    def get_expiration_task(self, task_id, headers):
        return self._request("GET", f"/labor-relations/expiration-tasks/{task_id}", headers=headers)

    def transition_expiration_task(self, task_id, payload, headers):
        return self._request("POST", f"/labor-relations/expiration-tasks/{task_id}/state", payload, headers)

    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
