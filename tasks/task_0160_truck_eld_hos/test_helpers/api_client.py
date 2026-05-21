"""API client: one method per endpoint defined in the PRD §4 table.

Subclass of GenericApiClient — the base `_request()` handles HTTP
plumbing. Method names mirror the PRD §4 endpoint table.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ======================================================================
    # Carriers — PRD §3.1
    # ======================================================================
    def create_carrier(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/carriers", payload, headers)

    def get_carrier(self, carrier_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/carriers/{carrier_id}", headers=headers,
        )

    # ======================================================================
    # ELD devices — PRD §3.1
    # ======================================================================
    def create_eld_device(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", "/eld-devices", payload, headers)

    def get_eld_device(self, device_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/eld-devices/{device_id}", headers=headers,
        )

    # ======================================================================
    # Vehicles — PRD §3.1
    # ======================================================================
    def create_vehicle(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/vehicles/{vehicle_id}", headers=headers,
        )

    # ======================================================================
    # Drivers — PRD §3.1, §3.2
    # ======================================================================
    def create_driver(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/drivers", payload, headers)

    def get_driver(self, driver_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/drivers/{driver_id}", headers=headers,
        )

    def bind_driver(self, driver_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/drivers/{driver_id}/bind", payload, headers,
        )

    def unbind_driver(self, driver_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/drivers/{driver_id}/unbind",
            payload, headers,
        )

    # ======================================================================
    # Duty events — PRD §3.3, §3.5
    # ======================================================================
    def create_duty_event(self, driver_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/drivers/{driver_id}/duty-events",
            payload, headers,
        )

    def list_duty_events(self, driver_id: str, headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/drivers/{driver_id}/duty-events",
            headers=headers, params=params,
        )

    def edit_duty_event(self, driver_id: str, event_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/drivers/{driver_id}/duty-events/{event_id}/edit",
            payload, headers,
        )

    # ======================================================================
    # HOS snapshot — PRD §3.9
    # ======================================================================
    def get_hos_snapshot(self, driver_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/drivers/{driver_id}/hos-snapshot", headers=headers,
        )

    # ======================================================================
    # Daily logs — PRD §3.7
    # ======================================================================
    def list_daily_logs(self, driver_id: str, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/drivers/{driver_id}/daily-logs",
            headers=headers, params=params,
        )

    def get_daily_log(self, driver_id: str, log_id: str,
                      headers: Dict[str, str]):
        return self._request(
            "GET", f"/drivers/{driver_id}/daily-logs/{log_id}",
            headers=headers,
        )

    def certify_daily_log(self, driver_id: str, log_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/drivers/{driver_id}/daily-logs/{log_id}/certify",
            payload, headers,
        )

    # ======================================================================
    # Violations — PRD §3.8
    # ======================================================================
    def list_violations(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/violations", headers=headers, params=params,
        )

    def get_violation(self, violation_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/violations/{violation_id}", headers=headers,
        )

    def acknowledge_violation(self, violation_id: str,
                              headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/violations/{violation_id}/acknowledge",
            payload, headers,
        )

    def report_violation_to_fmcsa(self, violation_id: str,
                                  headers: Dict[str, str],
                                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/violations/{violation_id}/report-to-fmcsa",
            payload, headers,
        )

    # ======================================================================
    # Adverse Conditions — PRD §3.6
    # ======================================================================
    def create_adverse_conditions(self, driver_id: str,
                                  payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request(
            "POST", f"/drivers/{driver_id}/adverse-conditions",
            payload, headers,
        )

    def list_adverse_conditions(self, driver_id: str,
                                headers: Dict[str, str],
                                params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/drivers/{driver_id}/adverse-conditions",
            headers=headers, params=params,
        )

    # ======================================================================
    # Test clock — PRD §3.10
    # ======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/advance", payload, headers,
        )

    def get_clock(self, headers: Dict[str, str]):
        return self._request("GET", "/_clock", headers=headers)


# Module-level singleton used by tests + fixtures.
api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
