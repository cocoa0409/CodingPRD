"""API client: one method per endpoint defined in the PRD §4.

Every method delegates to GenericApiClient._request and returns the raw
Response. Tests pass headers explicitly because PRD §2.1 makes
X-User-ID / X-User-Role mandatory for every request (except GET /_health).
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # =====================================================================
    # RoomType
    # =====================================================================
    def create_room_type(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/hotel/room-types", payload, headers)

    def list_room_types(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/hotel/room-types", headers=headers,
                             params=params)

    def get_room_type(self, room_type_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/hotel/room-types/{room_type_id}",
                             headers=headers)

    # =====================================================================
    # Room
    # =====================================================================
    def create_room(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/hotel/rooms", payload, headers)

    def list_rooms(self, headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/hotel/rooms", headers=headers,
                             params=params)

    def clean_room(self, room_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/hotel/rooms/{room_id}/clean",
                             headers=headers)

    def out_of_service_room(self, room_id: str, headers: Dict[str, str]):
        return self._request("POST",
                             f"/hotel/rooms/{room_id}/out-of-service",
                             headers=headers)

    def return_to_service_room(self, room_id: str, headers: Dict[str, str]):
        return self._request("POST",
                             f"/hotel/rooms/{room_id}/return-to-service",
                             headers=headers)

    # =====================================================================
    # MaintenanceBlock
    # =====================================================================
    def create_maintenance_block(self, payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request("POST", "/hotel/maintenance-blocks", payload,
                             headers)

    def release_maintenance_block(self, block_id: str,
                                  headers: Dict[str, str]):
        return self._request(
            "POST", f"/hotel/maintenance-blocks/{block_id}/release",
            headers=headers,
        )

    def cancel_maintenance_block(self, block_id: str,
                                 headers: Dict[str, str]):
        return self._request(
            "POST", f"/hotel/maintenance-blocks/{block_id}/cancel",
            headers=headers,
        )

    # =====================================================================
    # Channel
    # =====================================================================
    def create_channel(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/hotel/channels", payload, headers)

    def list_channels(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/hotel/channels", headers=headers,
                             params=params)

    # =====================================================================
    # RatePlan
    # =====================================================================
    def create_rate_plan(self, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", "/hotel/rate-plans", payload, headers)

    # =====================================================================
    # ChannelRatePlanMapping
    # =====================================================================
    def create_channel_rate_plan_mapping(self, payload: Dict[str, Any],
                                         headers: Dict[str, str]):
        return self._request("POST", "/hotel/channel-rate-plan-mappings",
                             payload, headers)

    # =====================================================================
    # RateOverride
    # =====================================================================
    def create_rate_override(self, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request("POST", "/hotel/rate-overrides", payload,
                             headers)

    def submit_rate_override(self, override_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/hotel/rate-overrides/{override_id}/submit",
            headers=headers,
        )

    def approve_rate_override(self, override_id: str,
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/hotel/rate-overrides/{override_id}/approve",
            headers=headers,
        )

    def reject_rate_override(self, override_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/hotel/rate-overrides/{override_id}/reject",
            headers=headers,
        )

    def withdraw_rate_override(self, override_id: str,
                               headers: Dict[str, str]):
        return self._request(
            "POST", f"/hotel/rate-overrides/{override_id}/withdraw",
            headers=headers,
        )

    # =====================================================================
    # OverbookingPolicy
    # =====================================================================
    def create_overbooking_policy(self, payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request("POST", "/hotel/overbooking-policies", payload,
                             headers)

    def get_walkout_cost_estimate(self, room_type_id: str, stay_date: str,
                                  headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/hotel/overbooking-policies/{room_type_id}/{stay_date}/walkout-cost-estimate",
            headers=headers,
        )

    # =====================================================================
    # Reservation
    # =====================================================================
    def create_reservation(self, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request("POST", "/hotel/reservations", payload, headers)

    def list_reservations(self, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/hotel/reservations", headers=headers,
                             params=params)

    def get_reservation(self, reservation_id: str, headers: Dict[str, str]):
        return self._request("GET",
                             f"/hotel/reservations/{reservation_id}",
                             headers=headers)

    def confirm_reservation(self, reservation_id: str,
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/hotel/reservations/{reservation_id}/confirm",
            headers=headers,
        )

    def modify_reservation(self, reservation_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/hotel/reservations/{reservation_id}/modify",
            payload, headers,
        )

    def cancel_reservation(self, reservation_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/hotel/reservations/{reservation_id}/cancel",
            headers=headers,
        )

    def check_in_reservation(self, reservation_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/hotel/reservations/{reservation_id}/check-in",
            payload, headers,
        )

    def check_out_reservation(self, reservation_id: str,
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/hotel/reservations/{reservation_id}/check-out",
            headers=headers,
        )

    def walk_out_reservation(self, reservation_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/hotel/reservations/{reservation_id}/walk-out",
            headers=headers,
        )

    def open_dispute(self, reservation_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/hotel/reservations/{reservation_id}/dispute",
            headers=headers,
        )

    def resolve_dispute(self, reservation_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/hotel/reservations/{reservation_id}/resolve-dispute",
            payload, headers,
        )

    # =====================================================================
    # AuditLog
    # =====================================================================
    def list_audit_logs(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/hotel/audit-logs", headers=headers,
                             params=params)

    # =====================================================================
    # Logical clock (test-driving system endpoints)
    # =====================================================================
    def advance_clock(self, new_now: str, headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance",
                             {"new_now": new_now}, headers)

    def get_clock(self, headers: Dict[str, str]):
        return self._request("GET", "/_clock", headers=headers)


# Single shared instance — base URL is provided by the runner via env.
api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
