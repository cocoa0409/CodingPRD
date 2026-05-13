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
    # Networks (PRD §3.1)
    # =======================================================================
    def create_network(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/networks", payload, headers)

    def get_network(self, network_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/networks/{network_id}", headers=headers,
        )

    def advance_clock(self, network_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/networks/{network_id}/_clock/advance",
            payload, headers,
        )

    # =======================================================================
    # Topology versions (PRD §3.2)
    # =======================================================================
    def create_topology_version(self, network_id: str,
                                payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", f"/networks/{network_id}/topology-versions",
            payload, headers,
        )

    def get_topology_version(self, network_id: str, version_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/networks/{network_id}/topology-versions/{version_id}",
            headers=headers,
        )

    def create_node(self, network_id: str, version_id: str,
                    payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/networks/{network_id}/topology-versions/{version_id}/nodes",
            payload, headers,
        )

    def create_segment(self, network_id: str, version_id: str,
                       payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/networks/{network_id}/topology-versions/{version_id}/segments",
            payload, headers,
        )

    def submit_topology_version(self, network_id: str, version_id: str,
                                headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/networks/{network_id}/topology-versions/{version_id}/submit",
            {}, headers,
        )

    def approve_topology_version(self, network_id: str, version_id: str,
                                 headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/networks/{network_id}/topology-versions/{version_id}/approve",
            {}, headers,
        )

    def reject_topology_version(self, network_id: str, version_id: str,
                                payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/networks/{network_id}/topology-versions/{version_id}/reject",
            payload, headers,
        )

    def rollback_topology_version(self, network_id: str, version_id: str,
                                  headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/networks/{network_id}/topology-versions/{version_id}/rollback",
            {}, headers,
        )

    # =======================================================================
    # DMAs (PRD §3.3)
    # =======================================================================
    def create_dma(self, network_id: str, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request(
            "POST", f"/networks/{network_id}/dmas", payload, headers,
        )

    def get_dma(self, network_id: str, dma_id: str,
                headers: Dict[str, str]):
        return self._request(
            "GET", f"/networks/{network_id}/dmas/{dma_id}",
            headers=headers,
        )

    def list_dmas(self, network_id: str, headers: Dict[str, str],
                  params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/networks/{network_id}/dmas",
            headers=headers, params=params,
        )

    def create_water_balance_report(self, network_id: str, dma_id: str,
                                    payload: Dict[str, Any],
                                    headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/networks/{network_id}/dmas/{dma_id}/water-balance-reports",
            payload, headers,
        )

    def list_water_balance_reports(self, network_id: str, dma_id: str,
                                   headers: Dict[str, str],
                                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/networks/{network_id}/dmas/{dma_id}/water-balance-reports",
            headers=headers, params=params,
        )

    # =======================================================================
    # Devices & readings (PRD §3.4)
    # =======================================================================
    def create_device(self, network_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/networks/{network_id}/devices", payload, headers,
        )

    def get_device(self, network_id: str, device_id: str,
                   headers: Dict[str, str]):
        return self._request(
            "GET", f"/networks/{network_id}/devices/{device_id}",
            headers=headers,
        )

    def patch_device(self, network_id: str, device_id: str,
                     payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/networks/{network_id}/devices/{device_id}",
            payload, headers,
        )

    def activate_device(self, network_id: str, device_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/networks/{network_id}/devices/{device_id}/activate",
            {}, headers,
        )

    def decommission_device(self, network_id: str, device_id: str,
                            headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/networks/{network_id}/devices/{device_id}/decommission",
            {}, headers,
        )

    def post_reading(self, network_id: str, device_id: str,
                     payload: Dict[str, Any], headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/networks/{network_id}/devices/{device_id}/readings",
            payload, headers, params=params,
        )

    def list_readings(self, network_id: str, device_id: str,
                      headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/networks/{network_id}/devices/{device_id}/readings",
            headers=headers, params=params,
        )

    # =======================================================================
    # Alerts (PRD §3.6)
    # =======================================================================
    def list_alerts(self, network_id: str, headers: Dict[str, str],
                    params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/networks/{network_id}/alerts",
            headers=headers, params=params,
        )

    def get_alert(self, network_id: str, alert_id: str,
                  headers: Dict[str, str]):
        return self._request(
            "GET", f"/networks/{network_id}/alerts/{alert_id}",
            headers=headers,
        )

    def acknowledge_alert(self, network_id: str, alert_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/networks/{network_id}/alerts/{alert_id}/acknowledge",
            {}, headers,
        )

    def resolve_alert(self, network_id: str, alert_id: str,
                      payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/networks/{network_id}/alerts/{alert_id}/resolve",
            payload, headers,
        )

    def suppress_alert(self, network_id: str, alert_id: str,
                       payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/networks/{network_id}/alerts/{alert_id}/suppress",
            payload, headers,
        )

    # =======================================================================
    # Investigations (PRD §3.7)
    # =======================================================================
    def create_investigation(self, network_id: str, alert_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/networks/{network_id}/alerts/{alert_id}/investigations",
            {}, headers,
        )

    def get_investigation(self, network_id: str, investigation_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/networks/{network_id}/investigations/{investigation_id}",
            headers=headers,
        )

    def narrow_investigation(self, network_id: str, investigation_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/networks/{network_id}/investigations/{investigation_id}/narrow",
            {}, headers,
        )

    def dispatch_investigation(self, network_id: str,
                               investigation_id: str,
                               payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/networks/{network_id}/investigations/{investigation_id}/dispatch",
            payload, headers,
        )

    # =======================================================================
    # WorkOrders (PRD §3.8)
    # =======================================================================
    def create_work_order(self, network_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/networks/{network_id}/work-orders",
            payload, headers,
        )

    def get_work_order(self, network_id: str, work_order_id: str,
                       headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/networks/{network_id}/work-orders/{work_order_id}",
            headers=headers,
        )

    def list_work_orders(self, network_id: str, headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/networks/{network_id}/work-orders",
            headers=headers, params=params,
        )

    def assign_work_order(self, network_id: str, work_order_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/networks/{network_id}/work-orders/{work_order_id}/assign",
            payload, headers,
        )

    def request_parts(self, network_id: str, work_order_id: str,
                      payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/networks/{network_id}/work-orders/{work_order_id}/request-parts",
            payload, headers,
        )

    def start_work_order(self, network_id: str, work_order_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/networks/{network_id}/work-orders/{work_order_id}/start",
            {}, headers,
        )

    def complete_work_order(self, network_id: str, work_order_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/networks/{network_id}/work-orders/{work_order_id}/complete",
            payload, headers,
        )

    def verify_work_order(self, network_id: str, work_order_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/networks/{network_id}/work-orders/{work_order_id}/verify",
            payload, headers,
        )

    def cancel_work_order(self, network_id: str, work_order_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/networks/{network_id}/work-orders/{work_order_id}/cancel",
            {}, headers,
        )

    # =======================================================================
    # Sync events & audit logs (PRD §2.9)
    # =======================================================================
    def list_sync_events(self, network_id: str, headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/networks/{network_id}/sync-events",
            headers=headers, params=params,
        )

    def list_audit_logs(self, network_id: str, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/networks/{network_id}/audit-logs",
            headers=headers, params=params,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
