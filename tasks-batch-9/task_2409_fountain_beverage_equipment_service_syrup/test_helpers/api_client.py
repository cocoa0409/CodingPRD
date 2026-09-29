"""API client: one method per endpoint of the Fountain Beverage Service Network API."""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/fountain-network"


class ApiClient(GenericApiClient):
    # ─── Logical clock ────────────────────────────────────────────────────

    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    # ─── Outlets ──────────────────────────────────────────────────────────

    def create_outlet(self, payload, headers):
        return self._request("POST", f"{PREFIX}/outlets", payload, headers)

    def get_outlet(self, outlet_id, headers):
        return self._request("GET", f"{PREFIX}/outlets/{outlet_id}", headers=headers)

    def list_outlets(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/outlets", headers=headers, params=params)

    def outlet_status_change(self, outlet_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/outlets/{outlet_id}/status-change", payload, headers
        )

    def outlet_compliance_hold(self, outlet_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/outlets/{outlet_id}/compliance-hold", payload, headers
        )

    def get_brand_mix_report(self, outlet_id, headers):
        return self._request(
            "GET", f"{PREFIX}/outlets/{outlet_id}/brand-mix-report", headers=headers
        )

    # ─── Placement agreements ─────────────────────────────────────────────

    def create_agreement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/placement-agreements", payload, headers)

    def get_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"{PREFIX}/placement-agreements/{agreement_id}", headers=headers
        )

    def list_agreements(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/placement-agreements", headers=headers, params=params
        )

    def activate_agreement(self, agreement_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/placement-agreements/{agreement_id}/activate",
            payload if payload is not None else {},
            headers,
        )

    def assess_shortfall(self, agreement_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/placement-agreements/{agreement_id}/assess-shortfall",
            payload,
            headers,
        )

    def recall_decision(self, agreement_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/placement-agreements/{agreement_id}/recall-decision",
            payload,
            headers,
        )

    def close_term(self, agreement_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/placement-agreements/{agreement_id}/close-term",
            payload if payload is not None else {},
            headers,
        )

    # ─── Dispenser units ──────────────────────────────────────────────────

    def create_dispenser_unit(self, payload, headers):
        return self._request("POST", f"{PREFIX}/dispenser-units", payload, headers)

    def get_dispenser_unit(self, unit_id, headers):
        return self._request("GET", f"{PREFIX}/dispenser-units/{unit_id}", headers=headers)

    def list_dispenser_units(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/dispenser-units", headers=headers, params=params
        )

    def unit_service_hold(self, unit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/dispenser-units/{unit_id}/service-hold", payload, headers
        )

    def confirm_return(self, unit_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/dispenser-units/{unit_id}/confirm-return",
            payload if payload is not None else {},
            headers,
        )

    # ─── Supply items ─────────────────────────────────────────────────────

    def create_supply_item(self, payload, headers):
        return self._request("POST", f"{PREFIX}/supply-items", payload, headers)

    def get_supply_item(self, item_id, headers):
        return self._request("GET", f"{PREFIX}/supply-items/{item_id}", headers=headers)

    def list_supply_items(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/supply-items", headers=headers, params=params
        )

    def patch_supply_item(self, item_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/supply-items/{item_id}", payload, headers)

    # ─── Telemetry readings ───────────────────────────────────────────────

    def create_telemetry_reading(self, payload, headers):
        return self._request("POST", f"{PREFIX}/telemetry-readings", payload, headers)

    def get_telemetry_reading(self, reading_id, headers):
        return self._request(
            "GET", f"{PREFIX}/telemetry-readings/{reading_id}", headers=headers
        )

    def list_telemetry_readings(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/telemetry-readings", headers=headers, params=params
        )

    # ─── Outlet supply positions ──────────────────────────────────────────

    def create_supply_position(self, payload, headers):
        return self._request("POST", f"{PREFIX}/supply-positions", payload, headers)

    def get_supply_position(self, position_id, headers):
        return self._request(
            "GET", f"{PREFIX}/supply-positions/{position_id}", headers=headers
        )

    def list_supply_positions(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/supply-positions", headers=headers, params=params
        )

    def run_forecast(self, position_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/supply-positions/{position_id}/forecast", payload, headers
        )

    def acknowledge_alert(self, position_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/supply-positions/{position_id}/acknowledge-alert",
            payload if payload is not None else {},
            headers,
        )

    # ─── Replenishment routes ─────────────────────────────────────────────

    def create_route(self, payload, headers):
        return self._request("POST", f"{PREFIX}/replenishment-routes", payload, headers)

    def get_route(self, route_id, headers):
        return self._request(
            "GET", f"{PREFIX}/replenishment-routes/{route_id}", headers=headers
        )

    def create_route_stop(self, route_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/replenishment-routes/{route_id}/stops", payload, headers
        )

    def dispatch_route(self, route_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/replenishment-routes/{route_id}/dispatch", payload, headers
        )

    def complete_route(self, route_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/replenishment-routes/{route_id}/complete",
            payload if payload is not None else {},
            headers,
        )

    def cancel_route(self, route_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/replenishment-routes/{route_id}/cancel", payload, headers
        )

    # ─── Route stops ──────────────────────────────────────────────────────

    def get_route_stop(self, stop_id, headers):
        return self._request("GET", f"{PREFIX}/route-stops/{stop_id}", headers=headers)

    def list_route_stops(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/route-stops", headers=headers, params=params)

    def allocate_stop(self, stop_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/route-stops/{stop_id}/allocations", payload, headers
        )

    def arrive_stop(self, stop_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/route-stops/{stop_id}/arrive",
            payload if payload is not None else {},
            headers,
        )

    def serve_stop(self, stop_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/route-stops/{stop_id}/serve",
            payload if payload is not None else {},
            headers,
        )

    def skip_stop(self, stop_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/route-stops/{stop_id}/skip", payload, headers
        )

    # ─── Maintenance tasks ────────────────────────────────────────────────

    def create_maintenance_task(self, payload, headers):
        return self._request("POST", f"{PREFIX}/maintenance-tasks", payload, headers)

    def get_maintenance_task(self, task_id, headers):
        return self._request(
            "GET", f"{PREFIX}/maintenance-tasks/{task_id}", headers=headers
        )

    def list_maintenance_tasks(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/maintenance-tasks", headers=headers, params=params
        )

    def evaluate_task_due(self, task_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/maintenance-tasks/{task_id}/evaluate-due",
            payload if payload is not None else {},
            headers,
        )

    def complete_task(self, task_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/maintenance-tasks/{task_id}/complete",
            payload if payload is not None else {},
            headers,
        )

    def waive_task(self, task_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/maintenance-tasks/{task_id}/waive", payload, headers
        )

    # ─── Service calls ────────────────────────────────────────────────────

    def create_service_call(self, payload, headers):
        return self._request("POST", f"{PREFIX}/service-calls", payload, headers)

    def get_service_call(self, call_id, headers):
        return self._request("GET", f"{PREFIX}/service-calls/{call_id}", headers=headers)

    def list_service_calls(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/service-calls", headers=headers, params=params
        )

    def dispatch_service_call(self, call_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/service-calls/{call_id}/dispatch", payload, headers
        )

    def arrive_on_site(self, call_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/service-calls/{call_id}/arrive-on-site",
            payload if payload is not None else {},
            headers,
        )

    def resolve_service_call(self, call_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/service-calls/{call_id}/resolve", payload, headers
        )

    def escalate_service_call(self, call_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/service-calls/{call_id}/escalate", payload, headers
        )

    def cancel_service_call(self, call_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/service-calls/{call_id}/cancel",
            payload if payload is not None else {},
            headers,
        )

    # ─── Van part stocks ──────────────────────────────────────────────────

    def create_van_part_stock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/van-part-stocks", payload, headers)

    def get_van_part_stock(self, stock_id, headers):
        return self._request(
            "GET", f"{PREFIX}/van-part-stocks/{stock_id}", headers=headers
        )

    def list_van_part_stocks(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/van-part-stocks", headers=headers, params=params
        )

    def restock_van_part(self, stock_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/van-part-stocks/{stock_id}/restock", payload, headers
        )


api_client = ApiClient()
