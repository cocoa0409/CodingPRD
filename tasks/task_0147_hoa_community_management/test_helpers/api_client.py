"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the base _request() method handles
HTTP plumbing. Tests pass headers explicitly because PRD §2.1
requires X-User-ID and X-User-Role on every request.

PRD §1: "The API is mounted under the prefix /hoa".
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Units — PRD §3.1, §4
    # =======================================================================
    def create_unit(self, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request("POST", "/hoa/units", payload, headers)

    def get_unit(self, unit_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/hoa/units/{unit_id}", headers=headers,
        )

    def patch_unit(self, unit_id: str, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/hoa/units/{unit_id}", payload, headers,
        )

    # =======================================================================
    # Members — PRD §3.1, §4
    # =======================================================================
    def create_member(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/hoa/members", payload, headers)

    def get_member(self, member_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/hoa/members/{member_id}", headers=headers,
        )

    # =======================================================================
    # Assessment cycles — PRD §3.2, §4
    # =======================================================================
    def create_assessment_cycle(self, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", "/hoa/assessment-cycles", payload, headers,
        )

    def issue_assessment_cycle(self, cycle_id: str,
                               payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", f"/hoa/assessment-cycles/{cycle_id}/issue",
            payload, headers,
        )

    def close_assessment_cycle(self, cycle_id: str,
                               payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", f"/hoa/assessment-cycles/{cycle_id}/close",
            payload, headers,
        )

    def void_assessment_cycle(self, cycle_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/hoa/assessment-cycles/{cycle_id}/void",
            payload, headers,
        )

    # =======================================================================
    # Assessment charges — PRD §3.3, §4
    # =======================================================================
    def get_assessment_charge(self, charge_id: str,
                              headers: Dict[str, str]):
        return self._request(
            "GET", f"/hoa/assessment-charges/{charge_id}",
            headers=headers,
        )

    def write_off_assessment_charge(self, charge_id: str,
                                    payload: Dict[str, Any],
                                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/hoa/assessment-charges/{charge_id}/write-off",
            payload, headers,
        )

    # =======================================================================
    # Payments — PRD §3.3, §4
    # =======================================================================
    def create_payment(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/hoa/payments", payload, headers)

    # =======================================================================
    # ACC requests — PRD §3.4, §4
    # =======================================================================
    def create_acc_request(self, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", "/hoa/acc-requests", payload, headers,
        )

    def begin_review_acc_request(self, request_id: str,
                                 payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "POST", f"/hoa/acc-requests/{request_id}/begin-review",
            payload, headers,
        )

    def vote_acc_request(self, request_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/hoa/acc-requests/{request_id}/votes",
            payload, headers,
        )

    def withdraw_acc_request(self, request_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "DELETE", f"/hoa/acc-requests/{request_id}", headers=headers,
        )

    def get_acc_request(self, request_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "GET", f"/hoa/acc-requests/{request_id}", headers=headers,
        )

    # =======================================================================
    # Violations — PRD §3.5, §4
    # =======================================================================
    def create_violation(self, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", "/hoa/violations", payload, headers,
        )

    def cure_violation(self, violation_id: str,
                       payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/hoa/violations/{violation_id}/cure",
            payload, headers,
        )

    def waive_violation(self, violation_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/hoa/violations/{violation_id}/waive",
            payload, headers,
        )

    def get_violation(self, violation_id: str,
                      headers: Dict[str, str]):
        return self._request(
            "GET", f"/hoa/violations/{violation_id}", headers=headers,
        )

    # =======================================================================
    # Board resolutions — PRD §3.8, §4
    # =======================================================================
    def create_board_resolution(self, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", "/hoa/board-resolutions", payload, headers,
        )

    def vote_board_resolution(self, resolution_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/hoa/board-resolutions/{resolution_id}/votes",
            payload, headers,
        )

    def get_board_resolution(self, resolution_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "GET", f"/hoa/board-resolutions/{resolution_id}",
            headers=headers,
        )

    # =======================================================================
    # Elections — PRD §3.7, §4
    # =======================================================================
    def create_election(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", "/hoa/elections", payload, headers,
        )

    def create_candidate(self, election_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/hoa/elections/{election_id}/candidates",
            payload, headers,
        )

    def create_ballot(self, election_id: str,
                      payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/hoa/elections/{election_id}/ballots",
            payload, headers,
        )

    def certify_election(self, election_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/hoa/elections/{election_id}/certify",
            payload, headers,
        )

    def get_election(self, election_id: str,
                     headers: Dict[str, str]):
        return self._request(
            "GET", f"/hoa/elections/{election_id}", headers=headers,
        )

    # =======================================================================
    # Liens — PRD §3.6, §4
    # =======================================================================
    def create_lien(self, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request("POST", "/hoa/liens", payload, headers)

    def record_lien(self, lien_id: str,
                    payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/hoa/liens/{lien_id}/record", payload, headers,
        )

    def release_lien(self, lien_id: str,
                     payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/hoa/liens/{lien_id}/release", payload, headers,
        )

    def list_liens(self, headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/hoa/liens", headers=headers, params=params,
        )

    def get_lien(self, lien_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/hoa/liens/{lien_id}", headers=headers,
        )

    # =======================================================================
    # Reserve studies — PRD §3.9, §4
    # =======================================================================
    def create_reserve_study(self, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", "/hoa/reserve-studies", payload, headers,
        )

    def adopt_reserve_study(self, study_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/hoa/reserve-studies/{study_id}/adopt",
            payload, headers,
        )

    def get_reserve_study(self, study_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "GET", f"/hoa/reserve-studies/{study_id}", headers=headers,
        )

    # =======================================================================
    # Logical clock — PRD §3.10, §4
    # =======================================================================
    def advance_clock(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/hoa/_clock/advance", payload, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
