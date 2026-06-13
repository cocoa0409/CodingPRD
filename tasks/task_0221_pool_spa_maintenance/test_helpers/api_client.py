"""API client: one method per endpoint defined in the PRD (Pool & Spa Maintenance)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Customer ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def suspend_customer(self, customer_id, headers):
        return self._request("POST", f"/customers/{customer_id}/suspend", {}, headers)

    # ---- Pool ----
    def create_pool(self, payload, headers):
        return self._request("POST", "/pools", payload, headers)

    def get_pool(self, pool_id, headers):
        return self._request("GET", f"/pools/{pool_id}", headers=headers)

    def list_pools(self, headers, params=None):
        return self._request("GET", "/pools", headers=headers, params=params)

    def create_visit_log(self, pool_id, payload, headers):
        return self._request("POST", f"/pools/{pool_id}/visit-logs", payload, headers)

    # ---- ServicePlan ----
    def create_service_plan(self, payload, headers):
        return self._request("POST", "/service-plans", payload, headers)

    def get_service_plan(self, plan_id, headers):
        return self._request("GET", f"/service-plans/{plan_id}", headers=headers)

    def list_service_plans(self, headers, params=None):
        return self._request("GET", "/service-plans", headers=headers, params=params)

    def activate_service_plan(self, plan_id, headers):
        return self._request("POST", f"/service-plans/{plan_id}/activate", {}, headers)

    def cancel_service_plan(self, plan_id, headers):
        return self._request("POST", f"/service-plans/{plan_id}/cancel", {}, headers)

    # ---- RouteAssignment ----
    def create_route(self, payload, headers):
        return self._request("POST", "/routes", payload, headers)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/routes/{route_id}", headers=headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/routes", headers=headers, params=params)

    def list_route_visits(self, route_id, headers, params=None):
        return self._request("GET", f"/routes/{route_id}/visits", headers=headers, params=params)

    def dispatch_route(self, route_id, headers):
        return self._request("POST", f"/routes/{route_id}/dispatch", {}, headers)

    def close_route(self, route_id, headers):
        return self._request("POST", f"/routes/{route_id}/close", {}, headers)

    # ---- ServiceVisit ----
    def create_visit(self, payload, headers):
        return self._request("POST", "/visits", payload, headers)

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"/visits/{visit_id}", headers=headers)

    def list_visits(self, headers, params=None):
        return self._request("GET", "/visits", headers=headers, params=params)

    def complete_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/complete", payload, headers)

    def skip_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/skip", payload, headers)

    def cancel_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/cancel", {}, headers)

    def create_reading(self, visit_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/readings", payload, headers)

    def list_readings(self, visit_id, headers, params=None):
        return self._request("GET", f"/visits/{visit_id}/readings", headers=headers, params=params)

    # ---- WorkOrder ----
    def create_work_order(self, payload, headers):
        return self._request("POST", "/work-orders", payload, headers)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/work-orders/{work_order_id}", headers=headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/work-orders", headers=headers, params=params)

    def diagnose_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/diagnose", payload, headers)

    def submit_work_order_for_approval(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/submit-for-approval", {}, headers)

    def hold_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/hold", {}, headers)

    def re_diagnose_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/re-diagnose", payload, headers)

    def resolve_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/resolve", {}, headers)

    def cancel_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/cancel", {}, headers)

    # ---- SeasonalEvent ----
    def create_seasonal_event(self, pool_id, payload, headers):
        return self._request("POST", f"/pools/{pool_id}/seasonal-events", payload, headers)

    def get_seasonal_event(self, event_id, headers):
        return self._request("GET", f"/seasonal-events/{event_id}", headers=headers)

    def list_seasonal_events(self, pool_id, headers, params=None):
        return self._request("GET", f"/pools/{pool_id}/seasonal-events", headers=headers, params=params)

    def apply_seasonal_event(self, event_id, headers):
        return self._request("POST", f"/seasonal-events/{event_id}/apply", {}, headers)

    def void_seasonal_event(self, event_id, headers):
        return self._request("POST", f"/seasonal-events/{event_id}/void", {}, headers)

    # ---- Invoice ----
    def create_invoice(self, payload, headers):
        return self._request("POST", "/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/issue", {}, headers)

    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/pay", {}, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/void", {}, headers)


api_client = ApiClient()
