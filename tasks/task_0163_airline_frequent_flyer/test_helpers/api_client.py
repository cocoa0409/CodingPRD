"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the base _request() method handles HTTP
plumbing. Tests pass headers explicitly because PRD §2.1 requires
X-User-ID and X-User-Role on every request.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ======================================================================
    # Members — PRD §3.1, §4
    # ======================================================================
    def create_member(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/members", payload, headers)

    def list_members(self, headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/members", headers=headers, params=params)

    def get_member(self, member_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/members/{member_id}", headers=headers,
        )

    def patch_member(self, member_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/members/{member_id}", payload, headers,
        )

    def freeze_member(self, member_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/members/{member_id}/freeze",
            payload if payload is not None else {}, headers,
        )

    def unfreeze_member(self, member_id: str, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/members/{member_id}/unfreeze",
            payload if payload is not None else {}, headers,
        )

    # ======================================================================
    # Flights — PRD §3.2, §4
    # ======================================================================
    def create_flight(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/flights", payload, headers)

    def list_flights(self, headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/flights", headers=headers, params=params)

    def get_flight(self, flight_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/flights/{flight_id}", headers=headers,
        )

    def depart_flight(self, flight_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/flights/{flight_id}/depart",
            payload if payload is not None else {}, headers,
        )

    def cancel_flight(self, flight_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/flights/{flight_id}/cancel",
            payload if payload is not None else {}, headers,
        )

    # ======================================================================
    # Segments — PRD §3.3, §4
    # ======================================================================
    def create_segment(self, member_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/members/{member_id}/segments", payload, headers,
        )

    def list_segments(self, member_id: str, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/members/{member_id}/segments",
            headers=headers, params=params,
        )

    def mark_segment_flown(self, member_id: str, segment_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/members/{member_id}/segments/{segment_id}/mark-flown",
            payload if payload is not None else {}, headers,
        )

    def cancel_segment(self, member_id: str, segment_id: str,
                       headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/members/{member_id}/segments/{segment_id}/cancel",
            payload if payload is not None else {}, headers,
        )

    def refund_segment(self, member_id: str, segment_id: str,
                       headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/members/{member_id}/segments/{segment_id}/refund",
            payload if payload is not None else {}, headers,
        )

    # ======================================================================
    # Upgrade Requests — PRD §3.4, §4
    # ======================================================================
    def create_upgrade_request(self, member_id: str, segment_id: str,
                               payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/members/{member_id}/segments/{segment_id}/upgrade-requests",
            payload, headers,
        )

    def list_upgrade_requests(self, member_id: str,
                              headers: Dict[str, str],
                              params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/members/{member_id}/upgrade-requests",
            headers=headers, params=params,
        )

    def patch_upgrade_request(self, upgrade_request_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/upgrades/{upgrade_request_id}", payload, headers,
        )

    def cancel_upgrade_request(self, upgrade_request_id: str,
                               headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/upgrades/{upgrade_request_id}/cancel",
            payload if payload is not None else {}, headers,
        )

    def confirm_upgrade_request(self, upgrade_request_id: str,
                                headers: Dict[str, str],
                                payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/upgrades/{upgrade_request_id}/confirm",
            payload if payload is not None else {}, headers,
        )

    # ======================================================================
    # Award Bookings — PRD §3.5, §4
    # ======================================================================
    def create_award_booking(self, member_id: str, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/members/{member_id}/award-bookings", payload, headers,
        )

    def list_award_bookings(self, member_id: str,
                            headers: Dict[str, str],
                            params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/members/{member_id}/award-bookings",
            headers=headers, params=params,
        )

    def get_award_booking(self, member_id: str, booking_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "GET", f"/members/{member_id}/award-bookings/{booking_id}",
            headers=headers,
        )

    def confirm_award_booking(self, member_id: str, booking_id: str,
                              headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/members/{member_id}/award-bookings/{booking_id}/confirm",
            payload if payload is not None else {}, headers,
        )

    def cancel_award_booking(self, member_id: str, booking_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/members/{member_id}/award-bookings/{booking_id}/cancel",
            payload if payload is not None else {}, headers,
        )

    # ======================================================================
    # Companion Certificates — PRD §3.5, §4
    # ======================================================================
    def list_certificates(self, member_id: str, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/members/{member_id}/certificates",
            headers=headers, params=params,
        )

    def grant_certificate(self, member_id: str, headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/members/{member_id}/certificates",
            payload if payload is not None else {}, headers,
        )

    def revoke_certificate(self, member_id: str, cert_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/members/{member_id}/certificates/{cert_id}/revoke",
            payload if payload is not None else {}, headers,
        )

    # ======================================================================
    # Status Match — PRD §3.7, §4
    # ======================================================================
    def create_status_match_request(self, member_id: str,
                                    payload: Dict[str, Any],
                                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/members/{member_id}/status-match-requests",
            payload, headers,
        )

    def list_status_match_requests(self, member_id: str,
                                   headers: Dict[str, str],
                                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/members/{member_id}/status-match-requests",
            headers=headers, params=params,
        )

    def approve_status_match_request(self, member_id: str, rid: str,
                                     headers: Dict[str, str],
                                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/members/{member_id}/status-match-requests/{rid}/approve",
            payload if payload is not None else {}, headers,
        )

    def reject_status_match_request(self, member_id: str, rid: str,
                                    headers: Dict[str, str],
                                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/members/{member_id}/status-match-requests/{rid}/reject",
            payload if payload is not None else {}, headers,
        )

    def activate_status_match_request(self, member_id: str, rid: str,
                                      headers: Dict[str, str],
                                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/members/{member_id}/status-match-requests/{rid}/activate",
            payload if payload is not None else {}, headers,
        )

    # ======================================================================
    # Gifts / Points Ledger — PRD §3.6, §3.8, §4
    # ======================================================================
    def send_gift(self, sender_id: str, payload: Dict[str, Any],
                  headers: Dict[str, str]):
        return self._request(
            "POST", f"/members/{sender_id}/gifts", payload, headers,
        )

    def list_points_transactions(self, member_id: str,
                                 headers: Dict[str, str],
                                 params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/members/{member_id}/points-transactions",
            headers=headers, params=params,
        )

    def post_points_adjustment(self, member_id: str,
                               payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/members/{member_id}/points-transactions/adjustments",
            payload, headers,
        )

    # ======================================================================
    # Membership Years — PRD §3.1, §4
    # ======================================================================
    def list_membership_years(self, member_id: str,
                              headers: Dict[str, str],
                              params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/members/{member_id}/membership-years",
            headers=headers, params=params,
        )

    # ======================================================================
    # Ops surface — PRD §3.8, §4
    # ======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload, headers)

    def sweep_expire_points(self, headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", "/_sweep/expire-points",
            payload if payload is not None else {}, headers,
        )

    def sweep_expire_bookings(self, headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", "/_sweep/expire-bookings",
            payload if payload is not None else {}, headers,
        )

    def sweep_expire_certificates(self, headers: Dict[str, str],
                                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", "/_sweep/expire-certificates",
            payload if payload is not None else {}, headers,
        )

    def sweep_expire_status_matches(self, headers: Dict[str, str],
                                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", "/_sweep/expire-status-matches",
            payload if payload is not None else {}, headers,
        )

    def sweep_promote_upgrades(self, headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", "/_sweep/promote-upgrades",
            payload if payload is not None else {}, headers,
        )

    def sweep_annual_rollover(self, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", "/_sweep/annual-rollover", payload, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
