"""API client: one method per endpoint defined in the PRD (Section 4).

All endpoints are mounted under the /operations prefix. The base _request()
method is inherited from GenericApiClient.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Test-driving clock ──────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/operations/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ─── HostSite ────────────────────────────────────────────────────────
    def create_host_site(self, payload, headers):
        return self._request("POST", "/operations/host-sites", payload, headers)

    def list_host_sites(self, headers, params=None):
        return self._request("GET", "/operations/host-sites", headers=headers, params=params)

    def get_host_site(self, host_site_id, headers):
        return self._request("GET", f"/operations/host-sites/{host_site_id}", headers=headers)

    def suspend_host_site(self, host_site_id, headers):
        return self._request("POST", f"/operations/host-sites/{host_site_id}/suspend", {}, headers)

    # ─── Product ─────────────────────────────────────────────────────────
    def create_product(self, payload, headers):
        return self._request("POST", "/operations/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/operations/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/operations/products/{product_id}", headers=headers)

    def update_product_cost(self, product_id, payload, headers):
        return self._request("PATCH", f"/operations/products/{product_id}/cost", payload, headers)

    def discontinue_product(self, product_id, headers):
        return self._request("POST", f"/operations/products/{product_id}/discontinue", {}, headers)

    # ─── Machine ─────────────────────────────────────────────────────────
    def create_machine(self, payload, headers):
        return self._request("POST", "/operations/machines", payload, headers)

    def list_machines(self, headers, params=None):
        return self._request("GET", "/operations/machines", headers=headers, params=params)

    def get_machine(self, machine_id, headers):
        return self._request("GET", f"/operations/machines/{machine_id}", headers=headers)

    def collect_cash(self, machine_id, headers):
        return self._request("POST", f"/operations/machines/{machine_id}/cash-collections", {}, headers)

    def spoilage_purge(self, machine_id, headers):
        return self._request("POST", f"/operations/machines/{machine_id}/spoilage-purge", {}, headers)

    # ─── PlanogramSlot ───────────────────────────────────────────────────
    def create_slot(self, machine_id, payload, headers):
        return self._request("POST", f"/operations/machines/{machine_id}/slots", payload, headers)

    def list_machine_slots(self, machine_id, headers, params=None):
        return self._request("GET", f"/operations/machines/{machine_id}/slots", headers=headers, params=params)

    def list_slots(self, headers, params=None):
        return self._request("GET", "/operations/slots", headers=headers, params=params)

    def get_slot(self, slot_id, headers):
        return self._request("GET", f"/operations/slots/{slot_id}", headers=headers)

    def update_slot_price(self, slot_id, payload, headers):
        return self._request("PATCH", f"/operations/slots/{slot_id}/price", payload, headers)

    # ─── InventoryLot ────────────────────────────────────────────────────
    def list_slot_lots(self, slot_id, headers, params=None):
        return self._request("GET", f"/operations/slots/{slot_id}/lots", headers=headers, params=params)

    def list_lots(self, headers, params=None):
        return self._request("GET", "/operations/lots", headers=headers, params=params)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/operations/lots/{lot_id}", headers=headers)

    # ─── RouteDriverProfile ──────────────────────────────────────────────
    def create_driver(self, payload, headers):
        return self._request("POST", "/operations/drivers", payload, headers)

    def list_drivers(self, headers, params=None):
        return self._request("GET", "/operations/drivers", headers=headers, params=params)

    def get_driver(self, driver_id, headers):
        return self._request("GET", f"/operations/drivers/{driver_id}", headers=headers)

    # ─── RestockRoute ────────────────────────────────────────────────────
    def create_route(self, payload, headers):
        return self._request("POST", "/operations/routes", payload, headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/operations/routes", headers=headers, params=params)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/operations/routes/{route_id}", headers=headers)

    def create_stop(self, route_id, payload, headers):
        return self._request("POST", f"/operations/routes/{route_id}/stops", payload, headers)

    def list_route_stops(self, route_id, headers, params=None):
        return self._request("GET", f"/operations/routes/{route_id}/stops", headers=headers, params=params)

    def dispatch_route(self, route_id, headers):
        return self._request("POST", f"/operations/routes/{route_id}/dispatch", {}, headers)

    def close_route(self, route_id, headers):
        return self._request("POST", f"/operations/routes/{route_id}/close", {}, headers)

    # ─── RouteStop (reverse reachability) ────────────────────────────────
    def list_stops(self, headers, params=None):
        return self._request("GET", "/operations/stops", headers=headers, params=params)

    def get_stop(self, stop_id, headers):
        return self._request("GET", f"/operations/stops/{stop_id}", headers=headers)

    # ─── RestockVisit ────────────────────────────────────────────────────
    def create_visit(self, payload, headers):
        return self._request("POST", "/operations/restock-visits", payload, headers)

    def list_visits(self, headers, params=None):
        return self._request("GET", "/operations/restock-visits", headers=headers, params=params)

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"/operations/restock-visits/{visit_id}", headers=headers)

    def reconcile_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/operations/restock-visits/{visit_id}/reconcile", payload, headers)

    def reject_visit(self, visit_id, headers):
        return self._request("POST", f"/operations/restock-visits/{visit_id}/reject", {}, headers)

    # ─── Sale ────────────────────────────────────────────────────────────
    def create_sale(self, payload, headers):
        return self._request("POST", "/operations/sales", payload, headers)

    def list_sales(self, headers, params=None):
        return self._request("GET", "/operations/sales", headers=headers, params=params)

    def get_sale(self, sale_id, headers):
        return self._request("GET", f"/operations/sales/{sale_id}", headers=headers)

    def void_sale(self, sale_id, headers):
        return self._request("POST", f"/operations/sales/{sale_id}/void", {}, headers)

    # ─── CommissionStatement ─────────────────────────────────────────────
    def create_statement(self, payload, headers):
        return self._request("POST", "/operations/commission-statements", payload, headers)

    def list_statements(self, headers, params=None):
        return self._request("GET", "/operations/commission-statements", headers=headers, params=params)

    def get_statement(self, statement_id, headers):
        return self._request("GET", f"/operations/commission-statements/{statement_id}", headers=headers)

    def finalize_statement(self, statement_id, headers):
        return self._request("POST", f"/operations/commission-statements/{statement_id}/finalize", {}, headers)

    # ─── ServiceTicket ───────────────────────────────────────────────────
    def create_ticket(self, machine_id, payload, headers):
        return self._request("POST", f"/operations/machines/{machine_id}/service-tickets", payload, headers)

    def list_machine_tickets(self, machine_id, headers, params=None):
        return self._request("GET", f"/operations/machines/{machine_id}/service-tickets", headers=headers, params=params)

    def list_tickets(self, headers, params=None):
        return self._request("GET", "/operations/service-tickets", headers=headers, params=params)

    def get_ticket(self, ticket_id, headers):
        return self._request("GET", f"/operations/service-tickets/{ticket_id}", headers=headers)

    def start_ticket(self, ticket_id, headers):
        return self._request("POST", f"/operations/service-tickets/{ticket_id}/start", {}, headers)

    def resolve_ticket(self, ticket_id, headers):
        return self._request("POST", f"/operations/service-tickets/{ticket_id}/resolve", {}, headers)

    def reopen_ticket(self, ticket_id, headers):
        return self._request("POST", f"/operations/service-tickets/{ticket_id}/reopen", {}, headers)


api_client = ApiClient()
