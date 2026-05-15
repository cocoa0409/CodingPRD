"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the base _request() method handles the
HTTP plumbing. Tests pass headers explicitly because PRD §2.1 requires
X-User-ID and X-User-Role on every call.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Stations (PRD §3.1)
    # =======================================================================
    def create_station(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/pv-ops/stations", payload, headers)

    def list_stations(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/pv-ops/stations", headers=headers, params=params,
        )

    def get_station(self, station_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/pv-ops/stations/{station_id}", headers=headers,
        )

    # =======================================================================
    # Arrays / Strings / Modules (PRD §3.1)
    # =======================================================================
    def create_array(self, station_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/pv-ops/stations/{station_id}/arrays", payload, headers,
        )

    def create_string(self, array_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/pv-ops/arrays/{array_id}/strings", payload, headers,
        )

    def create_module(self, string_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/pv-ops/strings/{string_id}/modules", payload, headers,
        )

    # =======================================================================
    # Inverters / Transformers (PRD §3.1)
    # =======================================================================
    def create_inverter(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/pv-ops/inverters", payload, headers)

    def get_inverter(self, inverter_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/pv-ops/inverters/{inverter_id}", headers=headers,
        )

    def create_transformer(self, station_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/pv-ops/stations/{station_id}/transformers",
            payload, headers,
        )

    # =======================================================================
    # Suppliers (PRD §3.1)
    # =======================================================================
    def create_supplier(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/pv-ops/suppliers", payload, headers)

    def update_supplier(self, supplier_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/pv-ops/suppliers/{supplier_id}", payload, headers,
        )

    # =======================================================================
    # Generation readings & performance (PRD §3.2)
    # =======================================================================
    def create_reading(self, station_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/pv-ops/stations/{station_id}/readings", payload, headers,
        )

    def get_station_performance(self, station_id: str,
                                headers: Dict[str, str],
                                params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/pv-ops/stations/{station_id}/performance",
            headers=headers, params=params,
        )

    # =======================================================================
    # Sweep / clock / events (PRD §3.2)
    # =======================================================================
    def sweep_run(self, headers: Dict[str, str]):
        return self._request("POST", "/_sweep/run", {}, headers)

    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload, headers)

    def events_emit(self, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request("POST", "/_events/emit", payload, headers)

    # =======================================================================
    # Alarms (PRD §3.3)
    # =======================================================================
    def create_alarm_code_map(self, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", "/pv-ops/alarm-code-map", payload, headers,
        )

    def create_alarm(self, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request("POST", "/pv-ops/alarms", payload, headers)

    def list_alarms(self, headers: Dict[str, str],
                    params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/pv-ops/alarms", headers=headers, params=params,
        )

    def ack_alarm(self, alarm_id: str, headers: Dict[str, str],
                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/pv-ops/alarms/{alarm_id}/ack",
            payload or {}, headers,
        )

    def clear_alarm(self, alarm_id: str, headers: Dict[str, str],
                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/pv-ops/alarms/{alarm_id}/clear",
            payload or {}, headers,
        )

    def archive_alarm(self, alarm_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/pv-ops/alarms/{alarm_id}/archive",
            payload or {}, headers,
        )

    # =======================================================================
    # Patrol plans and records (PRD §3.4)
    # =======================================================================
    def create_patrol_plan(self, station_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/pv-ops/stations/{station_id}/patrol-plans",
            payload, headers,
        )

    def schedule_patrol(self, plan_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/pv-ops/patrol-plans/{plan_id}/schedule",
            payload, headers,
        )

    def start_patrol(self, record_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/pv-ops/patrol-records/{record_id}/start", {}, headers,
        )

    def log_patrol_zone(self, record_id: str, zone: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/pv-ops/patrol-records/{record_id}/zones/{zone}/log",
            payload, headers,
        )

    def submit_patrol(self, record_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/pv-ops/patrol-records/{record_id}/submit", {}, headers,
        )

    def verify_patrol(self, record_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/pv-ops/patrol-records/{record_id}/verify", {}, headers,
        )

    def reject_patrol(self, record_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/pv-ops/patrol-records/{record_id}/reject",
            payload, headers,
        )

    # =======================================================================
    # Defects and work orders (PRD §3.5)
    # =======================================================================
    def create_defect(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/pv-ops/defects", payload, headers)

    def list_defects(self, headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/pv-ops/defects", headers=headers, params=params,
        )

    def create_work_order(self, defect_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/pv-ops/defects/{defect_id}/work-orders",
            payload, headers,
        )

    def start_work_order(self, work_order_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/pv-ops/work-orders/{work_order_id}/start", {}, headers,
        )

    def complete_work_order(self, work_order_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/pv-ops/work-orders/{work_order_id}/complete",
            payload, headers,
        )

    def cancel_work_order(self, work_order_id: str,
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/pv-ops/work-orders/{work_order_id}/cancel", {}, headers,
        )

    def close_defect(self, defect_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/pv-ops/defects/{defect_id}/close", {}, headers,
        )

    def reopen_defect(self, defect_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/pv-ops/defects/{defect_id}/reopen", {}, headers,
        )

    # =======================================================================
    # Spare parts (PRD §3.5)
    # =======================================================================
    def create_spare_part(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", "/pv-ops/spare-parts", payload, headers)

    def update_spare_part(self, spare_part_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/pv-ops/spare-parts/{spare_part_id}", payload, headers,
        )

    # =======================================================================
    # Settlement periods, metering, investor shares (PRD §3.6)
    # =======================================================================
    def create_settlement_period(self, station_id: str,
                                 payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "POST", f"/pv-ops/stations/{station_id}/settlement-periods",
            payload, headers,
        )

    def create_metering(self, station_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/pv-ops/stations/{station_id}/metering",
            payload, headers,
        )

    def start_reconciliation(self, period_id: str, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/pv-ops/settlement-periods/{period_id}/start-reconciliation",
            payload, headers,
        )

    def confirm_settlement(self, period_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/pv-ops/settlement-periods/{period_id}/confirm",
            {}, headers,
        )

    def dispute_settlement(self, period_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/pv-ops/settlement-periods/{period_id}/dispute",
            {}, headers,
        )

    def issue_invoice(self, period_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/pv-ops/settlement-periods/{period_id}/issue-invoice",
            payload, headers,
        )

    def revenue_adjust(self, period_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/pv-ops/settlement-periods/{period_id}/revenue-adjust",
            payload, headers,
        )

    def get_settlement_period(self, period_id: str,
                              headers: Dict[str, str]):
        return self._request(
            "GET", f"/pv-ops/settlement-periods/{period_id}", headers=headers,
        )

    def create_investor_share(self, station_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/pv-ops/stations/{station_id}/investor-shares",
            payload, headers,
        )

    # =======================================================================
    # Subsidies (PRD §3.7)
    # =======================================================================
    def create_subsidy_policy(self, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", "/pv-ops/subsidy-policies", payload, headers,
        )

    def create_subsidy_declaration(self, station_id: str,
                                   payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self._request(
            "POST", f"/pv-ops/stations/{station_id}/subsidy-declarations",
            payload, headers,
        )

    def submit_subsidy_declaration(self, declaration_id: str,
                                   headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/pv-ops/subsidy-declarations/{declaration_id}/submit",
            {}, headers,
        )

    def approve_subsidy_declaration(self, declaration_id: str,
                                    headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/pv-ops/subsidy-declarations/{declaration_id}/approve",
            {}, headers,
        )

    def reject_subsidy_declaration(self, declaration_id: str,
                                   payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/pv-ops/subsidy-declarations/{declaration_id}/reject",
            payload, headers,
        )

    def receive_subsidy_declaration(self, declaration_id: str,
                                    headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/pv-ops/subsidy-declarations/{declaration_id}/receive",
            {}, headers,
        )

    def list_subsidy_declarations(self, headers: Dict[str, str],
                                  params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/pv-ops/subsidy-declarations",
            headers=headers, params=params,
        )

    # =======================================================================
    # Audit log (PRD §2.10)
    # =======================================================================
    def list_audit_entries(self, headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/pv-ops/audit-entries",
            headers=headers, params=params,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
