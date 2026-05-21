"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the base _request() method handles
HTTP plumbing. Tests pass headers explicitly because PRD §2.1
requires X-User-ID and X-User-Role on every request.

Paths are taken verbatim from the PRD §4 endpoint table — for example
POST /parks, POST /campgrounds/{campground_id}/reservations,
POST /lottery-applications/{id}/accept.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Clock / sweep — PRD §2.13, §4
    # =======================================================================
    def advance_clock(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload, headers)

    def run_sweep(self, headers: Dict[str, str],
                  payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", "/_sweep/run", payload or {}, headers)

    # =======================================================================
    # Visitors — PRD §3.1, §4
    # =======================================================================
    def create_visitor(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/visitors", payload, headers)

    def get_visitor(self, visitor_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/visitors/{visitor_id}", headers=headers,
        )

    def deposit_wallet(self, visitor_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/visitors/{visitor_id}/wallet/deposit",
            payload, headers,
        )

    def list_visitor_ledger(self, visitor_id: str,
                            headers: Dict[str, str],
                            params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/visitors/{visitor_id}/ledger",
            headers=headers, params=params,
        )

    # =======================================================================
    # Passes — PRD §3.1, §4
    # =======================================================================
    def issue_pass(self, visitor_id: str, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request(
            "POST", f"/visitors/{visitor_id}/passes", payload, headers,
        )

    def list_passes(self, visitor_id: str, headers: Dict[str, str],
                    params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/visitors/{visitor_id}/passes",
            headers=headers, params=params,
        )

    def revoke_pass(self, visitor_id: str, pass_id: str,
                    headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/visitors/{visitor_id}/passes/{pass_id}/revoke",
            None, headers,
        )

    # =======================================================================
    # Parks — PRD §2.7, §3.2, §4
    # =======================================================================
    def create_park(self, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request("POST", "/parks", payload, headers)

    def list_parks(self, headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/parks", headers=headers, params=params,
        )

    def get_park(self, park_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/parks/{park_id}", headers=headers,
        )

    def patch_park(self, park_id: str, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/parks/{park_id}", payload, headers,
        )

    def restrict_park(self, park_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/parks/{park_id}/restrict", None, headers,
        )

    def freeze_park(self, park_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/parks/{park_id}/freeze", None, headers,
        )

    def reopen_park(self, park_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/parks/{park_id}/reopen", None, headers,
        )

    # =======================================================================
    # Timed-entry reservations — PRD §3.3, §4
    # =======================================================================
    def create_timed_entry(self, park_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/parks/{park_id}/timed-entry", payload, headers,
        )

    def list_timed_entries(self, park_id: str, headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/parks/{park_id}/timed-entry",
            headers=headers, params=params,
        )

    def confirm_timed_entry(self, park_id: str, reservation_id: str,
                            headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/parks/{park_id}/timed-entry/{reservation_id}/confirm",
            None, headers,
        )

    def cancel_timed_entry(self, park_id: str, reservation_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/parks/{park_id}/timed-entry/{reservation_id}/cancel",
            None, headers,
        )

    def check_in_timed_entry(self, park_id: str, reservation_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/parks/{park_id}/timed-entry/{reservation_id}/check-in",
            None, headers,
        )

    # =======================================================================
    # Campgrounds — PRD §3.2, §3.4, §4
    # =======================================================================
    def create_campground(self, park_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/parks/{park_id}/campgrounds", payload, headers,
        )

    def list_campgrounds(self, park_id: str, headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/parks/{park_id}/campgrounds",
            headers=headers, params=params,
        )

    def create_campground_reservation(self, campground_id: str,
                                      payload: Dict[str, Any],
                                      headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/campgrounds/{campground_id}/reservations",
            payload, headers,
        )

    def list_campground_reservations(self, campground_id: str,
                                     headers: Dict[str, str],
                                     params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/campgrounds/{campground_id}/reservations",
            headers=headers, params=params,
        )

    def confirm_campground_reservation(self, campground_id: str,
                                       reservation_id: str,
                                       headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/campgrounds/{campground_id}/reservations/{reservation_id}/confirm",
            None, headers,
        )

    def cancel_campground_reservation(self, campground_id: str,
                                      reservation_id: str,
                                      headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/campgrounds/{campground_id}/reservations/{reservation_id}/cancel",
            None, headers,
        )

    def check_in_campground_reservation(self, campground_id: str,
                                        reservation_id: str,
                                        headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/campgrounds/{campground_id}/reservations/{reservation_id}/check-in",
            None, headers,
        )

    # =======================================================================
    # Waitlist — PRD §3.5, §4
    # =======================================================================
    def create_waitlist_entry(self, campground_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/campgrounds/{campground_id}/waitlist",
            payload, headers,
        )

    def list_waitlist(self, campground_id: str, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/campgrounds/{campground_id}/waitlist",
            headers=headers, params=params,
        )

    def delete_waitlist_entry(self, campground_id: str,
                              waitlist_id: str,
                              headers: Dict[str, str]):
        return self._request(
            "DELETE",
            f"/campgrounds/{campground_id}/waitlist/{waitlist_id}",
            headers=headers,
        )

    # =======================================================================
    # Lottery permits & applications — PRD §3.6, §4
    # =======================================================================
    def create_lottery_permit(self, park_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/parks/{park_id}/lottery-permits",
            payload, headers,
        )

    def list_lottery_permits(self, park_id: str, headers: Dict[str, str],
                             params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/parks/{park_id}/lottery-permits",
            headers=headers, params=params,
        )

    def create_lottery_application(self, permit_id: str,
                                   payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self._request(
            "POST", f"/lottery-permits/{permit_id}/applications",
            payload, headers,
        )

    def list_lottery_applications(self, permit_id: str,
                                  headers: Dict[str, str],
                                  params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/lottery-permits/{permit_id}/applications",
            headers=headers, params=params,
        )

    def draw_lottery(self, permit_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/lottery-permits/{permit_id}/draw", None, headers,
        )

    def accept_lottery_application(self, application_id: str,
                                   headers: Dict[str, str]):
        return self._request(
            "POST", f"/lottery-applications/{application_id}/accept",
            None, headers,
        )

    def decline_lottery_application(self, application_id: str,
                                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/lottery-applications/{application_id}/decline",
            None, headers,
        )

    def no_show_lottery_application(self, application_id: str,
                                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/lottery-applications/{application_id}/no-show",
            None, headers,
        )

    # =======================================================================
    # Backcountry — PRD §3.7, §4
    # =======================================================================
    def create_backcountry_zone(self, park_id: str,
                                payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", f"/parks/{park_id}/backcountry-zones",
            payload, headers,
        )

    def list_backcountry_zones(self, park_id: str,
                               headers: Dict[str, str],
                               params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/parks/{park_id}/backcountry-zones",
            headers=headers, params=params,
        )

    def create_backcountry_permit(self, zone_id: str,
                                  payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request(
            "POST", f"/backcountry-zones/{zone_id}/permits",
            payload, headers,
        )

    def confirm_backcountry_permit(self, zone_id: str, permit_id: str,
                                   headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/backcountry-zones/{zone_id}/permits/{permit_id}/confirm",
            None, headers,
        )

    def cancel_backcountry_permit(self, zone_id: str, permit_id: str,
                                  headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/backcountry-zones/{zone_id}/permits/{permit_id}/cancel",
            None, headers,
        )

    def check_out_backcountry_permit(self, zone_id: str, permit_id: str,
                                     headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/backcountry-zones/{zone_id}/permits/{permit_id}/check-out",
            None, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
