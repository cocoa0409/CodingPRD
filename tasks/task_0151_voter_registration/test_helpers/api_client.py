"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the base _request() method handles
HTTP plumbing. Tests pass headers explicitly because PRD §2.1
requires X-User-ID and X-User-Role on every request.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Clock — PRD §2.5, §4
    # =======================================================================
    def advance_clock(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload, headers)

    def get_clock(self, headers: Dict[str, str]):
        return self._request("GET", "/_clock", headers=headers)

    # =======================================================================
    # Elections — PRD §3.1, §3.2, §4
    # =======================================================================
    def create_election(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/elections", payload, headers)

    def get_election(self, election_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/elections/{election_id}", headers=headers,
        )

    def list_elections(self, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/elections", headers=headers, params=params,
        )

    def transition_election(self, election_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/elections/{election_id}/state", payload, headers,
        )

    def get_tally(self, election_id: str, headers: Dict[str, str],
                  variant: Optional[str] = None):
        params = {"variant": variant} if variant else None
        return self._request(
            "GET", f"/elections/{election_id}/tally",
            headers=headers, params=params,
        )

    # =======================================================================
    # Precincts — PRD §3.1, §4
    # =======================================================================
    def create_precinct(self, election_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/elections/{election_id}/precincts",
            payload, headers,
        )

    def get_precinct(self, election_id: str, precinct_id: str,
                     headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/elections/{election_id}/precincts/{precinct_id}",
            headers=headers,
        )

    def list_precincts(self, election_id: str,
                       headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/elections/{election_id}/precincts",
            headers=headers, params=params,
        )

    # =======================================================================
    # Voters — PRD §3.3, §3.4, §4
    # =======================================================================
    def create_voter(self, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request("POST", "/voters", payload, headers)

    def get_voter(self, voter_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/voters/{voter_id}", headers=headers,
        )

    def patch_voter(self, voter_id: str,
                    payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/voters/{voter_id}", payload, headers,
        )

    def transition_voter(self, voter_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/voters/{voter_id}/state", payload, headers,
        )

    def change_party(self, voter_id: str,
                     payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/voters/{voter_id}/party-registration",
            payload, headers,
        )

    def list_party_registration(self, voter_id: str,
                                headers: Dict[str, str],
                                params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/voters/{voter_id}/party-registration",
            headers=headers, params=params,
        )

    # =======================================================================
    # Absentee ballots — PRD §3.5, §4
    # =======================================================================
    def request_absentee_ballot(self, voter_id: str,
                                payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", f"/voters/{voter_id}/absentee-ballots",
            payload, headers,
        )

    def get_absentee_ballot(self, ballot_id: str,
                            headers: Dict[str, str]):
        return self._request(
            "GET", f"/absentee-ballots/{ballot_id}", headers=headers,
        )

    def transition_absentee_ballot(self, ballot_id: str,
                                   payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self._request(
            "POST", f"/absentee-ballots/{ballot_id}/state",
            payload, headers,
        )

    def return_absentee_ballot(self, ballot_id: str,
                               payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", f"/absentee-ballots/{ballot_id}/return",
            payload, headers,
        )

    # =======================================================================
    # Curing cases — PRD §3.5, §4
    # =======================================================================
    def get_curing_case(self, case_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/curing-cases/{case_id}", headers=headers,
        )

    def submit_curing_case(self, case_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/curing-cases/{case_id}/submit",
            payload, headers,
        )

    def request_revision_curing_case(self, case_id: str,
                                     payload: Dict[str, Any],
                                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/curing-cases/{case_id}/request-revision",
            payload, headers,
        )

    def transition_curing_case(self, case_id: str,
                               payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", f"/curing-cases/{case_id}/state",
            payload, headers,
        )

    # =======================================================================
    # In-person ballots — PRD §3.8, §4
    # =======================================================================
    def create_ballot(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/ballots", payload, headers)

    def get_ballot(self, ballot_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/ballots/{ballot_id}", headers=headers,
        )

    def transition_ballot(self, ballot_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/ballots/{ballot_id}/state", payload, headers,
        )

    # =======================================================================
    # Voting machines — PRD §3.7, §4
    # =======================================================================
    def create_voting_machine(self, election_id: str, precinct_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/elections/{election_id}/precincts/{precinct_id}"
            "/voting-machines",
            payload, headers,
        )

    def get_voting_machine(self, machine_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "GET", f"/voting-machines/{machine_id}", headers=headers,
        )

    def transition_voting_machine(self, machine_id: str,
                                  payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request(
            "POST", f"/voting-machines/{machine_id}/state",
            payload, headers,
        )

    # =======================================================================
    # Recount requests — PRD §3.9, §4
    # =======================================================================
    def create_recount(self, election_id: str,
                       payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/elections/{election_id}/recounts",
            payload, headers,
        )

    def list_recounts(self, election_id: str,
                      headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/elections/{election_id}/recounts",
            headers=headers, params=params,
        )

    def transition_recount(self, recount_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/recounts/{recount_id}/state",
            payload, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
