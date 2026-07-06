"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- BudgetCycle ----
    def create_budget_cycle(self, payload, headers):
        return self._request("POST", "/budget-cycles", payload, headers)

    def get_budget_cycle(self, cycle_id, headers):
        return self._request("GET", f"/budget-cycles/{cycle_id}", headers=headers)

    def transition_phase(self, cycle_id, payload, headers):
        return self._request("POST", f"/budget-cycles/{cycle_id}/phase-transitions", payload, headers)

    def create_category(self, cycle_id, payload, headers):
        return self._request("POST", f"/budget-cycles/{cycle_id}/categories", payload, headers)

    def list_categories(self, cycle_id, headers, params=None):
        return self._request("GET", f"/budget-cycles/{cycle_id}/categories", headers=headers, params=params)

    def list_cycle_proposals(self, cycle_id, headers, params=None):
        return self._request("GET", f"/budget-cycles/{cycle_id}/proposals", headers=headers, params=params)

    def list_selection_runs(self, cycle_id, headers, params=None):
        return self._request("GET", f"/budget-cycles/{cycle_id}/selection-runs", headers=headers, params=params)

    def create_selection_run(self, cycle_id, payload, headers):
        return self._request("POST", f"/budget-cycles/{cycle_id}/selection-runs", payload, headers)

    # ---- Resident ----
    def create_resident(self, payload, headers):
        return self._request("POST", "/residents", payload, headers)

    def get_resident(self, resident_id, headers):
        return self._request("GET", f"/residents/{resident_id}", headers=headers)

    def request_verification(self, resident_id, payload, headers):
        return self._request("POST", f"/residents/{resident_id}/verification-requests", payload, headers)

    def decide_verification(self, resident_id, payload, headers):
        return self._request("POST", f"/residents/{resident_id}/verification-decisions", payload, headers)

    # ---- Proposal ----
    def create_proposal(self, cycle_id, payload, headers):
        return self._request("POST", f"/budget-cycles/{cycle_id}/proposals", payload, headers)

    def get_proposal(self, proposal_id, headers):
        return self._request("GET", f"/proposals/{proposal_id}", headers=headers)

    def list_proposals(self, headers, params=None):
        return self._request("GET", "/proposals", headers=headers, params=params)

    def submit_proposal(self, proposal_id, headers):
        return self._request("POST", f"/proposals/{proposal_id}/submit", {}, headers)

    def review_proposal(self, proposal_id, payload, headers):
        return self._request("POST", f"/proposals/{proposal_id}/review-decisions", payload, headers)

    def add_cost_line_item(self, proposal_id, payload, headers):
        return self._request("POST", f"/proposals/{proposal_id}/cost-line-items", payload, headers)

    def list_cost_line_items(self, proposal_id, headers, params=None):
        return self._request("GET", f"/proposals/{proposal_id}/cost-line-items", headers=headers, params=params)

    def finalize_cost(self, proposal_id, headers):
        return self._request("POST", f"/proposals/{proposal_id}/finalize-cost", {}, headers)

    def release_funding(self, proposal_id, headers):
        return self._request("POST", f"/proposals/{proposal_id}/release-funding", {}, headers)

    def cancel_funding(self, proposal_id, headers):
        return self._request("POST", f"/proposals/{proposal_id}/cancel-funding", {}, headers)

    def list_proposal_ballot_entries(self, proposal_id, headers, params=None):
        return self._request("GET", f"/proposals/{proposal_id}/ballot-entries", headers=headers, params=params)

    def list_proposal_milestones(self, proposal_id, headers, params=None):
        return self._request("GET", f"/proposals/{proposal_id}/milestones", headers=headers, params=params)

    def list_report_backs(self, proposal_id, headers, params=None):
        return self._request("GET", f"/proposals/{proposal_id}/report-backs", headers=headers, params=params)

    # ---- Ballot ----
    def create_ballot(self, cycle_id, headers):
        return self._request("POST", f"/budget-cycles/{cycle_id}/ballots", {}, headers)

    def get_ballot(self, ballot_id, headers):
        return self._request("GET", f"/ballots/{ballot_id}", headers=headers)

    def list_ballots(self, headers, params=None):
        return self._request("GET", "/ballots", headers=headers, params=params)

    def add_ballot_entry(self, ballot_id, payload, headers):
        return self._request("POST", f"/ballots/{ballot_id}/entries", payload, headers)

    def cast_ballot(self, ballot_id, headers):
        return self._request("POST", f"/ballots/{ballot_id}/cast", {}, headers)

    def withdraw_ballot(self, ballot_id, headers):
        return self._request("POST", f"/ballots/{ballot_id}/withdraw", {}, headers)

    def list_ballot_entries(self, ballot_id, headers, params=None):
        return self._request("GET", f"/ballots/{ballot_id}/entries", headers=headers, params=params)

    # ---- Milestone & ReportBack ----
    def create_milestone(self, proposal_id, payload, headers):
        return self._request("POST", f"/proposals/{proposal_id}/milestones", payload, headers)

    def transition_milestone(self, milestone_id, payload, headers):
        return self._request("POST", f"/milestones/{milestone_id}/transitions", payload, headers)

    def create_report_back(self, proposal_id, payload, headers):
        return self._request("POST", f"/proposals/{proposal_id}/report-backs", payload, headers)

    # ---- Test-driving: logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
