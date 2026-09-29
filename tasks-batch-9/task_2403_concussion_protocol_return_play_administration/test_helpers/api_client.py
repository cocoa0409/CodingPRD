"""
Typed API client for the Concussion Protocol & Return-to-Play Administration API.

One method per endpoint in the PRD endpoint table, plus the administrative
logical-clock endpoint, which is the single exception to the
`/concussion-program` mount.

Every method returns the raw `requests.Response` so tests can assert on status
codes as well as bodies.
"""

from typing import Any, Dict, List, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX, CLOCK_PATH


def _clean(params: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Drop keys whose value is None so unset filters are simply absent."""
    if params is None:
        return None
    return {k: v for k, v in params.items() if v is not None}


class ApiClient(GenericApiClient):
    """HTTP client covering every endpoint of the concussion-protocol API."""

    # ── Logical clock ────────────────────────────────────────────────────────

    def set_clock(self, current_utc: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", CLOCK_PATH, {"current_utc": current_utc}, headers)

    # ── Clubs ────────────────────────────────────────────────────────────────

    def create_club(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/clubs", payload, headers)

    def get_club(self, club_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/clubs/{club_id}", None, headers)

    def list_club_players(
        self, club_id: str, headers: Dict[str, str], **filters: Any
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/clubs/{club_id}/players", _clean(filters), headers
        )

    def get_compliance_summary(self, club_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/clubs/{club_id}/compliance-summary", None, headers
        )

    # ── Clinicians ───────────────────────────────────────────────────────────

    def create_clinician(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/clinicians", payload, headers)

    def suspend_clinician(
        self, clinician_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/clinicians/{clinician_id}/suspend", payload, headers
        )

    def get_clinician(self, clinician_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/clinicians/{clinician_id}", None, headers)

    def list_clinicians(self, headers: Dict[str, str], **filters: Any) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/clinicians", _clean(filters), headers)

    # ── Players ──────────────────────────────────────────────────────────────

    def create_player(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/players", payload, headers)

    def get_player(self, player_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/players/{player_id}", None, headers)

    def list_players(self, headers: Dict[str, str], **filters: Any) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/players", _clean(filters), headers)

    # ── Games ────────────────────────────────────────────────────────────────

    def create_game(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/games", payload, headers)

    def advance_game_status(
        self, game_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/games/{game_id}/advance-status", payload, headers
        )

    def get_game(self, game_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/games/{game_id}", None, headers)

    def list_games(self, headers: Dict[str, str], **filters: Any) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/games", _clean(filters), headers)

    # ── Baseline tests ───────────────────────────────────────────────────────

    def create_baseline_test(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/baseline-tests", payload, headers)

    def invalidate_baseline_test(
        self, baseline_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/baseline-tests/{baseline_id}/invalidate", payload, headers
        )

    def get_baseline_test(self, baseline_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/baseline-tests/{baseline_id}", None, headers)

    def list_baseline_tests(self, headers: Dict[str, str], **filters: Any) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/baseline-tests", _clean(filters), headers)

    # ── Sideline evaluations ─────────────────────────────────────────────────

    def create_sideline_evaluation(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/sideline-evaluations", payload, headers)

    def screen_evaluation(
        self, evaluation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/sideline-evaluations/{evaluation_id}/screen", payload, headers
        )

    def start_locker_room_exam(
        self, evaluation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/sideline-evaluations/{evaluation_id}/locker-room-exam",
            payload,
            headers,
        )

    def diagnose_concussion(
        self, evaluation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/sideline-evaluations/{evaluation_id}/diagnose-concussion",
            payload,
            headers,
        )

    def conclude_no_concussion(
        self, evaluation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/sideline-evaluations/{evaluation_id}/conclude-no-concussion",
            payload,
            headers,
        )

    def clear_to_return(
        self, evaluation_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/sideline-evaluations/{evaluation_id}/clear-to-return",
            payload if payload is not None else {},
            headers,
        )

    def get_sideline_evaluation(
        self, evaluation_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/sideline-evaluations/{evaluation_id}", None, headers
        )

    def list_sideline_evaluations(
        self, headers: Dict[str, str], **filters: Any
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/sideline-evaluations", _clean(filters), headers
        )

    # ── Concussion cases ─────────────────────────────────────────────────────

    def create_return_step(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/concussion-cases/{case_id}/return-steps", payload, headers
        )

    def request_inc_clearance(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/concussion-cases/{case_id}/inc-clearances", payload, headers
        )

    def return_to_contact(
        self, case_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/concussion-cases/{case_id}/return-to-contact",
            payload if payload is not None else {},
            headers,
        )

    def grant_roster_exemption(
        self, case_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/concussion-cases/{case_id}/roster-exemption", {}, headers
        )

    def symptom_check(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/concussion-cases/{case_id}/symptom-check", payload, headers
        )

    def get_concussion_case(self, case_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/concussion-cases/{case_id}", None, headers)

    def list_concussion_cases(self, headers: Dict[str, str], **filters: Any) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/concussion-cases", _clean(filters), headers)

    # ── Return steps ─────────────────────────────────────────────────────────

    def evaluate_return_step(
        self, step_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/return-steps/{step_id}/evaluate", payload, headers
        )

    def get_return_step(self, step_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/return-steps/{step_id}", None, headers)

    def list_return_steps(self, headers: Dict[str, str], **filters: Any) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/return-steps", _clean(filters), headers)

    # ── Consultant clearances ────────────────────────────────────────────────

    def decide_inc_clearance(
        self, clearance_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/inc-clearances/{clearance_id}/decide", payload, headers
        )

    def get_inc_clearance(self, clearance_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/inc-clearances/{clearance_id}", None, headers)

    def list_inc_clearances(self, headers: Dict[str, str], **filters: Any) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/inc-clearances", _clean(filters), headers)

    # ── Protocol audits ──────────────────────────────────────────────────────

    def create_protocol_audit(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/protocol-audits", payload, headers)

    def issue_findings(
        self, audit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/protocol-audits/{audit_id}/findings", payload, headers
        )

    def respond_to_audit(
        self, audit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/protocol-audits/{audit_id}/respond", payload, headers
        )

    def close_audit(
        self, audit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/protocol-audits/{audit_id}/close", payload, headers
        )

    def get_protocol_audit(self, audit_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/protocol-audits/{audit_id}", None, headers)

    def list_protocol_audits(self, headers: Dict[str, str], **filters: Any) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/protocol-audits", _clean(filters), headers)

    # ── Injury report entries ────────────────────────────────────────────────

    def create_injury_report_entry(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/injury-report-entries", payload, headers)

    def amend_injury_report_entry(
        self, entry_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/injury-report-entries/{entry_id}/amend", payload, headers
        )

    def get_injury_report_entry(self, entry_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/injury-report-entries/{entry_id}", None, headers
        )

    def list_injury_report_entries(
        self, headers: Dict[str, str], **filters: Any
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/injury-report-entries", _clean(filters), headers
        )

    # ── Operational sweep ────────────────────────────────────────────────────

    def run_protocol_sweep(self, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/protocol-sweeps", {}, headers)

    # ── Raw escape hatch ─────────────────────────────────────────────────────

    def raw(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """Send an arbitrary request; used for malformed-input probes."""
        return self._request(method, path, payload, headers, params)


__all__: List[str] = ["ApiClient"]
