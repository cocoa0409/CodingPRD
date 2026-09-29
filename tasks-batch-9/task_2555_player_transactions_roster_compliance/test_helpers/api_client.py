"""One client method per endpoint of the Player Transactions & Roster Compliance API.

Every method returns the raw ``requests.Response`` so that tests can assert on
status codes as well as on the response envelope. Every request carries explicit
headers, because the PRD requires the identity headers on reads as well as writes.
"""

from typing import Any, Dict, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient

from .types import Headers, Payload


class ApiClient(GenericApiClient):
    """Typed facade over the transactions API."""

    # ------------------------------------------------------------------
    # Logical league clock
    # ------------------------------------------------------------------
    def set_clock(self, current_utc: str, headers: Headers) -> requests.Response:
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def set_clock_raw(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Clubs
    # ------------------------------------------------------------------
    def create_team(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", "/teams", payload, headers)

    def get_team(self, team_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/teams/{team_id}", None, headers)

    def list_teams(self, headers: Headers,
                   params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("GET", "/teams", None, headers, params=params)

    def patch_team_limits(self, team_id: str, payload: Payload,
                          headers: Headers) -> requests.Response:
        return self._request("PATCH", f"/teams/{team_id}/limits", payload, headers)

    def get_cap_ledger(self, team_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/teams/{team_id}/cap-ledger", None, headers)

    def list_team_compliance_checks(
        self, team_id: str, headers: Headers,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/teams/{team_id}/compliance-checks", None, headers, params=params
        )

    # ------------------------------------------------------------------
    # Players
    # ------------------------------------------------------------------
    def create_player(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", "/players", payload, headers)

    def get_player(self, player_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/players/{player_id}", None, headers)

    def list_players(self, headers: Headers,
                     params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("GET", "/players", None, headers, params=params)

    # ------------------------------------------------------------------
    # Contracts and bonus allocations
    # ------------------------------------------------------------------
    def get_contract(self, contract_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/contracts/{contract_id}", None, headers)

    def list_contracts(self, headers: Headers,
                       params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("GET", "/contracts", None, headers, params=params)

    def decide_option(self, contract_id: str, payload: Payload,
                      headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"/contracts/{contract_id}/option-decision", payload, headers
        )

    def list_bonus_allocations(
        self, contract_id: str, headers: Headers,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/contracts/{contract_id}/bonus-allocations", None, headers,
            params=params,
        )

    def list_contract_trade_assets(
        self, contract_id: str, headers: Headers,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/contracts/{contract_id}/trade-assets", None, headers,
            params=params,
        )

    def earn_bonus_allocation(self, allocation_id: str,
                              headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"/bonus-allocations/{allocation_id}/earn", {}, headers
        )

    # ------------------------------------------------------------------
    # Filings
    # ------------------------------------------------------------------
    def create_transaction(self, payload: Payload,
                           headers: Headers) -> requests.Response:
        return self._request("POST", "/transactions", payload, headers)

    def get_transaction(self, transaction_id: str,
                        headers: Headers) -> requests.Response:
        return self._request("GET", f"/transactions/{transaction_id}", None, headers)

    def list_transactions(self, headers: Headers,
                          params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("GET", "/transactions", None, headers, params=params)

    def file_transaction(self, transaction_id: str,
                         headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"/transactions/{transaction_id}/file", {}, headers
        )

    def decide_transaction(self, transaction_id: str, payload: Payload,
                           headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"/transactions/{transaction_id}/decide", payload, headers
        )

    def revise_transaction(self, transaction_id: str, payload: Payload,
                           headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"/transactions/{transaction_id}/revise", payload, headers
        )

    # ------------------------------------------------------------------
    # Waiver wire
    # ------------------------------------------------------------------
    def create_waiver_request(self, payload: Payload,
                              headers: Headers) -> requests.Response:
        return self._request("POST", "/waiver-requests", payload, headers)

    def get_waiver_request(self, waiver_request_id: str,
                           headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"/waiver-requests/{waiver_request_id}", None, headers
        )

    def list_waiver_requests(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/waiver-requests", None, headers, params=params)

    def withdraw_waiver_request(self, waiver_request_id: str,
                                headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"/waiver-requests/{waiver_request_id}/withdraw", {}, headers
        )

    def submit_waiver_claim(self, waiver_request_id: str, payload: Payload,
                            headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"/waiver-requests/{waiver_request_id}/claims", payload, headers
        )

    def get_waiver_claim(self, waiver_claim_id: str,
                         headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"/waiver-claims/{waiver_claim_id}", None, headers
        )

    def list_waiver_claims(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/waiver-claims", None, headers, params=params)

    def process_waiver_request(self, waiver_request_id: str,
                               headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"/waiver-requests/{waiver_request_id}/process", {}, headers
        )

    # ------------------------------------------------------------------
    # Trades
    # ------------------------------------------------------------------
    def create_trade(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", "/trades", payload, headers)

    def get_trade(self, trade_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/trades/{trade_id}", None, headers)

    def list_trades(self, headers: Headers,
                    params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("GET", "/trades", None, headers, params=params)

    def add_trade_asset(self, trade_id: str, payload: Payload,
                        headers: Headers) -> requests.Response:
        return self._request("POST", f"/trades/{trade_id}/assets", payload, headers)

    def list_trade_assets(self, trade_id: str, headers: Headers,
                          params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request(
            "GET", f"/trades/{trade_id}/assets", None, headers, params=params
        )

    def counter_trade(self, trade_id: str, payload: Payload,
                      headers: Headers) -> requests.Response:
        return self._request("POST", f"/trades/{trade_id}/counter", payload, headers)

    def accept_trade(self, trade_id: str, headers: Headers) -> requests.Response:
        return self._request("POST", f"/trades/{trade_id}/accept", {}, headers)

    def execute_trade(self, trade_id: str, headers: Headers) -> requests.Response:
        return self._request("POST", f"/trades/{trade_id}/execute", {}, headers)

    # ------------------------------------------------------------------
    # Tenders and qualifying offers
    # ------------------------------------------------------------------
    def create_tender(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", "/qualifying-offers", payload, headers)

    def get_tender(self, tender_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/qualifying-offers/{tender_id}", None, headers)

    def list_tenders(self, headers: Headers,
                     params: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("GET", "/qualifying-offers", None, headers, params=params)

    def respond_to_tender(self, tender_id: str, payload: Payload,
                          headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"/qualifying-offers/{tender_id}/respond", payload, headers
        )

    # ------------------------------------------------------------------
    # Medical dimension
    # ------------------------------------------------------------------
    def create_injury_designation(self, payload: Payload,
                                  headers: Headers) -> requests.Response:
        return self._request("POST", "/injury-designations", payload, headers)

    def get_injury_designation(self, designation_id: str,
                               headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"/injury-designations/{designation_id}", None, headers
        )

    def list_injury_designations(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/injury-designations", None, headers, params=params
        )

    def file_injury_paperwork(self, designation_id: str, payload: Payload,
                              headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"/injury-designations/{designation_id}/file-paperwork",
            payload, headers,
        )

    def create_physical_exam(self, payload: Payload,
                             headers: Headers) -> requests.Response:
        return self._request("POST", "/physical-exams", payload, headers)

    def get_physical_exam(self, exam_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/physical-exams/{exam_id}", None, headers)

    def list_physical_exams(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/physical-exams", None, headers, params=params)

    def record_exam_result(self, exam_id: str, payload: Payload,
                           headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"/physical-exams/{exam_id}/record-result", payload, headers
        )

    # ------------------------------------------------------------------
    # Compliance sweep
    # ------------------------------------------------------------------
    def run_compliance_check(self, payload: Payload,
                             headers: Headers) -> requests.Response:
        return self._request("POST", "/compliance-checks/run", payload, headers)
