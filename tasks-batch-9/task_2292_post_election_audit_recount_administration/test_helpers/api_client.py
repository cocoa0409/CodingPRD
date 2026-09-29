"""API client: one method per endpoint declared by the PRD."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Every method returns the raw response so tests can assert status codes."""

    # -- logical clock -----------------------------------------------------
    def set_clock(self, current_utc: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # -- Election ----------------------------------------------------------
    def create_election(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/elections", payload, headers)

    def list_elections(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/elections", headers=headers, params=params)

    def get_election(self, election_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/elections/{election_id}", headers=headers)

    def patch_election(
        self, election_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("PATCH", f"/elections/{election_id}", payload, headers)

    def certify_election(self, election_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/elections/{election_id}/certify", {}, headers)

    # -- Contest -----------------------------------------------------------
    def create_contest(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/contests", payload, headers)

    def list_contests(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/contests", headers=headers, params=params)

    def get_contest(self, contest_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/contests/{contest_id}", headers=headers)

    def submit_canvass_results(
        self, contest_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/contests/{contest_id}/canvass-results", payload, headers
        )

    # -- BallotBatch -------------------------------------------------------
    def create_ballot_batch(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/ballot-batches", payload, headers)

    def bulk_create_ballot_batches(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/ballot-batches/bulk", payload, headers)

    def list_ballot_batches(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/ballot-batches", headers=headers, params=params)

    def get_ballot_batch(self, ballot_batch_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/ballot-batches/{ballot_batch_id}", headers=headers
        )

    def quarantine_ballot_batch(
        self, ballot_batch_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/ballot-batches/{ballot_batch_id}/quarantine", payload, headers
        )

    def list_ballot_batch_custody_events(
        self,
        ballot_batch_id: str,
        headers: Dict[str, str],
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET",
            f"/ballot-batches/{ballot_batch_id}/custody-events",
            headers=headers,
            params=params,
        )

    # -- CustodyEvent ------------------------------------------------------
    def list_custody_events(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/custody-events", headers=headers, params=params)

    def get_custody_event(self, custody_event_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/custody-events/{custody_event_id}", headers=headers
        )

    # -- Audit -------------------------------------------------------------
    def create_audit(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/audits", payload, headers)

    def list_audits(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/audits", headers=headers, params=params)

    def get_audit(self, audit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/audits/{audit_id}", headers=headers)

    def seed_audit(
        self, audit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/audits/{audit_id}/seed", payload, headers)

    def create_audit_round(
        self, audit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/audits/{audit_id}/rounds", payload, headers)

    def close_audit(self, audit_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/audits/{audit_id}/close", {}, headers)

    def terminate_audit(
        self, audit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/audits/{audit_id}/terminate", payload, headers)

    def review_audit_timeline(self, audit_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/audits/{audit_id}/timeline-review", {}, headers
        )

    def get_audit_public_report(self, audit_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/audits/{audit_id}/public-report", headers=headers
        )

    # -- AuditRound --------------------------------------------------------
    def list_audit_rounds(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/audit-rounds", headers=headers, params=params)

    def get_audit_round(self, audit_round_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/audit-rounds/{audit_round_id}", headers=headers)

    # -- AuditBatch --------------------------------------------------------
    def list_audit_batches(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/audit-batches", headers=headers, params=params)

    def get_audit_batch(self, audit_batch_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/audit-batches/{audit_batch_id}", headers=headers)

    def retrieve_audit_batch(
        self, audit_batch_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/audit-batches/{audit_batch_id}/retrieve", payload, headers
        )

    def return_audit_batch(
        self, audit_batch_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/audit-batches/{audit_batch_id}/return", payload, headers
        )

    # -- TallyTeam ---------------------------------------------------------
    def create_tally_team(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/tally-teams", payload, headers)

    def list_tally_teams(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/tally-teams", headers=headers, params=params)

    def get_tally_team(self, tally_team_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/tally-teams/{tally_team_id}", headers=headers)

    def set_tally_team_members(
        self, tally_team_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/tally-teams/{tally_team_id}/members", payload, headers
        )

    def disband_tally_team(self, tally_team_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/tally-teams/{tally_team_id}/disband", {}, headers
        )

    # -- ManualTally -------------------------------------------------------
    def create_manual_tally(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/manual-tallies", payload, headers)

    def list_manual_tallies(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/manual-tallies", headers=headers, params=params)

    def get_manual_tally(self, manual_tally_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/manual-tallies/{manual_tally_id}", headers=headers
        )

    def patch_manual_tally(
        self, manual_tally_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH", f"/manual-tallies/{manual_tally_id}", payload, headers
        )

    def submit_manual_tally(self, manual_tally_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/manual-tallies/{manual_tally_id}/submit", {}, headers
        )

    def reopen_manual_tally(
        self, manual_tally_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/manual-tallies/{manual_tally_id}/reopen", payload, headers
        )

    # -- Discrepancy -------------------------------------------------------
    def list_discrepancies(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/discrepancies", headers=headers, params=params)

    def get_discrepancy(self, discrepancy_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/discrepancies/{discrepancy_id}", headers=headers)

    def document_discrepancy(
        self, discrepancy_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/discrepancies/{discrepancy_id}/document", payload, headers
        )

    def escalate_discrepancy(
        self, discrepancy_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/discrepancies/{discrepancy_id}/escalate", payload, headers
        )

    def resolve_discrepancy(
        self, discrepancy_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/discrepancies/{discrepancy_id}/resolve", payload, headers
        )

    def list_discrepancy_corrective_actions(
        self, discrepancy_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/discrepancies/{discrepancy_id}/corrective-actions",
            headers=headers,
            params=params,
        )

    # -- CorrectiveAction --------------------------------------------------
    def create_corrective_action(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/corrective-actions", payload, headers)

    def list_corrective_actions(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/corrective-actions", headers=headers, params=params
        )

    def get_corrective_action(
        self, corrective_action_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "GET", f"/corrective-actions/{corrective_action_id}", headers=headers
        )

    def transition_corrective_action(
        self, corrective_action_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/corrective-actions/{corrective_action_id}/transition",
            payload,
            headers,
        )

    # -- BallotInterpretation ---------------------------------------------
    def create_ballot_interpretation(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/ballot-interpretations", payload, headers)

    def list_ballot_interpretations(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/ballot-interpretations", headers=headers, params=params
        )

    def get_ballot_interpretation(
        self, ballot_interpretation_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "GET", f"/ballot-interpretations/{ballot_interpretation_id}", headers=headers
        )

    def cast_ballot_interpretation_vote(
        self,
        ballot_interpretation_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/ballot-interpretations/{ballot_interpretation_id}/votes",
            payload,
            headers,
        )

    # -- Recount -----------------------------------------------------------
    def create_recount(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/recounts", payload, headers)

    def list_recounts(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/recounts", headers=headers, params=params)

    def get_recount(self, recount_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/recounts/{recount_id}", headers=headers)

    def post_recount_deposit(
        self, recount_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/recounts/{recount_id}/deposit", payload, headers
        )

    def start_recount(self, recount_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/recounts/{recount_id}/start", {}, headers)

    def complete_recount(
        self, recount_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/recounts/{recount_id}/complete", payload, headers
        )

    def withdraw_recount(
        self, recount_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/recounts/{recount_id}/withdraw", payload, headers
        )

    def deny_recount(
        self, recount_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/recounts/{recount_id}/deny", payload, headers)

    # -- ObserverCredential ------------------------------------------------
    def create_observer_credential(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/observer-credentials", payload, headers)

    def list_observer_credentials(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/observer-credentials", headers=headers, params=params
        )

    def get_observer_credential(
        self, observer_credential_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "GET", f"/observer-credentials/{observer_credential_id}", headers=headers
        )

    def revoke_observer_credential(
        self,
        observer_credential_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/observer-credentials/{observer_credential_id}/revoke",
            payload,
            headers,
        )


api_client = ApiClient()
