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
    # Grids — PRD §3.1, §4
    # ======================================================================
    def create_grid(self, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request("POST", "/grids", payload, headers)

    def list_grids(self, headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/grids", headers=headers, params=params)

    def get_grid(self, grid_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/grids/{grid_id}", headers=headers,
        )

    def patch_grid(self, grid_id: str, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/grids/{grid_id}", payload, headers,
        )

    def get_heatmap(self, headers: Dict[str, str],
                    params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/grids/heatmap", headers=headers, params=params,
        )

    # ======================================================================
    # Drivers — PRD §3.2, §3.6, §4
    # ======================================================================
    def create_driver(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/drivers", payload, headers)

    def get_driver(self, driver_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/drivers/{driver_id}", headers=headers,
        )

    def patch_driver_quest(self, driver_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/drivers/{driver_id}/quest", payload, headers,
        )

    def go_online(self, driver_id: str, payload: Dict[str, Any],
                  headers: Dict[str, str]):
        return self._request(
            "POST", f"/drivers/{driver_id}/go-online", payload, headers,
        )

    def go_offline(self, driver_id: str, headers: Dict[str, str],
                   payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/drivers/{driver_id}/go-offline",
            payload if payload is not None else {}, headers,
        )

    # ======================================================================
    # Riders — PRD §3.3, §4
    # ======================================================================
    def create_rider(self, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request("POST", "/riders", payload, headers)

    def get_rider(self, rider_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/riders/{rider_id}", headers=headers,
        )

    # ======================================================================
    # Rush-Hour Windows — PRD §3.5, §4
    # ======================================================================
    def create_rush_hour_window(self, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", "/rush-hour-windows", payload, headers,
        )

    def list_rush_hour_windows(self, headers: Dict[str, str],
                               params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/rush-hour-windows", headers=headers, params=params,
        )

    def patch_rush_hour_window(self, window_id: str,
                               payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/rush-hour-windows/{window_id}", payload, headers,
        )

    # ======================================================================
    # Quest Bonuses — PRD §3.6, §4
    # ======================================================================
    def create_quest_bonus(self, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request("POST", "/quest-bonuses", payload, headers)

    def list_quest_bonuses(self, headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/quest-bonuses", headers=headers, params=params,
        )

    def get_quest_bonus(self, quest_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/quest-bonuses/{quest_id}", headers=headers,
        )

    # ======================================================================
    # Airport Queue — PRD §3.2, §4
    # ======================================================================
    def airport_queue_join(self, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", "/airport-queue/join", payload, headers,
        )

    def airport_queue_leave(self, headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", "/airport-queue/leave",
            payload if payload is not None else {}, headers,
        )

    def list_airport_queue(self, headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/airport-queue", headers=headers, params=params,
        )

    # ======================================================================
    # Rides — PRD §3.3, §3.4, §4
    # ======================================================================
    def create_ride(self, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request("POST", "/rides", payload, headers)

    def get_ride(self, ride_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/rides/{ride_id}", headers=headers,
        )

    def list_rides(self, headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/rides", headers=headers, params=params,
        )

    def assign_ride(self, ride_id: str, headers: Dict[str, str],
                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/rides/{ride_id}/assign",
            payload if payload is not None else {}, headers,
        )

    def start_ride(self, ride_id: str, headers: Dict[str, str],
                   payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/rides/{ride_id}/start",
            payload if payload is not None else {}, headers,
        )

    def complete_ride(self, ride_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/rides/{ride_id}/complete",
            payload if payload is not None else {}, headers,
        )

    def cancel_ride(self, ride_id: str, headers: Dict[str, str],
                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/rides/{ride_id}/cancel",
            payload if payload is not None else {}, headers,
        )

    # ======================================================================
    # Disputes — PRD §3.7, §4
    # ======================================================================
    def create_dispute(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/disputes", payload, headers)

    def get_dispute(self, dispute_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/disputes/{dispute_id}", headers=headers,
        )

    def list_disputes(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/disputes", headers=headers, params=params,
        )

    def approve_dispute(self, dispute_id: str, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/disputes/{dispute_id}/approve",
            payload if payload is not None else {}, headers,
        )

    def reject_dispute(self, dispute_id: str, headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/disputes/{dispute_id}/reject",
            payload if payload is not None else {}, headers,
        )

    # ======================================================================
    # Test-driving endpoints — PRD §4
    # ======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload, headers)

    def sweep_recompute_surge(self, headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", "/_sweep/recompute_surge",
            payload if payload is not None else {}, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
