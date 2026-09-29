"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/swiss-shop"


class ApiClient(GenericApiClient):
    # ---- Logical clock -----------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- Operator ----------------------------------------------------------
    def create_operator(self, payload, headers):
        return self._request("POST", f"{PREFIX}/operators", payload, headers)

    def get_operator(self, operator_id, headers):
        return self._request("GET", f"{PREFIX}/operators/{operator_id}", headers=headers)

    # ---- Machine -----------------------------------------------------------
    def create_machine(self, payload, headers):
        return self._request("POST", f"{PREFIX}/machines", payload, headers)

    def get_machine(self, machine_id, headers):
        return self._request("GET", f"{PREFIX}/machines/{machine_id}", headers=headers)

    def restore_machine(self, machine_id, headers):
        return self._request("POST", f"{PREFIX}/machines/{machine_id}/restore", {}, headers)

    def reclaim_machine(self, machine_id, payload, headers):
        return self._request("POST", f"{PREFIX}/machines/{machine_id}/reclaim", payload, headers)

    # ---- Part --------------------------------------------------------------
    def create_part(self, payload, headers):
        return self._request("POST", f"{PREFIX}/parts", payload, headers)

    def get_part(self, part_id, headers):
        return self._request("GET", f"{PREFIX}/parts/{part_id}", headers=headers)

    # ---- Characteristic ----------------------------------------------------
    def create_characteristic(self, payload, headers):
        return self._request("POST", f"{PREFIX}/characteristics", payload, headers)

    def get_characteristic(self, characteristic_id, headers):
        return self._request(
            "GET", f"{PREFIX}/characteristics/{characteristic_id}", headers=headers
        )

    def list_characteristics(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/characteristics", headers=headers, params=params)

    # ---- Gauge -------------------------------------------------------------
    def create_gauge(self, payload, headers):
        return self._request("POST", f"{PREFIX}/gauges", payload, headers)

    def get_gauge(self, gauge_id, headers):
        return self._request("GET", f"{PREFIX}/gauges/{gauge_id}", headers=headers)

    def create_gauge_calibration(self, gauge_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/gauges/{gauge_id}/calibrations", payload, headers
        )

    # ---- BarStockLot -------------------------------------------------------
    def create_bar_stock_lot(self, payload, headers):
        return self._request("POST", f"{PREFIX}/bar-stock-lots", payload, headers)

    def get_bar_stock_lot(self, lot_id, headers):
        return self._request("GET", f"{PREFIX}/bar-stock-lots/{lot_id}", headers=headers)

    def certify_bar_stock_lot(self, lot_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/bar-stock-lots/{lot_id}/certify", payload, headers
        )

    # ---- Quote -------------------------------------------------------------
    def create_quote(self, payload, headers):
        return self._request("POST", f"{PREFIX}/quotes", payload, headers)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"{PREFIX}/quotes/{quote_id}", headers=headers)

    def list_quotes(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/quotes", headers=headers, params=params)

    def price_quote(self, quote_id, payload, headers):
        return self._request("POST", f"{PREFIX}/quotes/{quote_id}/price", payload, headers)

    def accept_quote(self, quote_id, payload, headers):
        return self._request("POST", f"{PREFIX}/quotes/{quote_id}/accept", payload, headers)

    # ---- BlanketPO ---------------------------------------------------------
    def get_blanket_po(self, po_id, headers):
        return self._request("GET", f"{PREFIX}/blanket-pos/{po_id}", headers=headers)

    def list_blanket_pos(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/blanket-pos", headers=headers, params=params)

    def suspend_blanket_po(self, po_id, payload, headers):
        return self._request("POST", f"{PREFIX}/blanket-pos/{po_id}/suspend", payload, headers)

    def reinstate_blanket_po(self, po_id, headers):
        return self._request("POST", f"{PREFIX}/blanket-pos/{po_id}/reinstate", {}, headers)

    # ---- KanbanRelease -----------------------------------------------------
    def create_kanban_release(self, payload, headers):
        return self._request("POST", f"{PREFIX}/kanban-releases", payload, headers)

    def get_kanban_release(self, release_id, headers):
        return self._request("GET", f"{PREFIX}/kanban-releases/{release_id}", headers=headers)

    def list_kanban_releases(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/kanban-releases", headers=headers, params=params)

    def short_close_release(self, release_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/kanban-releases/{release_id}/short-close", payload, headers
        )

    # ---- ToolAssignment ----------------------------------------------------
    def create_tool_assignment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/tool-assignments", payload, headers)

    def get_tool_assignment(self, tool_id, headers):
        return self._request("GET", f"{PREFIX}/tool-assignments/{tool_id}", headers=headers)

    def list_tool_assignments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/tool-assignments", headers=headers, params=params)

    def post_offset_log(self, tool_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/tool-assignments/{tool_id}/offset-logs", payload, headers
        )

    def index_tool_assignment(self, tool_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/tool-assignments/{tool_id}/index", payload, headers
        )

    # ---- WorkOrder ---------------------------------------------------------
    def create_work_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/work-orders", payload, headers)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"{PREFIX}/work-orders/{work_order_id}", headers=headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/work-orders", headers=headers, params=params)

    def start_work_order(self, work_order_id, headers):
        return self._request("POST", f"{PREFIX}/work-orders/{work_order_id}/start", {}, headers)

    def complete_machining(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/work-orders/{work_order_id}/complete-machining", payload, headers
        )

    def cancel_work_order(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/work-orders/{work_order_id}/cancel", payload, headers
        )

    def disposition_work_order(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/work-orders/{work_order_id}/disposition", payload, headers
        )

    def get_quality_summary(self, work_order_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/work-orders/{work_order_id}/quality-summary",
            headers=headers,
            params=params,
        )

    # ---- SpcSample ---------------------------------------------------------
    def create_spc_sample(self, payload, headers):
        return self._request("POST", f"{PREFIX}/spc-samples", payload, headers)

    def get_spc_sample(self, sample_id, headers):
        return self._request("GET", f"{PREFIX}/spc-samples/{sample_id}", headers=headers)

    def list_spc_samples(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/spc-samples", headers=headers, params=params)

    # ---- RoutingStep -------------------------------------------------------
    def create_routing_step(self, payload, headers):
        return self._request("POST", f"{PREFIX}/routing-steps", payload, headers)

    def get_routing_step(self, step_id, headers):
        return self._request("GET", f"{PREFIX}/routing-steps/{step_id}", headers=headers)

    def list_routing_steps(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/routing-steps", headers=headers, params=params)

    def advance_routing_step(self, step_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/routing-steps/{step_id}/advance", payload, headers
        )


api_client = ApiClient()
