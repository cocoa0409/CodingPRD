"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the base _request() method handles HTTP
plumbing. Tests pass headers explicitly because PRD §2.1 requires
X-User-ID and X-User-Role on every request.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


_PREFIX = "/crew-scheduling"


class ApiClient(GenericApiClient):

    def _request(self, method, path, payload=None, headers=None, params=None):
        # PRD §1: API is mounted under /crew-scheduling. Prepend the prefix
        # to every endpoint path defined below so tests do not have to repeat it.
        if not path.startswith(_PREFIX):
            path = f"{_PREFIX}{path}"
        return super()._request(method, path, payload, headers, params)

    # ======================================================================
    # Crew Members — PRD §3.1, §4
    # ======================================================================
    def create_crew_member(self, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request("POST", "/crew-members", payload, headers)

    def get_crew_member(self, crew_member_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "GET", f"/crew-members/{crew_member_id}", headers=headers,
        )

    def list_crew_members(self, headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/crew-members", headers=headers, params=params,
        )

    # ======================================================================
    # Pairings — PRD §3.1, §4
    # ======================================================================
    def create_pairing(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/pairings", payload, headers)

    def add_duty_period(self, pairing_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/pairings/{pairing_id}/duty-periods", payload, headers,
        )

    def add_flight_leg(self, duty_period_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/duty-periods/{duty_period_id}/flight-legs",
            payload, headers,
        )

    def publish_pairing(self, pairing_id: str, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/pairings/{pairing_id}/publish",
            payload if payload is not None else {}, headers,
        )

    def open_bidding(self, pairing_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/pairings/{pairing_id}/open-bidding", payload, headers,
        )

    def cancel_pairing(self, pairing_id: str, headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/pairings/{pairing_id}/cancel",
            payload if payload is not None else {}, headers,
        )

    def get_pairing(self, pairing_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/pairings/{pairing_id}", headers=headers,
        )

    def list_pairings(self, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/pairings", headers=headers, params=params,
        )

    # ======================================================================
    # Bids — PRD §3.2, §3.3, §4
    # ======================================================================
    def create_bid(self, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request("POST", "/bids", payload, headers)

    def delete_bid(self, bid_id: str, headers: Dict[str, str]):
        return self._request("DELETE", f"/bids/{bid_id}", headers=headers)

    def award_bid_window(self, bid_window_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/bid-windows/{bid_window_id}/award",
            payload if payload is not None else {}, headers,
        )

    # ======================================================================
    # Reserve Pool — PRD §3.4, §4
    # ======================================================================
    def create_reserve_pool(self, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request("POST", "/reserve-pool", payload, headers)

    def call_out_reserve(self, reserve_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/reserve-pool/{reserve_id}/call-out",
            payload, headers,
        )

    def release_reserve(self, reserve_id: str, headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/reserve-pool/{reserve_id}/release",
            payload if payload is not None else {}, headers,
        )

    def list_reserve_pool(self, headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/reserve-pool", headers=headers, params=params,
        )

    # ======================================================================
    # Sick Calls — PRD §3.4, §4
    # ======================================================================
    def create_sick_call(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", "/sick-calls", payload, headers)

    def get_sick_call(self, sick_call_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/sick-calls/{sick_call_id}", headers=headers,
        )

    # ======================================================================
    # Assignments — PRD §3.4, §3.5, §3.6, §3.7, §4
    # ======================================================================
    def create_assignment(self, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request("POST", "/assignments", payload, headers)

    def release_assignment(self, assignment_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/assignments/{assignment_id}/release",
            payload if payload is not None else {}, headers,
        )

    def mark_assignment_no_show(self, assignment_id: str,
                                  headers: Dict[str, str],
                                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/assignments/{assignment_id}/mark-no-show",
            payload if payload is not None else {}, headers,
        )

    def get_assignment(self, assignment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/assignments/{assignment_id}", headers=headers,
        )

    def get_pay_credit_estimate(self, assignment_id: str,
                                 headers: Dict[str, str]):
        return self._request(
            "GET", f"/assignments/{assignment_id}/pay-credit-estimate",
            headers=headers,
        )

    def list_assignments(self, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/assignments", headers=headers, params=params,
        )

    # ======================================================================
    # Trade Requests — PRD §3.8, §4
    # ======================================================================
    def create_trade_request(self, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request("POST", "/trade-requests", payload, headers)

    def counter_trade_request(self, trade_request_id: str,
                                payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", f"/trade-requests/{trade_request_id}/counter",
            payload, headers,
        )

    def accept_trade_request(self, trade_request_id: str,
                               headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/trade-requests/{trade_request_id}/accept",
            payload if payload is not None else {}, headers,
        )

    def reject_trade_request(self, trade_request_id: str,
                               headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/trade-requests/{trade_request_id}/reject",
            payload if payload is not None else {}, headers,
        )

    def union_bless_trade(self, trade_request_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/trade-requests/{trade_request_id}/union-bless",
            payload if payload is not None else {}, headers,
        )

    def approve_trade_request(self, trade_request_id: str,
                                headers: Dict[str, str],
                                payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/trade-requests/{trade_request_id}/approve",
            payload if payload is not None else {}, headers,
        )

    def delete_trade_request(self, trade_request_id: str,
                              headers: Dict[str, str]):
        return self._request(
            "DELETE", f"/trade-requests/{trade_request_id}", headers=headers,
        )

    def get_trade_request(self, trade_request_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "GET", f"/trade-requests/{trade_request_id}", headers=headers,
        )

    # ======================================================================
    # Test-driving clock — PRD §3.7, §4
    # ======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload, headers)

    def clock_now(self, headers: Dict[str, str]):
        return self._request("POST", "/_clock/now", {}, headers)


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
