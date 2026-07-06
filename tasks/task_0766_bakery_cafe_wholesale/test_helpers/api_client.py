"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --------------------------------------------------------------- logical clock
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # -------------------------------------------------------------------- products
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def discontinue_product(self, product_id, headers):
        return self._request("POST", f"/products/{product_id}/discontinue", {}, headers)

    # ----------------------------------------------------------------------- ovens
    def create_oven(self, payload, headers):
        return self._request("POST", "/ovens", payload, headers)

    def list_ovens(self, headers, params=None):
        return self._request("GET", "/ovens", headers=headers, params=params)

    # ------------------------------------------------------------------- bake plans
    def create_bake_plan(self, payload, headers):
        return self._request("POST", "/bake-plans", payload, headers)

    def get_bake_plan(self, plan_id, headers):
        return self._request("GET", f"/bake-plans/{plan_id}", headers=headers)

    def add_bake_plan_line(self, plan_id, payload, headers):
        return self._request("POST", f"/bake-plans/{plan_id}/lines", payload, headers)

    def list_bake_plan_lines(self, plan_id, headers, params=None):
        return self._request("GET", f"/bake-plans/{plan_id}/lines",
                             headers=headers, params=params)

    def commit_bake_plan(self, plan_id, headers):
        return self._request("POST", f"/bake-plans/{plan_id}/commit", {}, headers)

    def reconcile_bake_plan(self, plan_id, headers):
        return self._request("POST", f"/bake-plans/{plan_id}/reconcile", {}, headers)

    def close_bake_plan(self, plan_id, headers):
        return self._request("POST", f"/bake-plans/{plan_id}/close", {}, headers)

    # -------------------------------------------------------------- bake plan lines
    def get_bake_plan_line(self, line_id, headers):
        return self._request("GET", f"/bake-plan-lines/{line_id}", headers=headers)

    def list_all_bake_plan_lines(self, headers, params=None):
        return self._request("GET", "/bake-plan-lines", headers=headers, params=params)

    # -------------------------------------------------------------------- bake lots
    def create_bake_lot(self, payload, headers):
        return self._request("POST", "/bake-lots", payload, headers)

    def get_bake_lot(self, lot_id, headers):
        return self._request("GET", f"/bake-lots/{lot_id}", headers=headers)

    def list_bake_lots(self, headers, params=None):
        return self._request("GET", "/bake-lots", headers=headers, params=params)

    def list_lot_retail_sales(self, lot_id, headers, params=None):
        return self._request("GET", f"/bake-lots/{lot_id}/retail-sales",
                             headers=headers, params=params)

    def markdown_bake_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/bake-lots/{lot_id}/markdown", payload, headers)

    def expire_bake_lot(self, lot_id, headers):
        return self._request("POST", f"/bake-lots/{lot_id}/expire", {}, headers)

    # ----------------------------------------------------------------- retail sales
    def create_retail_sale(self, payload, headers):
        return self._request("POST", "/retail-sales", payload, headers)

    # ----------------------------------------------------------- wholesale accounts
    def create_wholesale_account(self, payload, headers):
        return self._request("POST", "/wholesale-accounts", payload, headers)

    def get_wholesale_account(self, account_id, headers):
        return self._request("GET", f"/wholesale-accounts/{account_id}", headers=headers)

    def suspend_account(self, account_id, headers):
        return self._request("POST", f"/wholesale-accounts/{account_id}/suspend", {}, headers)

    def close_account(self, account_id, headers):
        return self._request("POST", f"/wholesale-accounts/{account_id}/close", {}, headers)

    def get_statement(self, account_id, delivery_date, headers):
        return self._request("GET", f"/wholesale-accounts/{account_id}/statement",
                             headers=headers, params={"delivery_date": delivery_date})

    # --------------------------------------------------------------- standing orders
    def create_standing_order(self, payload, headers):
        return self._request("POST", "/standing-orders", payload, headers)

    def get_standing_order(self, so_id, headers):
        return self._request("GET", f"/standing-orders/{so_id}", headers=headers)

    def list_standing_orders(self, headers, params=None):
        return self._request("GET", "/standing-orders", headers=headers, params=params)

    def pause_standing_order(self, so_id, headers):
        return self._request("POST", f"/standing-orders/{so_id}/pause", {}, headers)

    def resume_standing_order(self, so_id, headers):
        return self._request("POST", f"/standing-orders/{so_id}/resume", {}, headers)

    def cancel_standing_order(self, so_id, headers):
        return self._request("POST", f"/standing-orders/{so_id}/cancel", {}, headers)

    # --------------------------------------------------------------- delivery orders
    def create_delivery_order(self, payload, headers):
        return self._request("POST", "/delivery-orders", payload, headers)

    def get_delivery_order(self, order_id, headers):
        return self._request("GET", f"/delivery-orders/{order_id}", headers=headers)

    def list_delivery_orders(self, headers, params=None):
        return self._request("GET", "/delivery-orders", headers=headers, params=params)

    def pack_delivery_order(self, order_id, headers):
        return self._request("POST", f"/delivery-orders/{order_id}/pack", {}, headers)

    def deliver_delivery_order(self, order_id, headers):
        return self._request("POST", f"/delivery-orders/{order_id}/deliver", {}, headers)

    def pay_delivery_order(self, order_id, payload, headers):
        return self._request("POST", f"/delivery-orders/{order_id}/payments", payload, headers)

    def cancel_delivery_order(self, order_id, headers):
        return self._request("POST", f"/delivery-orders/{order_id}/cancel", {}, headers)

    # --------------------------------------------------------------- delivery routes
    def create_delivery_route(self, payload, headers):
        return self._request("POST", "/delivery-routes", payload, headers)

    def get_delivery_route(self, route_id, headers):
        return self._request("GET", f"/delivery-routes/{route_id}", headers=headers)

    def dispatch_route(self, route_id, headers):
        return self._request("POST", f"/delivery-routes/{route_id}/dispatch", {}, headers)

    def cancel_route(self, route_id, headers):
        return self._request("POST", f"/delivery-routes/{route_id}/cancel", {}, headers)

    def add_route_stop(self, route_id, payload, headers):
        return self._request("POST", f"/delivery-routes/{route_id}/stops", payload, headers)

    def list_route_stops_for_route(self, route_id, headers, params=None):
        return self._request("GET", f"/delivery-routes/{route_id}/stops",
                             headers=headers, params=params)

    # ------------------------------------------------------------------ route stops
    def get_route_stop(self, stop_id, headers):
        return self._request("GET", f"/route-stops/{stop_id}", headers=headers)

    def list_route_stops(self, headers, params=None):
        return self._request("GET", "/route-stops", headers=headers, params=params)

    def complete_route_stop(self, stop_id, headers):
        return self._request("POST", f"/route-stops/{stop_id}/complete", {}, headers)


api_client = ApiClient()
