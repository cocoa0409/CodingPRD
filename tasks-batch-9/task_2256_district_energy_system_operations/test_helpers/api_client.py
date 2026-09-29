"""One method per District Energy endpoint.

Every method returns the raw ``requests.Response`` so tests can assert status
codes directly. Collection reads take an optional ``params`` dict carrying
``limit``, ``offset`` and the equality filters each collection declares.
"""

from typing import Any, Dict, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX, CLOCK_PATH


class ApiClient(GenericApiClient):
    """Typed client for the District Energy System Operations API."""

    def __init__(self, base_url: Optional[str] = None) -> None:
        super().__init__(base_url)
        # The harness reboots the server on the same port before every test, so a
        # keep-alive socket pooled by an earlier test is already dead when the next
        # test reuses it. Ask for one connection per request instead of inheriting a
        # stale pooled one; this only affects transport, never request content.
        self.session.headers.update({"Connection": "close"})

    # ─── The logical clock (mounted at the server root) ─────────────────────

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        """POST /_clock/set_current_utc — reposition the server's logical clock."""
        return self._request("POST", CLOCK_PATH, payload, headers)

    # ─── NetworkLoop ───────────────────────────────────────────────────────

    def create_network_loop(self, payload, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/network-loops", payload, headers)

    def get_network_loop(self, loop_id: str, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/network-loops/{loop_id}", None, headers)

    def list_network_loops(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/network-loops", params, headers)

    def get_emissions_summary(self, loop_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/network-loops/{loop_id}/emissions-summary", None, headers
        )

    # ─── PipeSegment ───────────────────────────────────────────────────────

    def create_pipe_segment(self, payload, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/pipe-segments", payload, headers)

    def get_pipe_segment(self, segment_id: str, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/pipe-segments/{segment_id}", None, headers)

    def list_pipe_segments(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/pipe-segments", params, headers)

    def assess_segment_condition(self, segment_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/pipe-segments/{segment_id}/condition-assessment",
            payload,
            headers,
        )

    # ─── FuelSupplyContract ────────────────────────────────────────────────

    def create_fuel_supply_contract(self, payload, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/fuel-supply-contracts", payload, headers)

    def get_fuel_supply_contract(self, contract_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/fuel-supply-contracts/{contract_id}", None, headers
        )

    def list_fuel_supply_contracts(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/fuel-supply-contracts", params, headers)

    def set_fuel_contract_status(self, contract_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/fuel-supply-contracts/{contract_id}/status", payload, headers
        )

    # ─── ProductionAsset ───────────────────────────────────────────────────

    def create_production_asset(self, payload, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/production-assets", payload, headers)

    def get_production_asset(self, asset_id: str, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/production-assets/{asset_id}", None, headers)

    def list_production_assets(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/production-assets", params, headers)

    def set_asset_availability(self, asset_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/production-assets/{asset_id}/availability", payload, headers
        )

    # ─── LoadForecast ──────────────────────────────────────────────────────

    def create_load_forecast(self, payload, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/load-forecasts", payload, headers)

    def get_load_forecast(self, forecast_id: str, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/load-forecasts/{forecast_id}", None, headers)

    def list_load_forecasts(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/load-forecasts", params, headers)

    def publish_load_forecast(self, forecast_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/load-forecasts/{forecast_id}/publish", payload, headers
        )

    # ─── DispatchPlan ──────────────────────────────────────────────────────

    def create_dispatch_plan(self, payload, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/dispatch-plans", payload, headers)

    def get_dispatch_plan(self, plan_id: str, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/dispatch-plans/{plan_id}", None, headers)

    def list_dispatch_plans(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/dispatch-plans", params, headers)

    def optimize_dispatch_plan(self, plan_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/dispatch-plans/{plan_id}/optimize", payload, headers
        )

    def submit_dispatch_plan(self, plan_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/dispatch-plans/{plan_id}/submit", payload, headers
        )

    def review_dispatch_plan(self, plan_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/dispatch-plans/{plan_id}/review", payload, headers
        )

    def commit_dispatch_plan(self, plan_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/dispatch-plans/{plan_id}/commit", payload, headers
        )

    def decommit_dispatch_plan(self, plan_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/dispatch-plans/{plan_id}/decommit", payload, headers
        )

    def reconcile_dispatch_plan(self, plan_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/dispatch-plans/{plan_id}/reconcile", payload, headers
        )

    # ─── DispatchOrder ─────────────────────────────────────────────────────

    def get_dispatch_order(self, order_id: str, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/dispatch-orders/{order_id}", None, headers)

    def list_dispatch_orders(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/dispatch-orders", params, headers)

    # ─── RateSchedule ──────────────────────────────────────────────────────

    def create_rate_schedule(self, payload, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/rate-schedules", payload, headers)

    def get_rate_schedule(self, rate_schedule_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/rate-schedules/{rate_schedule_id}", None, headers
        )

    def list_rate_schedules(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/rate-schedules", params, headers)

    # ─── ConnectionAgreement ───────────────────────────────────────────────

    def create_connection_agreement(self, payload, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/connection-agreements", payload, headers)

    def get_connection_agreement(self, agreement_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/connection-agreements/{agreement_id}", None, headers
        )

    def list_connection_agreements(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/connection-agreements", params, headers)

    def activate_connection_agreement(self, agreement_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/connection-agreements/{agreement_id}/activate",
            payload,
            headers,
        )

    def set_agreement_status(self, agreement_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/connection-agreements/{agreement_id}/status", payload, headers
        )

    # ─── MeteringPoint ─────────────────────────────────────────────────────

    def create_metering_point(self, payload, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/metering-points", payload, headers)

    def get_metering_point(self, point_id: str, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/metering-points/{point_id}", None, headers)

    def list_metering_points(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/metering-points", params, headers)

    def commission_metering_point(self, point_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/metering-points/{point_id}/commission", payload, headers
        )

    def remove_metering_point(self, point_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/metering-points/{point_id}/remove", payload, headers
        )

    def create_meter_reading(self, point_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/metering-points/{point_id}/readings", payload, headers
        )

    def list_point_readings(self, point_id: str, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/metering-points/{point_id}/readings", params, headers
        )

    # ─── MeterReading ──────────────────────────────────────────────────────

    def get_meter_reading(self, reading_id: str, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/meter-readings/{reading_id}", None, headers)

    def list_meter_readings(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/meter-readings", params, headers)

    # ─── Invoice ───────────────────────────────────────────────────────────

    def create_invoice(self, payload, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/invoices", payload, headers)

    def get_invoice(self, invoice_id: str, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/invoices/{invoice_id}", None, headers)

    def list_invoices(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/invoices", params, headers)

    def issue_invoice(self, invoice_id: str, payload, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/invoices/{invoice_id}/issue", payload, headers)

    def adjust_invoice(self, invoice_id: str, payload, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/invoices/{invoice_id}/adjust", payload, headers)

    def pay_invoice(self, invoice_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/invoices/{invoice_id}/payments", payload, headers
        )

    def void_invoice(self, invoice_id: str, payload, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/invoices/{invoice_id}/void", payload, headers)

    # ─── WorkOrder ─────────────────────────────────────────────────────────

    def create_work_order(self, payload, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/work-orders", payload, headers)

    def get_work_order(self, work_order_id: str, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/work-orders/{work_order_id}", None, headers)

    def list_work_orders(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/work-orders", params, headers)

    def submit_work_order_permit(self, work_order_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/work-orders/{work_order_id}/submit-permit", payload, headers
        )

    def decide_work_order_permit(self, work_order_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/work-orders/{work_order_id}/permit-decision", payload, headers
        )

    def begin_excavation(self, work_order_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/work-orders/{work_order_id}/begin-excavation", payload, headers
        )

    def begin_repair(self, work_order_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/work-orders/{work_order_id}/begin-repair", payload, headers
        )

    def backfill_work_order(self, work_order_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/work-orders/{work_order_id}/backfill", payload, headers
        )

    def complete_work_order(self, work_order_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/work-orders/{work_order_id}/complete", payload, headers
        )

    def cancel_work_order(self, work_order_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/work-orders/{work_order_id}/cancel", payload, headers
        )

    # ─── ExpansionProject ──────────────────────────────────────────────────

    def create_expansion_project(self, payload, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/expansion-projects", payload, headers)

    def get_expansion_project(self, project_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/expansion-projects/{project_id}", None, headers
        )

    def list_expansion_projects(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/expansion-projects", params, headers)

    def size_expansion_project(self, project_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/expansion-projects/{project_id}/size", payload, headers
        )

    def decide_expansion_project(self, project_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/expansion-projects/{project_id}/decision", payload, headers
        )

    def convert_expansion_project(self, project_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/expansion-projects/{project_id}/convert", payload, headers
        )


api_client = ApiClient()

__all__ = ["ApiClient", "api_client"]
