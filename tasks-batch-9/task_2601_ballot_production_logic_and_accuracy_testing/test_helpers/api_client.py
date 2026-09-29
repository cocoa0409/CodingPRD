"""Typed client with one method per endpoint of the PRD section 4 table.

Every method returns the raw ``requests.Response`` so tests can assert on the
status code as well as on the envelope. Query-parameter endpoints take their
parameters through ``params``; the client never invents a field name that the
PRD does not define.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class BallotProductionApiClient(GenericApiClient):
    """One method per endpoint of the ballot production service."""

    # ─── Logical clock ───────────────────────────────────────────────────────

    def set_clock(self, now: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", {"now": now}, headers)

    # ─── Elections ───────────────────────────────────────────────────────────

    def create_election(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/elections", payload, headers)

    def get_election(self, election_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/elections/{election_id}", None, headers)

    def certify_ballot_order(self, election_id: str, headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("POST", f"/elections/{election_id}/certify-ballot-order",
                             payload if payload is not None else {}, headers)

    def lock_styles(self, election_id: str, headers: Dict[str, str],
                    payload: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("POST", f"/elections/{election_id}/lock-styles",
                             payload if payload is not None else {}, headers)

    def deploy_election(self, election_id: str, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("POST", f"/elections/{election_id}/deploy",
                             payload if payload is not None else {}, headers)

    def close_polls(self, election_id: str, headers: Dict[str, str],
                    payload: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("POST", f"/elections/{election_id}/close-polls",
                             payload if payload is not None else {}, headers)

    def reconcile(self, election_id: str, payload: Dict[str, Any],
                  headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/elections/{election_id}/reconcile", payload, headers)

    def get_accountability(self, election_id: str, headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("GET", f"/elections/{election_id}/accountability", params, headers)

    def list_contests(self, election_id: str, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("GET", f"/elections/{election_id}/contests", params, headers)

    def list_custody_events(self, election_id: str, headers: Dict[str, str],
                            params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("GET", f"/elections/{election_id}/custody-events", params, headers)

    # ─── Contests and candidates ─────────────────────────────────────────────

    def create_contest(self, election_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/elections/{election_id}/contests", payload, headers)

    def get_contest(self, contest_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/contests/{contest_id}", None, headers)

    def list_candidates(self, contest_id: str, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("GET", f"/contests/{contest_id}/candidates", params, headers)

    def create_candidate(self, contest_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/contests/{contest_id}/candidates", payload, headers)

    def certify_contest(self, contest_id: str, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("POST", f"/contests/{contest_id}/certify",
                             payload if payload is not None else {}, headers)

    def withdraw_contest(self, contest_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/contests/{contest_id}/withdraw", payload, headers)

    def disqualify_candidate(self, candidate_id: str, payload: Dict[str, Any],
                             headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/candidates/{candidate_id}/disqualify", payload, headers)

    # ─── Precincts ───────────────────────────────────────────────────────────

    def create_precinct(self, election_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/elections/{election_id}/precincts", payload, headers)

    def get_precinct(self, precinct_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/precincts/{precinct_id}", None, headers)

    def list_precincts(self, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("GET", "/precincts", params, headers)

    def assign_style(self, precinct_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/precincts/{precinct_id}/assign-style", payload, headers)

    # ─── Ballot styles ───────────────────────────────────────────────────────

    def create_ballot_style(self, election_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/elections/{election_id}/ballot-styles", payload, headers)

    def get_ballot_style(self, style_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/ballot-styles/{style_id}", None, headers)

    def list_ballot_styles(self, headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("GET", "/ballot-styles", params, headers)

    def get_layout(self, style_id: str, headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("GET", f"/ballot-styles/{style_id}/layout", params, headers)

    def create_language_certifications(self, style_id: str, payload: Dict[str, Any],
                                       headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/ballot-styles/{style_id}/language-certifications",
                             payload, headers)

    def request_proof(self, style_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("POST", f"/ballot-styles/{style_id}/request-proof",
                             payload if payload is not None else {}, headers)

    def proof_decision(self, style_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/ballot-styles/{style_id}/proof-decision", payload, headers)

    def list_test_decks(self, style_id: str, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("GET", f"/ballot-styles/{style_id}/test-decks", params, headers)

    def create_test_deck(self, style_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/ballot-styles/{style_id}/test-decks", payload, headers)

    # ─── Print vendors and print jobs ────────────────────────────────────────

    def create_print_vendor(self, payload: Dict[str, Any],
                            headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/print-vendors", payload, headers)

    def get_print_vendor(self, vendor_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/print-vendors/{vendor_id}", None, headers)

    def create_print_job(self, payload: Dict[str, Any],
                         headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/print-jobs", payload, headers)

    def get_print_job(self, job_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/print-jobs/{job_id}", None, headers)

    def list_print_jobs(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("GET", "/print-jobs", params, headers)

    def approve_press_proof(self, job_id: str, headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("POST", f"/print-jobs/{job_id}/approve-proof",
                             payload if payload is not None else {}, headers)

    def inspect_print_job(self, job_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/print-jobs/{job_id}/inspect", payload, headers)

    def deliver_print_job(self, job_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/print-jobs/{job_id}/deliver", payload, headers)

    # ─── Ballot lots ─────────────────────────────────────────────────────────

    def get_ballot_lot(self, lot_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/ballot-lots/{lot_id}", None, headers)

    def list_ballot_lots(self, headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("GET", "/ballot-lots", params, headers)

    def receive_lot(self, lot_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/ballot-lots/{lot_id}/receive", payload, headers)

    def issue_lot(self, lot_id: str, payload: Dict[str, Any],
                  headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/ballot-lots/{lot_id}/issue", payload, headers)

    def recall_lot(self, lot_id: str, headers: Dict[str, str],
                   payload: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("POST", f"/ballot-lots/{lot_id}/recall",
                             payload if payload is not None else {}, headers)

    def return_counts(self, lot_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/ballot-lots/{lot_id}/return-counts", payload, headers)

    # ─── Tabulator units ─────────────────────────────────────────────────────

    def create_tabulator(self, election_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/elections/{election_id}/tabulator-units", payload, headers)

    def get_tabulator(self, tabulator_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/tabulator-units/{tabulator_id}", None, headers)

    def list_tabulators(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("GET", "/tabulator-units", params, headers)

    def program_tabulator(self, tabulator_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/tabulator-units/{tabulator_id}/program", payload, headers)

    def deploy_tabulator(self, tabulator_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/tabulator-units/{tabulator_id}/deploy", payload, headers)

    def break_seal(self, tabulator_id: str, payload: Dict[str, Any],
                   headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/tabulator-units/{tabulator_id}/break-seal", payload, headers)

    def seal_retention(self, tabulator_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/tabulator-units/{tabulator_id}/seal-retention",
                             payload, headers)

    # ─── Logic and accuracy sessions ─────────────────────────────────────────

    def create_la_session(self, payload: Dict[str, Any],
                          headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/la-test-sessions", payload, headers)

    def get_la_session(self, session_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/la-test-sessions/{session_id}", None, headers)

    def list_la_sessions(self, headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("GET", "/la-test-sessions", params, headers)

    def add_observer(self, session_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/la-test-sessions/{session_id}/observers", payload, headers)

    def start_session(self, session_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("POST", f"/la-test-sessions/{session_id}/start",
                             payload if payload is not None else {}, headers)

    def record_results(self, session_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/la-test-sessions/{session_id}/record-results",
                             payload, headers)

    # ─── Raw escape hatch for negative-path probes ───────────────────────────

    def raw(self, method: str, path: str, payload: Any = None,
            headers: Optional[Dict[str, str]] = None,
            params: Optional[Dict[str, Any]] = None) -> requests.Response:
        """Send an arbitrary request, for probes that deliberately malform input."""
        return self._request(method, path, payload, headers, params)
