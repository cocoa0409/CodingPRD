"""API client: one method per endpoint defined in PRD §4.

Each method delegates to GenericApiClient._request and returns the raw
Response object. All endpoints are mounted under the PRD-declared
prefix "/swap-stations".
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import GenericApiClient


PREFIX = "/swap-stations"


class ApiClient(GenericApiClient):
    # =======================================================================
    # Stations
    # =======================================================================
    def create_station(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/stations", payload, headers)

    def list_stations(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{PREFIX}/stations",
                             headers=headers, params=params)

    def get_station(self, station_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/stations/{station_id}",
                             headers=headers)

    def create_charging_slot(self, station_id: str, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/stations/{station_id}/charging-slots",
            payload, headers,
        )

    def list_charging_slots(self, station_id: str, headers: Dict[str, str],
                            params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"{PREFIX}/stations/{station_id}/charging-slots",
            headers=headers, params=params,
        )

    # =======================================================================
    # Reference data — BatteryModel, VehicleModel, CompatibilityRule
    # =======================================================================
    def create_battery_model(self, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/battery-models",
                             payload, headers)

    def create_vehicle_model(self, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/vehicle-models",
                             payload, headers)

    def create_compatibility_rule(self, payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/compatibility-rules",
                             payload, headers)

    def list_compatibility_rules(self, headers: Dict[str, str],
                                 params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{PREFIX}/compatibility-rules",
                             headers=headers, params=params)

    # =======================================================================
    # Batteries
    # =======================================================================
    def create_battery(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/batteries", payload, headers)

    def list_batteries(self, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{PREFIX}/batteries",
                             headers=headers, params=params)

    def get_battery(self, battery_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/batteries/{battery_id}",
                             headers=headers)

    def start_charging(self, battery_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/batteries/{battery_id}/start-charging",
            payload, headers,
        )

    def finish_charging(self, battery_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/batteries/{battery_id}/finish-charging",
            payload, headers,
        )

    def report_fault(self, battery_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/batteries/{battery_id}/report-fault",
            payload, headers,
        )

    def clear_fault(self, battery_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/batteries/{battery_id}/clear-fault",
            {}, headers,
        )

    def grade_cascade(self, battery_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/batteries/{battery_id}/grade-cascade",
            {}, headers,
        )

    def recycle_battery(self, battery_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/batteries/{battery_id}/recycle",
            {}, headers,
        )

    def list_soh_assessments(self, battery_id: str, headers: Dict[str, str],
                             params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"{PREFIX}/batteries/{battery_id}/soh-assessments",
            headers=headers, params=params,
        )

    # =======================================================================
    # Vehicles & Members
    # =======================================================================
    def create_vehicle(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/vehicles/{vehicle_id}",
                             headers=headers)

    def create_member(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/members", payload, headers)

    def get_member(self, member_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/members/{member_id}",
                             headers=headers)

    # =======================================================================
    # Reservations
    # =======================================================================
    def create_reservation(self, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/reservations",
                             payload, headers)

    def list_reservations(self, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{PREFIX}/reservations",
                             headers=headers, params=params)

    def get_reservation(self, reservation_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/reservations/{reservation_id}", headers=headers,
        )

    def check_in_reservation(self, reservation_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/reservations/{reservation_id}/check-in",
            {}, headers,
        )

    def cancel_reservation(self, reservation_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/reservations/{reservation_id}/cancel",
            {}, headers,
        )

    def create_walk_in_reservation(self, payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/reservations/walk-in", payload, headers,
        )

    # =======================================================================
    # Swap events
    # =======================================================================
    def get_swap_event(self, swap_event_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/swap-events/{swap_event_id}", headers=headers,
        )

    def inspect_swap_event(self, swap_event_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/swap-events/{swap_event_id}/inspect",
            payload, headers,
        )

    def uninstall_swap_event(self, swap_event_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/swap-events/{swap_event_id}/uninstall",
            {}, headers,
        )

    def install_swap_event(self, swap_event_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/swap-events/{swap_event_id}/install",
            payload, headers,
        )

    def complete_swap_event(self, swap_event_id: str,
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/swap-events/{swap_event_id}/complete",
            {}, headers,
        )

    def abort_swap_event(self, swap_event_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/swap-events/{swap_event_id}/abort",
            {}, headers,
        )

    # =======================================================================
    # Dispatch orders
    # =======================================================================
    def create_dispatch_order(self, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/dispatch-orders",
                             payload, headers)

    def dispatch_dispatch_order(self, order_id: str,
                                headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/dispatch-orders/{order_id}/dispatch",
            {}, headers,
        )

    def deliver_dispatch_order(self, order_id: str,
                               headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/dispatch-orders/{order_id}/deliver",
            {}, headers,
        )

    def cancel_dispatch_order(self, order_id: str,
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/dispatch-orders/{order_id}/cancel",
            {}, headers,
        )

    # =======================================================================
    # Recalls
    # =======================================================================
    def create_recall(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/recalls", payload, headers)

    # =======================================================================
    # Billing
    # =======================================================================
    def list_billing_records(self, headers: Dict[str, str],
                             params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{PREFIX}/billing-records",
                             headers=headers, params=params)

    def get_billing_record(self, record_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/billing-records/{record_id}", headers=headers,
        )

    def pay_billing_record(self, record_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/billing-records/{record_id}/pay",
            {}, headers,
        )

    def mark_failed_billing_record(self, record_id: str,
                                   headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/billing-records/{record_id}/mark-failed",
            {}, headers,
        )

    def refund_billing_record(self, record_id: str, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/billing-records/{record_id}/refund",
            payload, headers,
        )

    # =======================================================================
    # Audit logs + test-only clock & sweep
    # =======================================================================
    def list_audit_logs(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{PREFIX}/audit-logs",
                             headers=headers, params=params)

    def advance_clock(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/_clock/advance",
                             payload, headers)

    def run_no_show_sweep(self, headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/_sweep/no-show",
                             {}, headers)


api_client = ApiClient()


__all__ = ["ApiClient", "api_client", "PREFIX"]
