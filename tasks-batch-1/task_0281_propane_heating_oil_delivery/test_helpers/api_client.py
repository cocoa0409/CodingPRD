"""API client: one method per endpoint defined in the PRD.

Subclasses GenericApiClient; the base _request() handles the envelope, headers,
and transport. All paths are mounted at the server root.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- System clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- Account ---
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/accounts", headers=headers, params=params)

    def suspend_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/suspend", headers=headers)

    def reactivate_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/reactivate", headers=headers)

    def close_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/close", headers=headers)

    # --- PricePlan ---
    def create_price_plan(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/price-plans", payload, headers)

    def get_price_plan(self, plan_id, headers):
        return self._request("GET", f"/price-plans/{plan_id}", headers=headers)

    def list_price_plans(self, headers, params=None):
        return self._request("GET", "/price-plans", headers=headers, params=params)

    def activate_price_plan(self, account_id, plan_id, headers):
        return self._request("POST",
                             f"/accounts/{account_id}/price-plans/{plan_id}/activate",
                             headers=headers)

    # --- Tank ---
    def create_tank(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/tanks", payload, headers)

    def get_tank(self, tank_id, headers):
        return self._request("GET", f"/tanks/{tank_id}", headers=headers)

    def list_tanks(self, headers, params=None):
        return self._request("GET", "/tanks", headers=headers, params=params)

    def lockout_tank(self, tank_id, headers):
        return self._request("POST", f"/tanks/{tank_id}/lockout", headers=headers)

    def decommission_tank(self, tank_id, headers):
        return self._request("POST", f"/tanks/{tank_id}/decommission", headers=headers)

    def evaluate_reorder(self, tank_id, headers):
        return self._request("POST", f"/tanks/{tank_id}/evaluate-reorder", headers=headers)

    def generate_auto_order(self, tank_id, headers):
        return self._request("POST", f"/tanks/{tank_id}/generate-auto-order", headers=headers)

    # --- TankMonitorReading ---
    def create_reading(self, tank_id, payload, headers):
        return self._request("POST", f"/tanks/{tank_id}/readings", payload, headers)

    def get_reading(self, reading_id, headers):
        return self._request("GET", f"/tank-readings/{reading_id}", headers=headers)

    def list_readings(self, headers, params=None):
        return self._request("GET", "/tank-readings", headers=headers, params=params)

    # --- DegreeDayReading ---
    def create_degree_day_reading(self, payload, headers):
        return self._request("POST", "/degree-day-readings", payload, headers)

    def list_degree_day_readings(self, headers, params=None):
        return self._request("GET", "/degree-day-readings", headers=headers, params=params)

    # --- MarketPrice ---
    def create_market_price(self, payload, headers):
        return self._request("POST", "/market-prices", payload, headers)

    def get_market_price(self, market_price_id, headers):
        return self._request("GET", f"/market-prices/{market_price_id}", headers=headers)

    def list_market_prices(self, headers, params=None):
        return self._request("GET", "/market-prices", headers=headers, params=params)

    # --- TankLease ---
    def create_lease(self, tank_id, payload, headers):
        return self._request("POST", f"/tanks/{tank_id}/leases", payload, headers)

    def get_lease(self, lease_id, headers):
        return self._request("GET", f"/tank-leases/{lease_id}", headers=headers)

    def list_leases(self, headers, params=None):
        return self._request("GET", "/tank-leases", headers=headers, params=params)

    def terminate_lease(self, tank_id, lease_id, headers):
        return self._request("POST", f"/tanks/{tank_id}/leases/{lease_id}/terminate",
                             headers=headers)

    # --- SafetyInspection ---
    def create_inspection(self, tank_id, payload, headers):
        return self._request("POST", f"/tanks/{tank_id}/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/safety-inspections/{inspection_id}", headers=headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/safety-inspections", headers=headers, params=params)

    # --- Truck ---
    def create_truck(self, payload, headers):
        return self._request("POST", "/trucks", payload, headers)

    def get_truck(self, truck_id, headers):
        return self._request("GET", f"/trucks/{truck_id}", headers=headers)

    def list_trucks(self, headers, params=None):
        return self._request("GET", "/trucks", headers=headers, params=params)

    # --- DeliveryRoute ---
    def create_route(self, truck_id, payload, headers):
        return self._request("POST", f"/trucks/{truck_id}/routes", payload, headers)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/routes/{route_id}", headers=headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/routes", headers=headers, params=params)

    def dispatch_route(self, truck_id, route_id, headers):
        return self._request("POST", f"/trucks/{truck_id}/routes/{route_id}/dispatch",
                             headers=headers)

    def cancel_route(self, truck_id, route_id, headers):
        return self._request("POST", f"/trucks/{truck_id}/routes/{route_id}/cancel",
                             headers=headers)

    # --- DeliveryOrder ---
    def create_order(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/delivery-orders",
                             payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/delivery-orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/delivery-orders", headers=headers, params=params)

    def assign_order(self, account_id, order_id, payload, headers):
        return self._request("POST",
                             f"/accounts/{account_id}/delivery-orders/{order_id}/assign",
                             payload, headers)

    def unassign_order(self, account_id, order_id, headers):
        return self._request("POST",
                             f"/accounts/{account_id}/delivery-orders/{order_id}/unassign",
                             headers=headers)

    def hold_order(self, account_id, order_id, headers):
        return self._request("POST",
                             f"/accounts/{account_id}/delivery-orders/{order_id}/hold",
                             headers=headers)

    def resume_order(self, account_id, order_id, headers):
        return self._request("POST",
                             f"/accounts/{account_id}/delivery-orders/{order_id}/resume",
                             headers=headers)

    def deliver_order(self, account_id, order_id, payload, headers):
        return self._request("POST",
                             f"/accounts/{account_id}/delivery-orders/{order_id}/deliver",
                             payload, headers)

    def cancel_order(self, account_id, order_id, headers):
        return self._request("POST",
                             f"/accounts/{account_id}/delivery-orders/{order_id}/cancel",
                             headers=headers)

    def reverse_order(self, account_id, order_id, payload, headers):
        return self._request("POST",
                             f"/accounts/{account_id}/delivery-orders/{order_id}/reverse",
                             payload, headers)

    # --- BudgetPlan ---
    def create_budget_plan(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/budget-plans", payload, headers)

    def get_budget_plan(self, budget_plan_id, headers):
        return self._request("GET", f"/budget-plans/{budget_plan_id}", headers=headers)

    def list_budget_plans(self, headers, params=None):
        return self._request("GET", "/budget-plans", headers=headers, params=params)

    def post_installment(self, account_id, budget_plan_id, headers):
        return self._request("POST",
                             f"/accounts/{account_id}/budget-plans/{budget_plan_id}/post-installment",
                             headers=headers)

    def reconcile_budget_plan(self, account_id, budget_plan_id, headers):
        return self._request("POST",
                             f"/accounts/{account_id}/budget-plans/{budget_plan_id}/reconcile",
                             headers=headers)


api_client = ApiClient()
