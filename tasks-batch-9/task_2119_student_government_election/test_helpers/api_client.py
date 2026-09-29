"""API client: one method per endpoint defined in the PRD (§4).

Every collection is mounted at the root of the URL space and relationships are
carried by identifier fields in request payloads rather than by nested URLs.
"""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Elections ────────────────────────────────────────────────────────────

    def create_election(self, payload, headers):
        return self._request("POST", "/elections", payload, headers)

    def list_elections(self, headers, params=None):
        return self._request("GET", "/elections", headers=headers, params=params)

    def get_election(self, election_id, headers):
        return self._request("GET", f"/elections/{election_id}", headers=headers)

    def open_petitioning(self, election_id, headers, payload=None):
        return self._request(
            "POST", f"/elections/{election_id}/open-petitioning", payload or {}, headers
        )

    def open_voting(self, election_id, payload, headers):
        return self._request(
            "POST", f"/elections/{election_id}/open-voting", payload, headers
        )

    def close_voting(self, election_id, headers, payload=None):
        return self._request(
            "POST", f"/elections/{election_id}/close-voting", payload or {}, headers
        )

    def tally(self, election_id, headers, payload=None):
        return self._request(
            "POST", f"/elections/{election_id}/tally", payload or {}, headers
        )

    def certify(self, election_id, headers, payload=None):
        return self._request(
            "POST", f"/elections/{election_id}/certify", payload or {}, headers
        )

    def run_transition_checkpoint(self, election_id, headers, payload=None):
        return self._request(
            "POST",
            f"/elections/{election_id}/run-transition-checkpoint",
            payload or {},
            headers,
        )

    # ─── Offices ──────────────────────────────────────────────────────────────

    def create_office(self, payload, headers):
        return self._request("POST", "/offices", payload, headers)

    def list_offices(self, headers, params=None):
        return self._request("GET", "/offices", headers=headers, params=params)

    def get_office(self, office_id, headers):
        return self._request("GET", f"/offices/{office_id}", headers=headers)

    # ─── Students ─────────────────────────────────────────────────────────────

    def create_student(self, payload, headers):
        return self._request("POST", "/students", payload, headers)

    def list_students(self, headers, params=None):
        return self._request("GET", "/students", headers=headers, params=params)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/students/{student_id}", headers=headers)

    def update_student(self, student_id, payload, headers):
        return self._request("PATCH", f"/students/{student_id}", payload, headers)

    # ─── Candidacies ──────────────────────────────────────────────────────────

    def create_candidacy(self, payload, headers):
        return self._request("POST", "/candidacies", payload, headers)

    def list_candidacies(self, headers, params=None):
        return self._request("GET", "/candidacies", headers=headers, params=params)

    def get_candidacy(self, candidacy_id, headers):
        return self._request("GET", f"/candidacies/{candidacy_id}", headers=headers)

    def submit_petition(self, candidacy_id, headers, payload=None):
        return self._request(
            "POST", f"/candidacies/{candidacy_id}/submit-petition", payload or {}, headers
        )

    def return_petition(self, candidacy_id, payload, headers):
        return self._request(
            "POST", f"/candidacies/{candidacy_id}/return", payload, headers
        )

    def approve_candidacy(self, candidacy_id, headers, payload=None):
        return self._request(
            "POST", f"/candidacies/{candidacy_id}/approve", payload or {}, headers
        )

    def withdraw_candidacy(self, candidacy_id, headers, payload=None):
        return self._request(
            "POST", f"/candidacies/{candidacy_id}/withdraw", payload or {}, headers
        )

    def change_slate_membership(self, candidacy_id, payload, headers):
        return self._request(
            "POST", f"/candidacies/{candidacy_id}/slate-membership", payload, headers
        )

    def record_training(self, candidacy_id, payload, headers):
        return self._request(
            "POST", f"/candidacies/{candidacy_id}/record-training", payload, headers
        )

    def activate_officer(self, candidacy_id, headers, payload=None):
        return self._request(
            "POST", f"/candidacies/{candidacy_id}/activate-officer", payload or {}, headers
        )

    # ─── Petition signatures ──────────────────────────────────────────────────

    def create_petition_signature(self, payload, headers):
        return self._request("POST", "/petition-signatures", payload, headers)

    def list_petition_signatures(self, headers, params=None):
        return self._request(
            "GET", "/petition-signatures", headers=headers, params=params
        )

    def get_petition_signature(self, petition_signature_id, headers):
        return self._request(
            "GET", f"/petition-signatures/{petition_signature_id}", headers=headers
        )

    def adjudicate_signature(self, petition_signature_id, payload, headers):
        return self._request(
            "POST",
            f"/petition-signatures/{petition_signature_id}/adjudicate",
            payload,
            headers,
        )

    def void_signature(self, petition_signature_id, headers, payload=None):
        return self._request(
            "POST",
            f"/petition-signatures/{petition_signature_id}/void",
            payload or {},
            headers,
        )

    # ─── Campaign expenses ────────────────────────────────────────────────────

    def create_campaign_expense(self, payload, headers):
        return self._request("POST", "/campaign-expenses", payload, headers)

    def list_campaign_expenses(self, headers, params=None):
        return self._request(
            "GET", "/campaign-expenses", headers=headers, params=params
        )

    def get_campaign_expense(self, campaign_expense_id, headers):
        return self._request(
            "GET", f"/campaign-expenses/{campaign_expense_id}", headers=headers
        )

    def approve_expense(self, campaign_expense_id, headers, payload=None):
        return self._request(
            "POST",
            f"/campaign-expenses/{campaign_expense_id}/approve",
            payload or {},
            headers,
        )

    def reverse_expense(self, campaign_expense_id, headers, payload=None):
        return self._request(
            "POST",
            f"/campaign-expenses/{campaign_expense_id}/reverse",
            payload or {},
            headers,
        )

    # ─── Compliance cases ─────────────────────────────────────────────────────

    def create_compliance_case(self, payload, headers):
        return self._request("POST", "/compliance-cases", payload, headers)

    def list_compliance_cases(self, headers, params=None):
        return self._request("GET", "/compliance-cases", headers=headers, params=params)

    def get_compliance_case(self, compliance_case_id, headers):
        return self._request(
            "GET", f"/compliance-cases/{compliance_case_id}", headers=headers
        )

    def uphold_case(self, compliance_case_id, headers, payload=None):
        return self._request(
            "POST",
            f"/compliance-cases/{compliance_case_id}/uphold",
            payload or {},
            headers,
        )

    def dismiss_case(self, compliance_case_id, headers, payload=None):
        return self._request(
            "POST",
            f"/compliance-cases/{compliance_case_id}/dismiss",
            payload or {},
            headers,
        )

    # ─── Referenda ────────────────────────────────────────────────────────────

    def create_referendum(self, payload, headers):
        return self._request("POST", "/referenda", payload, headers)

    def list_referenda(self, headers, params=None):
        return self._request("GET", "/referenda", headers=headers, params=params)

    def get_referendum(self, referendum_id, headers):
        return self._request("GET", f"/referenda/{referendum_id}", headers=headers)

    def submit_referendum(self, referendum_id, headers, payload=None):
        return self._request(
            "POST", f"/referenda/{referendum_id}/submit", payload or {}, headers
        )

    def review_referendum(self, referendum_id, payload, headers):
        return self._request(
            "POST", f"/referenda/{referendum_id}/review", payload, headers
        )

    # ─── Ballots and ballot lines ─────────────────────────────────────────────

    def create_ballot(self, payload, headers):
        return self._request("POST", "/ballots", payload, headers)

    def list_ballots(self, headers, params=None):
        return self._request("GET", "/ballots", headers=headers, params=params)

    def get_ballot(self, ballot_id, headers):
        return self._request("GET", f"/ballots/{ballot_id}", headers=headers)

    def create_ballot_line(self, ballot_id, payload, headers):
        return self._request("POST", f"/ballots/{ballot_id}/lines", payload, headers)

    def list_ballot_lines(self, headers, params=None):
        return self._request("GET", "/ballot-lines", headers=headers, params=params)

    def get_ballot_line(self, ballot_line_id, headers):
        return self._request("GET", f"/ballot-lines/{ballot_line_id}", headers=headers)

    def lock_ballot(self, ballot_id, headers, payload=None):
        return self._request("POST", f"/ballots/{ballot_id}/lock", payload or {}, headers)

    def publish_ballot(self, ballot_id, headers, payload=None):
        return self._request(
            "POST", f"/ballots/{ballot_id}/publish", payload or {}, headers
        )

    # ─── Votes ────────────────────────────────────────────────────────────────

    def create_vote(self, payload, headers):
        return self._request("POST", "/votes", payload, headers)

    def list_votes(self, headers, params=None):
        return self._request("GET", "/votes", headers=headers, params=params)

    def get_vote(self, vote_id, headers):
        return self._request("GET", f"/votes/{vote_id}", headers=headers)

    def void_vote(self, vote_id, payload, headers):
        return self._request("POST", f"/votes/{vote_id}/void", payload, headers)

    # ─── Appeals ──────────────────────────────────────────────────────────────

    def create_appeal(self, payload, headers):
        return self._request("POST", "/appeals", payload, headers)

    def list_appeals(self, headers, params=None):
        return self._request("GET", "/appeals", headers=headers, params=params)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/appeals/{appeal_id}", headers=headers)

    def sustain_appeal(self, appeal_id, headers, payload=None):
        return self._request(
            "POST", f"/appeals/{appeal_id}/sustain", payload or {}, headers
        )

    def deny_appeal(self, appeal_id, headers, payload=None):
        return self._request(
            "POST", f"/appeals/{appeal_id}/deny", payload or {}, headers
        )

    # ─── Logical clock ────────────────────────────────────────────────────────

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
