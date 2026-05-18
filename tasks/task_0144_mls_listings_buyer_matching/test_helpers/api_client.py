"""API client: one method per endpoint defined in PRD §4.

Subclasses GenericApiClient from the framework — the base _request()
method handles HTTP plumbing. Tests pass headers explicitly because
PRD §2.1 requires X-User-Role and X-User-ID on every request.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Agents — PRD §3.1, §4
    # =======================================================================
    def create_agent(self, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request("POST", "/agents", payload, headers)

    def get_agent(self, agent_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/agents/{agent_id}", headers=headers)

    def patch_agent(self, agent_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/agents/{agent_id}", payload, headers,
        )

    # =======================================================================
    # Listings — PRD §3.2, §4
    # =======================================================================
    def create_listing(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/listings", payload, headers)

    def get_listing(self, listing_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/listings/{listing_id}", headers=headers,
        )

    def list_listings(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/listings", headers=headers, params=params,
        )

    def patch_listing(self, listing_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/listings/{listing_id}", payload, headers,
        )

    def withdraw_listing(self, listing_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/listings/{listing_id}/withdraw", payload, headers,
        )

    def close_listing(self, listing_id: str,
                      payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/listings/{listing_id}/close", payload, headers,
        )

    def get_listing_buyer_matches(self, listing_id: str,
                                  headers: Dict[str, str],
                                  params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/listings/{listing_id}/buyer-matches",
            headers=headers, params=params,
        )

    # =======================================================================
    # Buyers — PRD §3.3, §4
    # =======================================================================
    def create_buyer(self, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request("POST", "/buyers", payload, headers)

    def get_buyer(self, buyer_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/buyers/{buyer_id}", headers=headers,
        )

    def patch_buyer(self, buyer_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/buyers/{buyer_id}", payload, headers,
        )

    def get_buyer_matches(self, buyer_id: str,
                          headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/buyers/{buyer_id}/matches",
            headers=headers, params=params,
        )

    # =======================================================================
    # Lockbox — PRD §3.5, §4
    # =======================================================================
    def create_lockbox(self, listing_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/listings/{listing_id}/lockbox", payload, headers,
        )

    def arm_lockbox(self, listing_id: str, headers: Dict[str, str],
                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/listings/{listing_id}/lockbox/arm",
            payload if payload is not None else {}, headers,
        )

    def disarm_lockbox(self, listing_id: str, headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/listings/{listing_id}/lockbox/disarm",
            payload if payload is not None else {}, headers,
        )

    def retire_lockbox(self, listing_id: str, headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/listings/{listing_id}/lockbox/retire",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # Showings — PRD §3.5, §4
    # =======================================================================
    def request_showing(self, listing_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/listings/{listing_id}/showings", payload, headers,
        )

    def approve_showing(self, listing_id: str, showing_id: str,
                        headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/listings/{listing_id}/showings/{showing_id}/approve",
            payload if payload is not None else {}, headers,
        )

    def complete_showing(self, listing_id: str, showing_id: str,
                         headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/listings/{listing_id}/showings/{showing_id}/complete",
            payload if payload is not None else {}, headers,
        )

    def cancel_showing(self, listing_id: str, showing_id: str,
                       headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/listings/{listing_id}/showings/{showing_id}/cancel",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # Offers — PRD §3.6, §4
    # =======================================================================
    def submit_offer(self, listing_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/listings/{listing_id}/offers", payload, headers,
        )

    def list_offers(self, listing_id: str, headers: Dict[str, str],
                    params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/listings/{listing_id}/offers",
            headers=headers, params=params,
        )

    def accept_offer(self, listing_id: str, offer_id: str,
                     headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/listings/{listing_id}/offers/{offer_id}/accept",
            payload if payload is not None else {}, headers,
        )

    def reject_offer(self, listing_id: str, offer_id: str,
                     headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/listings/{listing_id}/offers/{offer_id}/reject",
            payload if payload is not None else {}, headers,
        )

    def withdraw_offer(self, listing_id: str, offer_id: str,
                       headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/listings/{listing_id}/offers/{offer_id}/withdraw",
            payload if payload is not None else {}, headers,
        )

    def counter_offer(self, listing_id: str, offer_id: str,
                      payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/listings/{listing_id}/offers/{offer_id}/counter",
            payload, headers,
        )

    def rebound_offer(self, listing_id: str, offer_id: str,
                      payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/listings/{listing_id}/offers/{offer_id}/rebound",
            payload, headers,
        )

    # =======================================================================
    # Contingencies — PRD §3.7, §4
    # =======================================================================
    def create_contingency(self, listing_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/listings/{listing_id}/contingencies",
            payload, headers,
        )

    def satisfy_contingency(self, listing_id: str, contingency_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/listings/{listing_id}/contingencies/{contingency_id}/satisfy",
            payload if payload is not None else {}, headers,
        )

    def waive_contingency(self, listing_id: str, contingency_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/listings/{listing_id}/contingencies/{contingency_id}/waive",
            payload if payload is not None else {}, headers,
        )

    def fail_contingency(self, listing_id: str, contingency_id: str,
                         headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/listings/{listing_id}/contingencies/{contingency_id}/fail",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # Commission splits (read-only) — PRD §3.8, §4
    # =======================================================================
    def list_commission_splits(self, listing_id: str,
                               headers: Dict[str, str],
                               params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/listings/{listing_id}/commission-splits",
            headers=headers, params=params,
        )

    # =======================================================================
    # Test harness — PRD §2.9, §3.9, §4
    # =======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload, headers)

    def sweep_run(self, headers: Dict[str, str],
                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", "/_sweep/run",
            payload if payload is not None else {}, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
