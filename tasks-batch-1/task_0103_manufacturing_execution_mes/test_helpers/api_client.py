"""API client: one method per endpoint defined in the MES PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Product + BOM ----
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def create_bom_line(self, payload, headers):
        return self._request("POST", "/bom-lines", payload, headers)

    def get_bom_line(self, bom_line_id, headers):
        return self._request("GET", f"/bom-lines/{bom_line_id}", headers=headers)

    def list_bom_lines(self, headers, params=None):
        return self._request("GET", "/bom-lines", headers=headers, params=params)

    # ---- Routing + Operation ----
    def create_routing(self, payload, headers):
        return self._request("POST", "/routings", payload, headers)

    def get_routing(self, routing_id, headers):
        return self._request("GET", f"/routings/{routing_id}", headers=headers)

    def list_routings(self, headers, params=None):
        return self._request("GET", "/routings", headers=headers, params=params)

    def create_operation(self, routing_id, payload, headers):
        return self._request("POST", f"/routings/{routing_id}/operations", payload, headers)

    def list_routing_operations(self, routing_id, headers):
        return self._request("GET", f"/routings/{routing_id}/operations", headers=headers)

    def release_routing(self, routing_id, headers):
        return self._request("POST", f"/routings/{routing_id}/release", {}, headers)

    def archive_routing(self, routing_id, headers):
        return self._request("POST", f"/routings/{routing_id}/archive", {}, headers)

    # ---- Machine + OEE ----
    def create_machine(self, payload, headers):
        return self._request("POST", "/machines", payload, headers)

    def get_machine(self, machine_id, headers):
        return self._request("GET", f"/machines/{machine_id}", headers=headers)

    def list_machine_operations(self, machine_id, headers):
        return self._request("GET", f"/machines/{machine_id}/operations", headers=headers)

    def set_machine_status(self, machine_id, payload, headers):
        return self._request("POST", f"/machines/{machine_id}/status", payload, headers)

    def create_run_log(self, machine_id, payload, headers):
        return self._request("POST", f"/machines/{machine_id}/run-logs", payload, headers)

    def list_run_logs(self, machine_id, headers, params=None):
        return self._request("GET", f"/machines/{machine_id}/run-logs", headers=headers, params=params)

    def recompute_oee(self, machine_id, headers):
        return self._request("POST", f"/machines/{machine_id}/recompute-oee", {}, headers)

    # ---- Lot inventory ----
    def create_lot(self, payload, headers):
        return self._request("POST", "/lots", payload, headers)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/lots/{lot_id}", headers=headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", "/lots", headers=headers, params=params)

    # ---- Work order lifecycle ----
    def create_work_order(self, payload, headers):
        return self._request("POST", "/work-orders", payload, headers)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/work-orders/{work_order_id}", headers=headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/work-orders", headers=headers, params=params)

    def release_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/release", payload, headers)

    def complete_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/complete", {}, headers)

    def close_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/close", {}, headers)

    def cancel_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/cancel", {}, headers)

    def get_cost_summary(self, work_order_id, headers):
        return self._request("GET", f"/work-orders/{work_order_id}/cost-summary", headers=headers)

    # ---- Component demand ----
    def list_work_order_component_demands(self, work_order_id, headers):
        return self._request("GET", f"/work-orders/{work_order_id}/component-demands", headers=headers)

    def get_component_demand(self, component_demand_id, headers):
        return self._request("GET", f"/component-demands/{component_demand_id}", headers=headers)

    def list_component_demands(self, headers, params=None):
        return self._request("GET", "/component-demands", headers=headers, params=params)

    # ---- Work order operations (WIP) ----
    def list_work_order_operations(self, work_order_id, headers):
        return self._request("GET", f"/work-orders/{work_order_id}/operations", headers=headers)

    def get_work_order_operation(self, woop_id, headers):
        return self._request("GET", f"/work-order-operations/{woop_id}", headers=headers)

    def list_wip_nodes(self, headers, params=None):
        return self._request("GET", "/work-order-operations", headers=headers, params=params)

    def start_operation(self, woop_id, payload, headers):
        return self._request("POST", f"/work-order-operations/{woop_id}/start", payload, headers)

    def pause_operation(self, woop_id, headers):
        return self._request("POST", f"/work-order-operations/{woop_id}/pause", {}, headers)

    def resume_operation(self, woop_id, headers):
        return self._request("POST", f"/work-order-operations/{woop_id}/resume", {}, headers)

    def complete_operation(self, woop_id, payload, headers):
        return self._request("POST", f"/work-order-operations/{woop_id}/complete", payload, headers)

    def create_signoff(self, woop_id, payload, headers):
        return self._request("POST", f"/work-order-operations/{woop_id}/signoffs", payload, headers)

    def list_signoffs(self, woop_id, headers):
        return self._request("GET", f"/work-order-operations/{woop_id}/signoffs", headers=headers)

    def create_scrap_disposition(self, woop_id, payload, headers):
        return self._request("POST", f"/work-order-operations/{woop_id}/scrap-dispositions", payload, headers)

    def list_scrap_dispositions(self, woop_id, headers):
        return self._request("GET", f"/work-order-operations/{woop_id}/scrap-dispositions", headers=headers)

    def disposition_scrap(self, scrap_disposition_id, payload, headers):
        return self._request("POST", f"/scrap-dispositions/{scrap_disposition_id}/disposition", payload, headers)

    def get_scrap_disposition(self, scrap_disposition_id, headers):
        return self._request("GET", f"/scrap-dispositions/{scrap_disposition_id}", headers=headers)

    # ---- Lot issues + genealogy ----
    def create_lot_issue(self, payload, headers):
        return self._request("POST", "/lot-issues", payload, headers)

    def get_lot_issue(self, lot_issue_id, headers):
        return self._request("GET", f"/lot-issues/{lot_issue_id}", headers=headers)

    def list_lot_issues(self, headers, params=None):
        return self._request("GET", "/lot-issues", headers=headers, params=params)

    def list_work_order_genealogy(self, work_order_id, headers):
        return self._request("GET", f"/work-orders/{work_order_id}/genealogy", headers=headers)

    def get_genealogy_link(self, genealogy_link_id, headers):
        return self._request("GET", f"/genealogy-links/{genealogy_link_id}", headers=headers)

    def list_genealogy_links(self, headers, params=None):
        return self._request("GET", "/genealogy-links", headers=headers, params=params)


api_client = ApiClient()
