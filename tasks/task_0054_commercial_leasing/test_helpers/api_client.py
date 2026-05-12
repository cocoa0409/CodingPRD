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
    # Buildings (PRD §3.1, §4)
    # =======================================================================
    def create_building(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/buildings", payload, headers)

    def get_building(self, building_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/buildings/{building_id}", headers=headers,
        )

    # =======================================================================
    # Units (PRD §3.1, §4)
    # =======================================================================
    def create_unit(self, building_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/buildings/{building_id}/units", payload, headers,
        )

    def get_unit(self, building_id: str, unit_id: str,
                 headers: Dict[str, str]):
        return self._request(
            "GET", f"/buildings/{building_id}/units/{unit_id}",
            headers=headers,
        )

    def reserve_unit(self, building_id: str, unit_id: str,
                     payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/buildings/{building_id}/units/{unit_id}/reserve",
            payload, headers,
        )

    def release_reservation(self, building_id: str, unit_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/buildings/{building_id}/units/{unit_id}/release-reservation",
            payload or {}, headers,
        )

    def start_renovation(self, building_id: str, unit_id: str,
                         payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/buildings/{building_id}/units/{unit_id}/start-renovation",
            payload, headers,
        )

    def finish_renovation(self, building_id: str, unit_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/buildings/{building_id}/units/{unit_id}/finish-renovation",
            payload or {}, headers,
        )

    def split_unit(self, building_id: str, unit_id: str,
                   payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/buildings/{building_id}/units/{unit_id}/split",
            payload, headers,
        )

    def merge_units(self, building_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/buildings/{building_id}/units/merge",
            payload, headers,
        )

    # =======================================================================
    # Tenants (PRD §3.2, §4)
    # =======================================================================
    def create_tenant(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/tenants", payload, headers)

    def approve_tenant(self, tenant_id: str,
                       headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/tenants/{tenant_id}/approve",
            payload or {}, headers,
        )

    def reject_tenant(self, tenant_id: str,
                      headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/tenants/{tenant_id}/reject",
            payload or {}, headers,
        )

    def revoke_tenant_approval(self, tenant_id: str,
                               headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/tenants/{tenant_id}/revoke-approval",
            payload or {}, headers,
        )

    def get_tenant(self, tenant_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/tenants/{tenant_id}", headers=headers,
        )

    # =======================================================================
    # Leases (PRD §3.3, §3.5, §4)
    # =======================================================================
    def create_lease(self, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request("POST", "/leases", payload, headers)

    def get_lease(self, lease_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/leases/{lease_id}", headers=headers,
        )

    def get_rent_schedule(self, lease_id: str, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/leases/{lease_id}/rent-schedule",
            headers=headers, params=params,
        )

    def sign_lease(self, lease_id: str, headers: Dict[str, str],
                   payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/leases/{lease_id}/sign",
            payload or {}, headers,
        )

    def activate_lease(self, lease_id: str, headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/leases/{lease_id}/activate",
            payload or {}, headers,
        )

    def amend_lease(self, lease_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/leases/{lease_id}/amend", payload, headers,
        )

    def amend_confirm_lease(self, lease_id: str, headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/leases/{lease_id}/amend-confirm",
            payload or {}, headers,
        )

    def amend_cancel_lease(self, lease_id: str, headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/leases/{lease_id}/amend-cancel",
            payload or {}, headers,
        )

    def renew_lease(self, lease_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/leases/{lease_id}/renew", payload, headers,
        )

    def move_out_request(self, lease_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/leases/{lease_id}/move-out-request",
            payload, headers,
        )

    # =======================================================================
    # Deposits (PRD §3.6, §4)
    # =======================================================================
    def get_deposit(self, deposit_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/deposits/{deposit_id}", headers=headers,
        )

    def top_up_deposit(self, deposit_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/deposits/{deposit_id}/top-up",
            payload, headers,
        )

    def propose_deductions(self, deposit_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/deposits/{deposit_id}/propose-deductions",
            payload, headers,
        )

    def approve_deductions(self, deposit_id: str, headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/deposits/{deposit_id}/approve-deductions",
            payload or {}, headers,
        )

    def reject_deductions(self, deposit_id: str, headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/deposits/{deposit_id}/reject-deductions",
            payload or {}, headers,
        )

    # =======================================================================
    # Fee bills (PRD §3.7, §4)
    # =======================================================================
    def create_fee_bill(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/fee-bills", payload, headers)

    def get_fee_bill(self, bill_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/fee-bills/{bill_id}", headers=headers,
        )

    def pay_fee_bill(self, bill_id: str, headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/fee-bills/{bill_id}/pay",
            payload or {}, headers,
        )

    def dispute_fee_bill(self, bill_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/fee-bills/{bill_id}/dispute", payload, headers,
        )

    def resolve_dispute_fee_bill(self, bill_id: str,
                                 payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "POST", f"/fee-bills/{bill_id}/resolve-dispute",
            payload, headers,
        )

    def void_fee_bill(self, bill_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/fee-bills/{bill_id}/void",
            payload or {}, headers,
        )

    # =======================================================================
    # Move-out requests (PRD §3.8, §4)
    # =======================================================================
    def get_move_out_request(self, request_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "GET", f"/move-out-requests/{request_id}", headers=headers,
        )

    def record_inspection(self, request_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/move-out-requests/{request_id}/record-inspection",
            payload, headers,
        )

    def confirm_restoration(self, request_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/move-out-requests/{request_id}/confirm-restoration",
            payload, headers,
        )

    def reject_move_out(self, request_id: str, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/move-out-requests/{request_id}/reject",
            payload or {}, headers,
        )

    def finalize_move_out(self, request_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/move-out-requests/{request_id}/finalize",
            payload or {}, headers,
        )

    # =======================================================================
    # Audit events (PRD §3.9, §4)
    # =======================================================================
    def list_audit_events(self, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/audit-events", headers=headers, params=params,
        )

    # =======================================================================
    # Test-driving endpoints (PRD §3.9, §4)
    # =======================================================================
    def advance_clock(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload, headers)

    def run_sweep(self, headers: Dict[str, str],
                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", "/_sweep/run", payload or {}, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
