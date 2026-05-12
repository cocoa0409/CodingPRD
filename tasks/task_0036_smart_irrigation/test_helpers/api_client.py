"""API client: one method per endpoint defined in PRD §4.

Every method delegates to GenericApiClient._request and returns the raw
Response object. Tests pass headers explicitly because PRD §2.1 makes
X-User-ID / X-User-Role mandatory for every non-test-driving call.
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


PREFIX = ""  # PRD §4 endpoints use bare paths


class ApiClient(GenericApiClient):
    # =====================================================================
    # Tenants
    # =====================================================================
    def create_tenant(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/tenants", payload, headers)

    def get_tenant(self, tenant_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/tenants/{tenant_id}", headers=headers)

    # =====================================================================
    # Plots
    # =====================================================================
    def create_plot(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/plots", payload, headers)

    def get_plot(self, plot_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/plots/{plot_id}", headers=headers)

    def patch_plot(self, plot_id: str, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request("PATCH", f"/plots/{plot_id}", payload, headers)

    def list_plots(self, headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/plots", headers=headers, params=params)

    # =====================================================================
    # Sensors
    # =====================================================================
    def create_sensor(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/sensors", payload, headers)

    def patch_sensor(self, sensor_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request("PATCH", f"/sensors/{sensor_id}", payload, headers)

    def get_sensor(self, sensor_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/sensors/{sensor_id}", headers=headers)

    # =====================================================================
    # Sensor readings
    # =====================================================================
    def ingest_reading(self, sensor_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/sensors/{sensor_id}/readings", payload, headers
        )

    def list_readings(self, sensor_id: str, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/sensors/{sensor_id}/readings",
            headers=headers, params=params,
        )

    # =====================================================================
    # Irrigation plans (nested under plot)
    # =====================================================================
    def create_irrigation_plan(self, plot_id: str, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", f"/plots/{plot_id}/irrigation-plans", payload, headers
        )

    def activate_plan(self, plot_id: str, plan_id: str,
                      headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/plots/{plot_id}/irrigation-plans/{plan_id}/activate",
            {}, headers,
        )

    def suspend_plan(self, plot_id: str, plan_id: str,
                     headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/plots/{plot_id}/irrigation-plans/{plan_id}/suspend",
            {}, headers,
        )

    def resume_plan(self, plot_id: str, plan_id: str,
                    headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/plots/{plot_id}/irrigation-plans/{plan_id}/resume",
            {}, headers,
        )

    def override_plan(self, plot_id: str, plan_id: str,
                      payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/plots/{plot_id}/irrigation-plans/{plan_id}/override",
            payload, headers,
        )

    def cancel_plan(self, plot_id: str, plan_id: str,
                    headers: Dict[str, str]):
        return self._request(
            "DELETE",
            f"/plots/{plot_id}/irrigation-plans/{plan_id}",
            headers=headers,
        )

    def list_plans(self, plot_id: str, headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/plots/{plot_id}/irrigation-plans",
            headers=headers, params=params,
        )

    # =====================================================================
    # Valve groups
    # =====================================================================
    def create_valve_group(self, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request("POST", "/valve-groups", payload, headers)

    def patch_valve_group(self, valve_group_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/valve-groups/{valve_group_id}", payload, headers
        )

    def get_valve_group(self, valve_group_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/valve-groups/{valve_group_id}", headers=headers
        )

    # =====================================================================
    # Control commands
    # =====================================================================
    def create_control_command(self, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request("POST", "/control-commands", payload, headers)

    def dispatch_command(self, command_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/control-commands/{command_id}/dispatch", {}, headers
        )

    def feedback_command(self, command_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/control-commands/{command_id}/feedback",
            payload, headers,
        )

    def get_control_command(self, command_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/control-commands/{command_id}", headers=headers
        )

    def list_control_commands(self, headers: Dict[str, str],
                              params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/control-commands", headers=headers, params=params
        )

    # =====================================================================
    # Water quotas
    # =====================================================================
    def create_water_quota(self, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request("POST", "/water-quotas", payload, headers)

    def patch_water_quota(self, quota_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/water-quotas/{quota_id}", payload, headers
        )

    def request_quota_override(self, quota_id: str, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", f"/water-quotas/{quota_id}/request-override",
            payload, headers,
        )

    def approve_quota_override(self, quota_id: str, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", f"/water-quotas/{quota_id}/approve-override",
            payload, headers,
        )

    def reject_quota_override(self, quota_id: str, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/water-quotas/{quota_id}/reject-override",
            payload, headers,
        )

    def get_water_quota(self, quota_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/water-quotas/{quota_id}", headers=headers
        )

    def list_water_quotas(self, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/water-quotas", headers=headers, params=params
        )

    # =====================================================================
    # Alerts
    # =====================================================================
    def get_alert(self, alert_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/alerts/{alert_id}", headers=headers)

    def acknowledge_alert(self, alert_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/alerts/{alert_id}/acknowledge", {}, headers
        )

    def resolve_alert(self, alert_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/alerts/{alert_id}/resolve", {}, headers
        )

    def list_alerts(self, headers: Dict[str, str],
                    params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/alerts", headers=headers, params=params)

    # =====================================================================
    # Water bills
    # =====================================================================
    def create_water_bill(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", "/water-bills", payload, headers)

    def issue_bill(self, bill_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/water-bills/{bill_id}/issue", {}, headers
        )

    def pay_bill(self, bill_id: str, payload: Dict[str, Any],
                 headers: Dict[str, str]):
        return self._request(
            "POST", f"/water-bills/{bill_id}/payments", payload, headers
        )

    def dispute_bill(self, bill_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/water-bills/{bill_id}/dispute", payload, headers
        )

    def resolve_bill_dispute(self, bill_id: str, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/water-bills/{bill_id}/dispute-resolve",
            payload, headers,
        )

    def get_water_bill(self, bill_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/water-bills/{bill_id}", headers=headers
        )

    def list_water_bills(self, headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/water-bills", headers=headers, params=params
        )

    # =====================================================================
    # Audit logs
    # =====================================================================
    def list_audit_logs(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/audit-logs", headers=headers, params=params
        )

    # =====================================================================
    # Test-driving endpoints (PRD §4)
    # =====================================================================
    def advance_clock(self, to_iso: str,
                      headers: Optional[Dict[str, str]] = None):
        return self._request(
            "POST", "/_clock/advance", {"to_iso8601": to_iso},
            headers or {},
        )

    def run_sweep(self, headers: Optional[Dict[str, str]] = None):
        return self._request(
            "POST", "/_sweep/run", {}, headers or {},
        )

    def emit_event(self, event_type: str, payload: Dict[str, Any],
                   headers: Optional[Dict[str, str]] = None):
        body = {"event_type": event_type, "payload": payload}
        return self._request(
            "POST", "/_events/emit", body, headers or {},
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client", "PREFIX"]
