"""API client: one method per endpoint defined in PRD section 4.

Each method returns the raw Response object. Headers are passed
explicitly because PRD section 2.1 requires X-User-ID/X-User-Role on
every call.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # =====================================================================
    # Fleet
    # =====================================================================
    def create_fleet(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/fleets", payload, headers)

    def get_fleet(self, fleet_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/fleets/{fleet_id}", headers=headers
        )

    def advance_clock(
        self,
        fleet_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/fleets/{fleet_id}:advance_clock", payload, headers
        )

    def dispatch(
        self,
        fleet_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/dispatch",
            payload if payload is not None else {},
            headers,
        )

    def get_metrics(
        self,
        fleet_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET",
            f"/fleets/{fleet_id}/metrics",
            headers=headers,
            params=params,
        )

    # =====================================================================
    # Map
    # =====================================================================
    def create_map_node(
        self,
        fleet_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/fleets/{fleet_id}/map_nodes", payload, headers
        )

    def create_map_edge(
        self,
        fleet_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/fleets/{fleet_id}/map_edges", payload, headers
        )

    def emit_event(
        self,
        fleet_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/fleets/{fleet_id}/events:emit", payload, headers
        )

    # =====================================================================
    # Charging Station
    # =====================================================================
    def create_charging_station(
        self,
        fleet_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/charging_stations",
            payload,
            headers,
        )

    def get_charging_station(
        self,
        fleet_id: str,
        station_id: str,
        headers: Dict[str, str],
    ):
        return self._request(
            "GET",
            f"/fleets/{fleet_id}/charging_stations/{station_id}",
            headers=headers,
        )

    # =====================================================================
    # Robot
    # =====================================================================
    def create_robot(
        self,
        fleet_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/fleets/{fleet_id}/robots", payload, headers
        )

    def get_robot(
        self,
        fleet_id: str,
        robot_id: str,
        headers: Dict[str, str],
    ):
        return self._request(
            "GET",
            f"/fleets/{fleet_id}/robots/{robot_id}",
            headers=headers,
        )

    def list_robots(
        self,
        fleet_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET",
            f"/fleets/{fleet_id}/robots",
            headers=headers,
            params=params,
        )

    def heartbeat_robot(
        self,
        fleet_id: str,
        robot_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/robots/{robot_id}:heartbeat",
            payload if payload is not None else {},
            headers,
        )

    def step_robot(
        self,
        fleet_id: str,
        robot_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/robots/{robot_id}:step",
            payload if payload is not None else {},
            headers,
        )

    def dock_robot(
        self,
        fleet_id: str,
        robot_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/robots/{robot_id}:dock",
            payload if payload is not None else {},
            headers,
        )

    def undock_robot(
        self,
        fleet_id: str,
        robot_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/robots/{robot_id}:undock",
            payload if payload is not None else {},
            headers,
        )

    def queue_charger(
        self,
        fleet_id: str,
        robot_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/robots/{robot_id}:queue_charger",
            payload,
            headers,
        )

    def list_trajectory(
        self,
        fleet_id: str,
        robot_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET",
            f"/fleets/{fleet_id}/robots/{robot_id}/trajectory",
            headers=headers,
            params=params,
        )

    # =====================================================================
    # Task
    # =====================================================================
    def create_task(
        self,
        fleet_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/fleets/{fleet_id}/tasks", payload, headers
        )

    def get_task(
        self,
        fleet_id: str,
        task_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET",
            f"/fleets/{fleet_id}/tasks/{task_id}",
            headers=headers,
            params=params,
        )

    def list_tasks(
        self,
        fleet_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET",
            f"/fleets/{fleet_id}/tasks",
            headers=headers,
            params=params,
        )

    def assign_task(
        self,
        fleet_id: str,
        task_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/tasks/{task_id}:assign",
            payload,
            headers,
        )

    def start_task(
        self,
        fleet_id: str,
        task_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/tasks/{task_id}:start",
            payload if payload is not None else {},
            headers,
        )

    def complete_task(
        self,
        fleet_id: str,
        task_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/tasks/{task_id}:complete",
            payload if payload is not None else {},
            headers,
        )

    def cancel_task(
        self,
        fleet_id: str,
        task_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/tasks/{task_id}:cancel",
            payload if payload is not None else {},
            headers,
        )

    def split_task(
        self,
        fleet_id: str,
        task_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/tasks/{task_id}:split",
            payload if payload is not None else {},
            headers,
        )

    def merge_tasks(
        self,
        fleet_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/fleets/{fleet_id}/tasks:merge", payload, headers
        )

    # =====================================================================
    # Slot Reservations
    # =====================================================================
    def create_slot_reservation(
        self,
        fleet_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/slot_reservations",
            payload,
            headers,
        )

    def list_slot_reservations(
        self,
        fleet_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET",
            f"/fleets/{fleet_id}/slot_reservations",
            headers=headers,
            params=params,
        )

    # =====================================================================
    # Fault Incidents
    # =====================================================================
    def open_fault(
        self,
        fleet_id: str,
        robot_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/robots/{robot_id}/faults",
            payload,
            headers,
        )

    def get_fault_incident(
        self,
        fleet_id: str,
        incident_id: str,
        headers: Dict[str, str],
    ):
        return self._request(
            "GET",
            f"/fleets/{fleet_id}/fault_incidents/{incident_id}",
            headers=headers,
        )

    def takeover_fault(
        self,
        fleet_id: str,
        incident_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/fault_incidents/{incident_id}:takeover",
            payload if payload is not None else {},
            headers,
        )

    def resolve_fault(
        self,
        fleet_id: str,
        incident_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/fault_incidents/{incident_id}:resolve",
            payload if payload is not None else {},
            headers,
        )

    # =====================================================================
    # Audit
    # =====================================================================
    def list_audit_events(
        self,
        fleet_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET",
            f"/fleets/{fleet_id}/audit_events",
            headers=headers,
            params=params,
        )

    # =====================================================================
    # Charging Sessions
    # =====================================================================
    def cancel_charging_session(
        self,
        fleet_id: str,
        session_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/charging_sessions/{session_id}:cancel",
            payload if payload is not None else {},
            headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
