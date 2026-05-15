"""API client: one method per endpoint defined in PRD §4.

Each method delegates to GenericApiClient._request and returns the raw
Response object. Tests pass headers explicitly because PRD §2.1 requires
X-User-ID and X-User-Role on every call.
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Rooms (PRD §3.1, §3.9, §3.10)
    # =======================================================================
    def create_room(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/rooms", payload, headers)

    def list_rooms(
        self,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request("GET", "/rooms", headers=headers, params=params)

    def get_room(self, room_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/rooms/{room_id}", headers=headers)

    def correct_room_status(
        self,
        room_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/rooms/{room_id}/correct-status", payload, headers,
        )

    def list_room_status_events(
        self,
        room_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"/rooms/{room_id}/status-events",
            headers=headers, params=params,
        )

    # =======================================================================
    # Housekeepers (PRD §3.6)
    # =======================================================================
    def create_housekeeper(
        self, payload: Dict[str, Any], headers: Dict[str, str],
    ):
        return self._request("POST", "/housekeepers", payload, headers)

    def list_housekeepers(
        self,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", "/housekeepers", headers=headers, params=params,
        )

    def get_housekeeper(
        self, housekeeper_id: str, headers: Dict[str, str],
    ):
        return self._request(
            "GET", f"/housekeepers/{housekeeper_id}", headers=headers,
        )

    def toggle_housekeeper_shift(
        self,
        housekeeper_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/housekeepers/{housekeeper_id}/shift",
            payload, headers,
        )

    # =======================================================================
    # Cleaning Tasks (PRD §3.3, §3.5)
    # =======================================================================
    def create_cleaning_task(
        self, payload: Dict[str, Any], headers: Dict[str, str],
    ):
        return self._request("POST", "/cleaning-tasks", payload, headers)

    def list_cleaning_tasks(
        self,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", "/cleaning-tasks", headers=headers, params=params,
        )

    def get_cleaning_task(self, task_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/cleaning-tasks/{task_id}", headers=headers,
        )

    def patch_cleaning_task(
        self,
        task_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "PATCH", f"/cleaning-tasks/{task_id}", payload, headers,
        )

    def dispatch_cleaning_task(
        self, task_id: str, headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/cleaning-tasks/{task_id}/dispatch", {}, headers,
        )

    def accept_cleaning_task(
        self, task_id: str, headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/cleaning-tasks/{task_id}/accept", {}, headers,
        )

    def reassign_cleaning_task(
        self,
        task_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/cleaning-tasks/{task_id}/reassign", payload, headers,
        )

    def start_cleaning_task(
        self, task_id: str, headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/cleaning-tasks/{task_id}/start", {}, headers,
        )

    def submit_cleaning_task(
        self, task_id: str, headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/cleaning-tasks/{task_id}/submit", {}, headers,
        )

    def inspect_cleaning_task(
        self,
        task_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/cleaning-tasks/{task_id}/inspect", payload, headers,
        )

    def get_inspection_record(
        self, task_id: str, headers: Dict[str, str],
    ):
        return self._request(
            "GET", f"/cleaning-tasks/{task_id}/inspection", headers=headers,
        )

    # =======================================================================
    # Maintenance Tickets (PRD §3.7)
    # =======================================================================
    def create_maintenance_ticket(
        self, payload: Dict[str, Any], headers: Dict[str, str],
    ):
        return self._request(
            "POST", "/maintenance-tickets", payload, headers,
        )

    def list_maintenance_tickets(
        self,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", "/maintenance-tickets", headers=headers, params=params,
        )

    def get_maintenance_ticket(
        self, ticket_id: str, headers: Dict[str, str],
    ):
        return self._request(
            "GET", f"/maintenance-tickets/{ticket_id}", headers=headers,
        )

    def dispatch_maintenance_ticket(
        self,
        ticket_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/maintenance-tickets/{ticket_id}/dispatch",
            payload, headers,
        )

    def verify_maintenance_ticket(
        self, ticket_id: str, headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/maintenance-tickets/{ticket_id}/verify", {}, headers,
        )

    def reject_maintenance_ticket(
        self, ticket_id: str, headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/maintenance-tickets/{ticket_id}/reject", {}, headers,
        )

    # =======================================================================
    # Minibar Items / Consumptions (PRD §3.11)
    # =======================================================================
    def create_minibar_item(
        self, payload: Dict[str, Any], headers: Dict[str, str],
    ):
        return self._request("POST", "/minibar-items", payload, headers)

    def list_minibar_items(
        self,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", "/minibar-items", headers=headers, params=params,
        )

    def archive_minibar_item(
        self, item_id: str, headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/minibar-items/{item_id}/archive", {}, headers,
        )

    def create_minibar_consumption(
        self, payload: Dict[str, Any], headers: Dict[str, str],
    ):
        return self._request(
            "POST", "/minibar-consumptions", payload, headers,
        )

    def list_minibar_consumptions(
        self,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", "/minibar-consumptions", headers=headers, params=params,
        )

    def get_minibar_consumption(
        self, consumption_id: str, headers: Dict[str, str],
    ):
        return self._request(
            "GET", f"/minibar-consumptions/{consumption_id}",
            headers=headers,
        )

    def post_minibar_consumption(
        self, consumption_id: str, headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/minibar-consumptions/{consumption_id}/post",
            {}, headers,
        )

    def dispute_minibar_consumption(
        self,
        consumption_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/minibar-consumptions/{consumption_id}/dispute",
            payload, headers,
        )

    def investigate_minibar_consumption(
        self,
        consumption_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/minibar-consumptions/{consumption_id}/investigate",
            payload, headers,
        )

    def resolve_minibar_consumption(
        self,
        consumption_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/minibar-consumptions/{consumption_id}/resolve",
            payload, headers,
        )

    # =======================================================================
    # Linen Types / Movements (PRD §3.12)
    # =======================================================================
    def create_linen_type(
        self, payload: Dict[str, Any], headers: Dict[str, str],
    ):
        return self._request("POST", "/linen-types", payload, headers)

    def list_linen_types(
        self,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", "/linen-types", headers=headers, params=params,
        )

    def create_linen_movement(
        self, payload: Dict[str, Any], headers: Dict[str, str],
    ):
        return self._request("POST", "/linen-movements", payload, headers)

    def list_linen_movements(
        self,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", "/linen-movements", headers=headers, params=params,
        )

    def handover_laundry(
        self, movement_id: str, headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/linen-movements/{movement_id}/handover-laundry",
            {}, headers,
        )

    def resolve_linen_loss_damage(
        self, movement_id: str, headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/linen-movements/{movement_id}/resolve-loss-damage",
            {}, headers,
        )

    # =======================================================================
    # Audit Logs (PRD §3.13)
    # =======================================================================
    def list_audit_logs(
        self,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", "/audit-logs", headers=headers, params=params,
        )

    # =======================================================================
    # Inbound events / test clock (PRD §3.2, §3.7, §3.12, §2.11)
    # =======================================================================
    def pms_sync_event(
        self, payload: Dict[str, Any], headers: Dict[str, str],
    ):
        return self._request(
            "POST", "/_events/pms-sync", payload, headers,
        )

    def engineering_update_event(
        self, payload: Dict[str, Any], headers: Dict[str, str],
    ):
        return self._request(
            "POST", "/_events/engineering-update", payload, headers,
        )

    def laundry_return_event(
        self, payload: Dict[str, Any], headers: Dict[str, str],
    ):
        return self._request(
            "POST", "/_events/laundry-return", payload, headers,
        )

    def clock_advance(
        self, payload: Dict[str, Any], headers: Dict[str, str],
    ):
        return self._request(
            "POST", "/_clock/advance", payload, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
