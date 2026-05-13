"""API client: one method per endpoint defined in PRD §4.

Each method delegates to GenericApiClient._request and returns the raw
Response. Headers are passed explicitly because PRD §2.1 requires
X-User-ID and X-User-Role on every request.
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Routes (PRD §3.2, §4)
    # =======================================================================
    def create_route(self, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request("POST", "/shuttle/routes", payload, headers)

    def get_route(self, route_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/shuttle/routes/{route_id}", headers=headers,
        )

    def list_routes(self, headers: Dict[str, str],
                    params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/shuttle/routes", headers=headers, params=params,
        )

    def update_route(self, route_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/shuttle/routes/{route_id}", payload, headers,
        )

    def publish_route(self, route_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/shuttle/routes/{route_id}/publish",
            payload or {}, headers,
        )

    def retire_route(self, route_id: str, headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/shuttle/routes/{route_id}/retire",
            payload or {}, headers,
        )

    def list_route_versions(self, route_id: str, headers: Dict[str, str],
                            params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/shuttle/routes/{route_id}/versions",
            headers=headers, params=params,
        )

    # =======================================================================
    # Stops (PRD §3.1, §4)
    # =======================================================================
    def create_stop(self, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request("POST", "/shuttle/stops", payload, headers)

    def list_stops(self, headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/shuttle/stops", headers=headers, params=params,
        )

    def activate_stop(self, stop_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/shuttle/stops/{stop_id}/activate",
            payload or {}, headers,
        )

    def offshelf_stop(self, stop_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/shuttle/stops/{stop_id}/offshelf",
            payload or {}, headers,
        )

    # =======================================================================
    # Vehicles (PRD §3.3, §4)
    # =======================================================================
    def create_vehicle(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/shuttle/vehicles", payload, headers)

    def list_vehicles(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/shuttle/vehicles", headers=headers, params=params,
        )

    def start_vehicle_maintenance(self, vehicle_id: str,
                                  payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request(
            "POST", f"/shuttle/vehicles/{vehicle_id}/maintenance",
            payload, headers,
        )

    def complete_vehicle_maintenance(self, vehicle_id: str,
                                     headers: Dict[str, str],
                                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/shuttle/vehicles/{vehicle_id}/maintenance-complete",
            payload or {}, headers,
        )

    # =======================================================================
    # Drivers (PRD §3.3, §4)
    # =======================================================================
    def create_driver(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/shuttle/drivers", payload, headers)

    def list_drivers(self, headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/shuttle/drivers", headers=headers, params=params,
        )

    # =======================================================================
    # Run sheets (PRD §3.4, §3.5, §4)
    # =======================================================================
    def create_run_sheet(self, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", "/shuttle/run-sheets", payload, headers,
        )

    def list_run_sheets(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/shuttle/run-sheets", headers=headers, params=params,
        )

    def get_run_sheet(self, run_sheet_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/shuttle/run-sheets/{run_sheet_id}", headers=headers,
        )

    def start_boarding(self, run_sheet_id: str, headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/shuttle/run-sheets/{run_sheet_id}/start-boarding",
            payload or {}, headers,
        )

    def depart_run_sheet(self, run_sheet_id: str, headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/shuttle/run-sheets/{run_sheet_id}/depart",
            payload or {}, headers,
        )

    def complete_run_sheet(self, run_sheet_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/shuttle/run-sheets/{run_sheet_id}/complete",
            payload or {}, headers,
        )

    def cancel_run_sheet(self, run_sheet_id: str, headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/shuttle/run-sheets/{run_sheet_id}/cancel",
            payload or {}, headers,
        )

    def report_delay(self, run_sheet_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/shuttle/run-sheets/{run_sheet_id}/delays",
            payload, headers,
        )

    def resume_run_sheet(self, run_sheet_id: str, headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/shuttle/run-sheets/{run_sheet_id}/resume",
            payload or {}, headers,
        )

    def dispatch_substitute(self, run_sheet_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/shuttle/run-sheets/{run_sheet_id}/dispatch-substitute",
            payload, headers,
        )

    def get_run_sheet_statistics(self, run_sheet_id: str,
                                 headers: Dict[str, str]):
        return self._request(
            "GET", f"/shuttle/run-sheets/{run_sheet_id}/statistics",
            headers=headers,
        )

    # =======================================================================
    # Reservations (PRD §3.6, §4)
    # =======================================================================
    def create_reservation(self, run_sheet_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/shuttle/run-sheets/{run_sheet_id}/reservations",
            payload, headers,
        )

    def list_reservations(self, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/shuttle/reservations",
            headers=headers, params=params,
        )

    def get_reservation(self, reservation_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "GET", f"/shuttle/reservations/{reservation_id}",
            headers=headers,
        )

    def cancel_reservation(self, reservation_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "DELETE", f"/shuttle/reservations/{reservation_id}",
            payload or None, headers,
        )

    # =======================================================================
    # Check-in / Ridership (PRD §3.6, §4)
    # =======================================================================
    def check_in(self, run_sheet_id: str, payload: Dict[str, Any],
                 headers: Dict[str, str]):
        return self._request(
            "POST", f"/shuttle/run-sheets/{run_sheet_id}/check-in",
            payload, headers,
        )

    def update_ridership(self, ridership_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/shuttle/ridership/{ridership_id}", payload, headers,
        )

    # =======================================================================
    # Bills (PRD §3.8, §4)
    # =======================================================================
    def create_bill(self, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request("POST", "/shuttle/bills", payload, headers)

    def finalize_bill(self, bill_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/shuttle/bills/{bill_id}/finalize",
            payload or {}, headers,
        )

    def settle_bill(self, bill_id: str, headers: Dict[str, str],
                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/shuttle/bills/{bill_id}/settle",
            payload or {}, headers,
        )

    def list_bills(self, headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/shuttle/bills", headers=headers, params=params,
        )

    # =======================================================================
    # Audit logs (PRD §2.11, §4)
    # =======================================================================
    def list_audit_logs(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/shuttle/audit-logs", headers=headers, params=params,
        )

    # =======================================================================
    # Test-driving clock (PRD §2.12, §4)
    # =======================================================================
    def advance_clock(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/shuttle/_clock/advance", payload, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
