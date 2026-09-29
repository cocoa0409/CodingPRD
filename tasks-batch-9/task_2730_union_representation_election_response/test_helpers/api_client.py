"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/labor-relations"


class ApiClient(GenericApiClient):
    # ---------------------------------------------------------------- clock
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------ petitions
    def create_petition(self, payload, headers):
        return self._request("POST", f"{PREFIX}/petitions", payload, headers)

    def list_petitions(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/petitions", headers=headers, params=params)

    def get_petition(self, petition_id, headers):
        return self._request("GET", f"{PREFIX}/petitions/{petition_id}", headers=headers)

    def open_scope_analysis(self, petition_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/petitions/{petition_id}/open-scope-analysis",
            payload if payload is not None else {}, headers,
        )

    def verify_showing(self, petition_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/petitions/{petition_id}/verify-showing", payload, headers
        )

    def schedule_rerun(self, petition_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/petitions/{petition_id}/schedule-rerun", payload, headers
        )

    def certify_petition(self, petition_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/petitions/{petition_id}/certify", payload, headers
        )

    # ------------------------------------------------------- classifications
    def create_classification(self, payload, headers):
        return self._request("POST", f"{PREFIX}/classifications", payload, headers)

    def list_classifications(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/classifications", headers=headers, params=params)

    def get_classification(self, classification_id, headers):
        return self._request(
            "GET", f"{PREFIX}/classifications/{classification_id}", headers=headers
        )

    def score_classification(self, classification_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/classifications/{classification_id}/score", payload, headers
        )

    def rule_classification(self, classification_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/classifications/{classification_id}/rule", payload, headers
        )

    def reconsider_classification(self, classification_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/classifications/{classification_id}/reconsider",
            payload if payload is not None else {}, headers,
        )

    # --------------------------------------------------- election agreements
    def create_election_agreement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/election-agreements", payload, headers)

    def list_election_agreements(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/election-agreements", headers=headers, params=params
        )

    def get_election_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"{PREFIX}/election-agreements/{agreement_id}", headers=headers
        )

    def stipulate_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/election-agreements/{agreement_id}/stipulate", payload, headers
        )

    def request_hearing(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/election-agreements/{agreement_id}/request-hearing",
            payload, headers,
        )

    def direct_election(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/election-agreements/{agreement_id}/direct-election",
            payload, headers,
        )

    # ----------------------------------------------------------- voter lists
    def create_voter_list(self, payload, headers):
        return self._request("POST", f"{PREFIX}/voter-lists", payload, headers)

    def list_voter_lists(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/voter-lists", headers=headers, params=params)

    def get_voter_list(self, voter_list_id, headers):
        return self._request("GET", f"{PREFIX}/voter-lists/{voter_list_id}", headers=headers)

    def submit_voter_list(self, voter_list_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/voter-lists/{voter_list_id}/submit", payload, headers
        )

    def resubmit_voter_list(self, voter_list_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/voter-lists/{voter_list_id}/resubmit", payload, headers
        )

    def review_voter_list(self, voter_list_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/voter-lists/{voter_list_id}/review", payload, headers
        )

    # --------------------------------------------------- voter list entries
    def create_voter_list_entry(self, payload, headers):
        return self._request("POST", f"{PREFIX}/voter-list-entries", payload, headers)

    def list_voter_list_entries(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/voter-list-entries", headers=headers, params=params
        )

    def get_voter_list_entry(self, entry_id, headers):
        return self._request(
            "GET", f"{PREFIX}/voter-list-entries/{entry_id}", headers=headers
        )

    def update_voter_list_entry(self, entry_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/voter-list-entries/{entry_id}", payload, headers
        )

    # ----------------------------------------------------------- supervisors
    def create_supervisor(self, payload, headers):
        return self._request("POST", f"{PREFIX}/supervisors", payload, headers)

    def list_supervisors(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/supervisors", headers=headers, params=params)

    def get_supervisor(self, supervisor_id, headers):
        return self._request("GET", f"{PREFIX}/supervisors/{supervisor_id}", headers=headers)

    def train_supervisor(self, supervisor_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/supervisors/{supervisor_id}/train", payload, headers
        )

    def record_violation(self, supervisor_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/supervisors/{supervisor_id}/record-violation", payload, headers
        )

    # ----------------------------------------------- campaign communications
    def create_campaign_communication(self, payload, headers):
        return self._request("POST", f"{PREFIX}/campaign-communications", payload, headers)

    def list_campaign_communications(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/campaign-communications", headers=headers, params=params
        )

    def get_campaign_communication(self, communication_id, headers):
        return self._request(
            "GET", f"{PREFIX}/campaign-communications/{communication_id}", headers=headers
        )

    def accuracy_review_communication(self, communication_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/campaign-communications/{communication_id}/accuracy-review",
            payload, headers,
        )

    def submit_communication_for_review(self, communication_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/campaign-communications/{communication_id}/submit-for-review",
            payload if payload is not None else {}, headers,
        )

    def review_communication(self, communication_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/campaign-communications/{communication_id}/review",
            payload, headers,
        )

    def deliver_communication(self, communication_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/campaign-communications/{communication_id}/deliver",
            payload if payload is not None else {}, headers,
        )

    # -------------------------------------------------------- election rounds
    def list_election_rounds(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/election-rounds", headers=headers, params=params)

    def get_election_round(self, round_id, headers):
        return self._request("GET", f"{PREFIX}/election-rounds/{round_id}", headers=headers)

    def open_polls(self, round_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/election-rounds/{round_id}/open-polls",
            payload if payload is not None else {}, headers,
        )

    def post_tally(self, round_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/election-rounds/{round_id}/post-tally",
            payload if payload is not None else {}, headers,
        )

    def revise_tally(self, round_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/election-rounds/{round_id}/revise-tally",
            payload if payload is not None else {}, headers,
        )

    # ---------------------------------------------------------- poll sessions
    def create_poll_session(self, payload, headers):
        return self._request("POST", f"{PREFIX}/poll-sessions", payload, headers)

    def list_poll_sessions(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/poll-sessions", headers=headers, params=params)

    def get_poll_session(self, session_id, headers):
        return self._request("GET", f"{PREFIX}/poll-sessions/{session_id}", headers=headers)

    def designate_observer(self, session_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/poll-sessions/{session_id}/designate-observer", payload, headers
        )

    def close_poll_session(self, session_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/poll-sessions/{session_id}/close", payload, headers
        )

    # ------------------------------------------------------ challenged ballots
    def create_challenged_ballot(self, payload, headers):
        return self._request("POST", f"{PREFIX}/challenged-ballots", payload, headers)

    def list_challenged_ballots(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/challenged-ballots", headers=headers, params=params
        )

    def get_challenged_ballot(self, ballot_id, headers):
        return self._request(
            "GET", f"{PREFIX}/challenged-ballots/{ballot_id}", headers=headers
        )

    def resolve_challenged_ballot(self, ballot_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/challenged-ballots/{ballot_id}/resolve", payload, headers
        )

    def reopen_challenged_ballot(self, ballot_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/challenged-ballots/{ballot_id}/reopen",
            payload if payload is not None else {}, headers,
        )

    # ------------------------------------------------------------- objections
    def create_objection(self, payload, headers):
        return self._request("POST", f"{PREFIX}/objections", payload, headers)

    def list_objections(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/objections", headers=headers, params=params)

    def get_objection(self, objection_id, headers):
        return self._request("GET", f"{PREFIX}/objections/{objection_id}", headers=headers)

    def rule_objection(self, objection_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/objections/{objection_id}/rule", payload, headers
        )

    # ------------------------------------------------------------ ULP charges
    def create_ulp_charge(self, payload, headers):
        return self._request("POST", f"{PREFIX}/ulp-charges", payload, headers)

    def list_ulp_charges(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/ulp-charges", headers=headers, params=params)

    def get_ulp_charge(self, charge_id, headers):
        return self._request("GET", f"{PREFIX}/ulp-charges/{charge_id}", headers=headers)

    def determine_ulp_charge(self, charge_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/ulp-charges/{charge_id}/determine", payload, headers
        )

    def settle_ulp_charge(self, charge_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/ulp-charges/{charge_id}/settle", payload, headers
        )

    # -------------------------------------------------------------- raw paths
    def raw_post(self, path, payload, headers):
        """POST an arbitrary path, for header-authentication probes."""
        return self._request("POST", path, payload, headers)

    def raw_get(self, path, headers, params=None):
        """GET an arbitrary path, for header-authentication probes."""
        return self._request("GET", path, headers=headers, params=params)


api_client = ApiClient()
