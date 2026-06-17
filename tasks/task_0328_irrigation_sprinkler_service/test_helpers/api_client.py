"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------- Customer ----------
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    def suspend_customer(self, customer_id, headers):
        return self._request("POST", f"/customers/{customer_id}/suspend", headers=headers)

    # ---------- Technician ----------
    def create_technician(self, payload, headers):
        return self._request("POST", "/technicians", payload, headers)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"/technicians/{technician_id}", headers=headers)

    def list_technicians(self, headers, params=None):
        return self._request("GET", "/technicians", headers=headers, params=params)

    # ---------- Property ----------
    def create_property(self, payload, headers):
        return self._request("POST", "/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/properties/{property_id}", headers=headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/properties", headers=headers, params=params)

    # ---------- IrrigationSystem ----------
    def create_system(self, payload, headers):
        return self._request("POST", "/irrigation-systems", payload, headers)

    def get_system(self, system_id, headers):
        return self._request("GET", f"/irrigation-systems/{system_id}", headers=headers)

    def list_systems(self, headers, params=None):
        return self._request("GET", "/irrigation-systems", headers=headers, params=params)

    def get_blowout_quote(self, system_id, headers):
        return self._request("GET", f"/irrigation-systems/{system_id}/blowout-quote", headers=headers)

    def decommission_system(self, system_id, headers):
        return self._request("POST", f"/irrigation-systems/{system_id}/decommission", headers=headers)

    # ---------- Zone ----------
    def create_zone(self, payload, headers):
        return self._request("POST", "/zones", payload, headers)

    def get_zone(self, zone_id, headers):
        return self._request("GET", f"/zones/{zone_id}", headers=headers)

    def list_zones(self, headers, params=None):
        return self._request("GET", "/zones", headers=headers, params=params)

    # ---------- ControllerProgram ----------
    def create_program(self, payload, headers):
        return self._request("POST", "/controller-programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/controller-programs/{program_id}", headers=headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/controller-programs", headers=headers, params=params)

    def activate_program(self, program_id, headers):
        return self._request("POST", f"/controller-programs/{program_id}/activate", headers=headers)

    # ---------- ServiceQuote ----------
    def create_quote(self, payload, headers):
        return self._request("POST", "/service-quotes", payload, headers)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/service-quotes/{quote_id}", headers=headers)

    def list_quotes(self, headers, params=None):
        return self._request("GET", "/service-quotes", headers=headers, params=params)

    def send_quote(self, quote_id, headers):
        return self._request("POST", f"/service-quotes/{quote_id}/send", headers=headers)

    def revise_quote_line_items(self, quote_id, payload, headers):
        return self._request("PATCH", f"/service-quotes/{quote_id}/line-items", payload, headers)

    def request_changes_quote(self, quote_id, headers):
        return self._request("POST", f"/service-quotes/{quote_id}/request-changes", headers=headers)

    def approve_quote(self, quote_id, headers):
        return self._request("POST", f"/service-quotes/{quote_id}/approve", headers=headers)

    def reject_quote(self, quote_id, headers):
        return self._request("POST", f"/service-quotes/{quote_id}/reject", headers=headers)

    # ---------- WorkOrder ----------
    def create_work_order(self, payload, headers):
        return self._request("POST", "/work-orders", payload, headers)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/work-orders/{work_order_id}", headers=headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/work-orders", headers=headers, params=params)

    def depart_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/depart", headers=headers)

    def arrive_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/arrive", headers=headers)

    def complete_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/complete", payload, headers)

    def fail_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/fail", headers=headers)

    def cancel_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/cancel", headers=headers)

    # ---------- MaintenancePlan ----------
    def create_plan(self, payload, headers):
        return self._request("POST", "/maintenance-plans", payload, headers)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/maintenance-plans/{plan_id}", headers=headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/maintenance-plans", headers=headers, params=params)

    def pause_plan(self, plan_id, headers):
        return self._request("POST", f"/maintenance-plans/{plan_id}/pause", headers=headers)

    def resume_plan(self, plan_id, headers):
        return self._request("POST", f"/maintenance-plans/{plan_id}/resume", headers=headers)

    def cancel_plan(self, plan_id, headers):
        return self._request("POST", f"/maintenance-plans/{plan_id}/cancel", headers=headers)

    # ---------- BackflowTest ----------
    def create_backflow_test(self, payload, headers):
        return self._request("POST", "/backflow-tests", payload, headers)

    def get_backflow_test(self, test_id, headers):
        return self._request("GET", f"/backflow-tests/{test_id}", headers=headers)

    def list_backflow_tests(self, headers, params=None):
        return self._request("GET", "/backflow-tests", headers=headers, params=params)

    # ---------- Route ----------
    def create_route(self, payload, headers):
        return self._request("POST", "/routes", payload, headers)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/routes/{route_id}", headers=headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/routes", headers=headers, params=params)

    def dispatch_route(self, route_id, headers):
        return self._request("POST", f"/routes/{route_id}/dispatch", headers=headers)

    def close_route(self, route_id, headers):
        return self._request("POST", f"/routes/{route_id}/close", headers=headers)

    # ---------- RouteStop ----------
    def create_route_stop(self, payload, headers):
        return self._request("POST", "/route-stops", payload, headers)

    def get_route_stop(self, stop_id, headers):
        return self._request("GET", f"/route-stops/{stop_id}", headers=headers)

    def list_route_stops(self, headers, params=None):
        return self._request("GET", "/route-stops", headers=headers, params=params)


api_client = ApiClient()
