"""API client: one method per endpoint defined in the PRD §4.

Every method delegates to GenericApiClient._request and returns the raw
Response. Tests pass headers explicitly because PRD §2.1 makes
X-User-ID / X-User-Role mandatory for every call (except /healthz).
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # =====================================================================
    # Lots / Zones / Spaces
    # =====================================================================
    def create_lot(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/lots", payload, headers)

    def get_lot(self, lot_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/lots/{lot_id}", headers=headers)

    def create_zone(self, lot_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request("POST", f"/lots/{lot_id}/zones", payload, headers)

    def get_availability(self, lot_id: str, headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/lots/{lot_id}/availability", headers=headers, params=params
        )

    def create_space(self, lot_id: str, zone_id: str,
                     payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/lots/{lot_id}/zones/{zone_id}/spaces", payload, headers
        )

    def get_space(self, lot_id: str, zone_id: str, space_id: str,
                  headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/lots/{lot_id}/zones/{zone_id}/spaces/{space_id}",
            headers=headers,
        )

    # =====================================================================
    # Vehicles
    # =====================================================================
    def create_vehicle(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/vehicles/{vehicle_id}", headers=headers)

    # =====================================================================
    # Cards
    # =====================================================================
    def create_card(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/cards", payload, headers)

    def get_card(self, card_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/cards/{card_id}", headers=headers)

    def recharge_card(self, card_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/cards/{card_id}/recharge", payload, headers
        )

    def bind_card(self, card_id: str, payload: Dict[str, Any],
                  headers: Dict[str, str]):
        return self._request(
            "POST", f"/cards/{card_id}/bind", payload, headers
        )

    def unbind_card(self, card_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/cards/{card_id}/unbind", payload, headers
        )

    def suspend_card(self, card_id: str, headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/cards/{card_id}/suspend", payload or {}, headers
        )

    def reactivate_card(self, card_id: str, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/cards/{card_id}/reactivate", payload or {}, headers
        )

    def transfer_card(self, card_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/cards/{card_id}/transfer", payload, headers
        )

    # =====================================================================
    # Reservations
    # =====================================================================
    def create_reservation(self, lot_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/lots/{lot_id}/reservations", payload, headers
        )

    def get_reservation(self, reservation_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "GET", f"/reservations/{reservation_id}", headers=headers
        )

    def patch_reservation(self, reservation_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/reservations/{reservation_id}", payload, headers
        )

    def cancel_reservation(self, reservation_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/reservations/{reservation_id}/cancel",
            payload or {},
            headers,
        )

    # =====================================================================
    # Sessions
    # =====================================================================
    def create_session(self, lot_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/lots/{lot_id}/sessions", payload, headers
        )

    def get_session(self, session_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/sessions/{session_id}", headers=headers
        )

    def exit_session(self, session_id: str, headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/sessions/{session_id}/exit", payload or {}, headers
        )

    def pay_session(self, session_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/sessions/{session_id}/pay", payload, headers
        )

    def waive_session(self, session_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/sessions/{session_id}/waive", payload, headers
        )

    # =====================================================================
    # Violations / Fines
    # =====================================================================
    def create_violation(self, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", "/violations", payload, headers)

    def get_violation(self, violation_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/violations/{violation_id}", headers=headers
        )

    def patch_violation(self, violation_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/violations/{violation_id}", payload, headers
        )

    def pay_violation(self, violation_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/violations/{violation_id}/pay", payload, headers
        )

    def tow_violation(self, violation_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/violations/{violation_id}/tow", payload, headers
        )

    # =====================================================================
    # Payments / Refunds
    # =====================================================================
    def refund_payment(self, payment_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/payments/{payment_id}/refund", payload, headers
        )

    # =====================================================================
    # Revenue / Settlement
    # =====================================================================
    def get_revenue(self, lot_id: str, headers: Dict[str, str],
                    params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/lots/{lot_id}/revenue", headers=headers, params=params
        )

    def run_settlement(self, lot_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/lots/{lot_id}/settlement/run", payload, headers
        )

    # =====================================================================
    # Audit
    # =====================================================================
    def list_audit_logs(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/audit-logs", headers=headers, params=params
        )

    # =====================================================================
    # Test-driving endpoints
    # =====================================================================
    def advance_clock(self, to_iso: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/advance", {"to": to_iso}, headers
        )

    def run_sweep(self, headers: Dict[str, str]):
        return self._request("POST", "/_sweep/run", {}, headers)

    def emit_event(self, event_kind: str, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request(
            "POST",
            "/_events/emit",
            {"event_kind": event_kind, "payload": payload},
            headers,
        )


api_client = ApiClient()
