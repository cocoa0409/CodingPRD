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
    # Test-harness clock and event hooks (PRD §3.8)
    # =======================================================================
    def advance_clock(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload, headers)

    def deliver_payment_confirmed(self, payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request(
            "POST", "/_events/payment-confirmed", payload, headers,
        )

    def deliver_identity_verified(self, payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request(
            "POST", "/_events/identity-verified", payload, headers,
        )

    def deliver_im_notified(self, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", "/_events/im-notified", payload, headers,
        )

    # =======================================================================
    # Labs (PRD §3.1, §3.8, §4)
    # =======================================================================
    def create_lab(self, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request("POST", "/labs", payload, headers)

    def get_lab(self, lab_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/labs/{lab_id}", headers=headers,
        )

    def settle_lab(self, lab_id: str, headers: Dict[str, str],
                   payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/labs/{lab_id}/settle",
            payload or {}, headers,
        )

    # =======================================================================
    # Users (PRD §3.1, §4)
    # =======================================================================
    def create_user(self, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request("POST", "/users", payload, headers)

    def get_user(self, user_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/users/{user_id}", headers=headers,
        )

    # =======================================================================
    # Equipment (PRD §3.1, §4)
    # =======================================================================
    def create_equipment(self, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", "/equipment", payload, headers)

    def get_equipment(self, equipment_id: str,
                      headers: Dict[str, str]):
        return self._request(
            "GET", f"/equipment/{equipment_id}", headers=headers,
        )

    def list_equipment(self, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/equipment", headers=headers, params=params,
        )

    def update_equipment(self, equipment_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "PUT", f"/equipment/{equipment_id}", payload, headers,
        )

    # =======================================================================
    # Billing rules (PRD §3.5, §4)
    # =======================================================================
    def create_billing_rule(self, equipment_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/equipment/{equipment_id}/billing-rules",
            payload, headers,
        )

    def list_billing_rules(self, equipment_id: str,
                           headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/equipment/{equipment_id}/billing-rules",
            headers=headers, params=params,
        )

    def publish_billing_rule(self, equipment_id: str, rule_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/equipment/{equipment_id}/billing-rules/{rule_id}/publish",
            payload or {}, headers,
        )

    # =======================================================================
    # Maintenance windows (PRD §3.7, §4)
    # =======================================================================
    def create_maintenance_window(self, equipment_id: str,
                                  payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/equipment/{equipment_id}/maintenance-windows",
            payload, headers,
        )

    def accept_maintenance_window(self, window_id: str,
                                  headers: Dict[str, str],
                                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/maintenance-windows/{window_id}/accept",
            payload or {}, headers,
        )

    def reject_maintenance_window(self, window_id: str,
                                  headers: Dict[str, str],
                                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/maintenance-windows/{window_id}/reject",
            payload or {}, headers,
        )

    # =======================================================================
    # Authorizations (PRD §3.2, §4)
    # =======================================================================
    def create_authorization(self, equipment_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/equipment/{equipment_id}/authorizations",
            payload, headers,
        )

    def approve_authorization(self, authorization_id: str,
                              headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/authorizations/{authorization_id}/approve",
            payload or {}, headers,
        )

    def reject_authorization(self, authorization_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/authorizations/{authorization_id}/reject",
            payload or {}, headers,
        )

    def revoke_authorization(self, authorization_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/authorizations/{authorization_id}/revoke",
            payload or {}, headers,
        )

    # =======================================================================
    # Reservations (PRD §3.3, §3.6, §4)
    # =======================================================================
    def create_reservation(self, equipment_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/equipment/{equipment_id}/reservations",
            payload, headers,
        )

    def get_reservation(self, reservation_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "GET", f"/reservations/{reservation_id}", headers=headers,
        )

    def list_reservations(self, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/reservations", headers=headers, params=params,
        )

    def check_in_reservation(self, reservation_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/reservations/{reservation_id}/check-in",
            payload or {}, headers,
        )

    def check_out_reservation(self, reservation_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/reservations/{reservation_id}/check-out",
            payload, headers,
        )

    def cancel_reservation(self, reservation_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/reservations/{reservation_id}/cancel",
            payload or {}, headers,
        )

    # =======================================================================
    # Audit events (PRD §2.8, §4)
    # =======================================================================
    def list_audit_events(self, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/audit-events", headers=headers, params=params,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
