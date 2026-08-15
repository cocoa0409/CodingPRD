"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock (PRD §2.4) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Plants ---
    def create_plant(self, payload, headers):
        return self._request("POST", "/bakery/plants", payload, headers)

    def get_plant(self, plant_id, headers):
        return self._request("GET", f"/bakery/plants/{plant_id}", headers=headers)

    def list_plants(self, headers, params=None):
        return self._request("GET", "/bakery/plants", headers=headers, params=params)

    def close_day(self, plant_id, headers):
        return self._request("POST", f"/bakery/plants/{plant_id}/close_day", {}, headers)

    # --- Products ---
    def create_product(self, payload, headers):
        return self._request("POST", "/bakery/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/bakery/products/{product_id}", headers=headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/bakery/products", headers=headers, params=params)

    # --- Stores ---
    def create_store(self, payload, headers):
        return self._request("POST", "/bakery/stores", payload, headers)

    def get_store(self, store_id, headers):
        return self._request("GET", f"/bakery/stores/{store_id}", headers=headers)

    def list_stores(self, headers, params=None):
        return self._request("GET", "/bakery/stores", headers=headers, params=params)

    def suspend_store(self, store_id, payload, headers):
        return self._request("POST", f"/bakery/stores/{store_id}/suspend", payload, headers)

    def reinstate_store(self, store_id, headers):
        return self._request("POST", f"/bakery/stores/{store_id}/reinstate", {}, headers)

    # --- Drivers ---
    def create_driver(self, payload, headers):
        return self._request("POST", "/bakery/drivers", payload, headers)

    def get_driver(self, driver_id, headers):
        return self._request("GET", f"/bakery/drivers/{driver_id}", headers=headers)

    def list_drivers(self, headers, params=None):
        return self._request("GET", "/bakery/drivers", headers=headers, params=params)

    # --- Lines ---
    def create_line(self, payload, headers):
        return self._request("POST", "/bakery/lines", payload, headers)

    def get_line(self, line_id, headers):
        return self._request("GET", f"/bakery/lines/{line_id}", headers=headers)

    def list_lines(self, headers, params=None):
        return self._request("GET", "/bakery/lines", headers=headers, params=params)

    # --- Store orders ---
    def create_store_order(self, payload, headers):
        return self._request("POST", "/bakery/store-orders", payload, headers)

    def get_store_order(self, order_id, headers):
        return self._request("GET", f"/bakery/store-orders/{order_id}", headers=headers)

    def list_store_orders(self, headers, params=None):
        return self._request("GET", "/bakery/store-orders", headers=headers, params=params)

    def confirm_store_order(self, order_id, headers):
        return self._request("POST", f"/bakery/store-orders/{order_id}/confirm", {}, headers)

    def request_amendment(self, order_id, payload, headers):
        return self._request("POST", f"/bakery/store-orders/{order_id}/request-amendment", payload, headers)

    def accept_amendment(self, order_id, headers):
        return self._request("POST", f"/bakery/store-orders/{order_id}/accept-amendment", {}, headers)

    def reject_amendment(self, order_id, headers):
        return self._request("POST", f"/bakery/store-orders/{order_id}/reject-amendment", {}, headers)

    def lock_store_order(self, order_id, headers):
        return self._request("POST", f"/bakery/store-orders/{order_id}/lock", {}, headers)

    def cancel_store_order(self, order_id, headers):
        return self._request("POST", f"/bakery/store-orders/{order_id}/cancel", {}, headers)

    # --- Production plans ---
    def create_production_plan(self, payload, headers):
        return self._request("POST", "/bakery/production-plans", payload, headers)

    def get_production_plan(self, plan_id, headers):
        return self._request("GET", f"/bakery/production-plans/{plan_id}", headers=headers)

    def list_production_plans(self, headers, params=None):
        return self._request("GET", "/bakery/production-plans", headers=headers, params=params)

    def lock_production_plan(self, plan_id, headers):
        return self._request("POST", f"/bakery/production-plans/{plan_id}/lock", {}, headers)

    def unlock_production_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/bakery/production-plans/{plan_id}/unlock", payload, headers)

    def release_production_plan(self, plan_id, headers):
        return self._request("POST", f"/bakery/production-plans/{plan_id}/release", {}, headers)

    def reconcile_production_plan(self, plan_id, headers):
        return self._request("POST", f"/bakery/production-plans/{plan_id}/reconcile", {}, headers)

    # --- Batches ---
    def create_batch(self, payload, headers):
        return self._request("POST", "/bakery/batches", payload, headers)

    def get_batch(self, batch_id, headers):
        return self._request("GET", f"/bakery/batches/{batch_id}", headers=headers)

    def list_batches(self, headers, params=None):
        return self._request("GET", "/bakery/batches", headers=headers, params=params)

    def start_mix(self, batch_id, headers):
        return self._request("POST", f"/bakery/batches/{batch_id}/start-mix", {}, headers)

    def start_proof(self, batch_id, headers):
        return self._request("POST", f"/bakery/batches/{batch_id}/start-proof", {}, headers)

    def start_bake(self, batch_id, headers):
        return self._request("POST", f"/bakery/batches/{batch_id}/start-bake", {}, headers)

    def complete_bake(self, batch_id, headers):
        return self._request("POST", f"/bakery/batches/{batch_id}/complete-bake", {}, headers)

    def release_batch(self, batch_id, headers):
        return self._request("POST", f"/bakery/batches/{batch_id}/release", {}, headers)

    def reject_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/bakery/batches/{batch_id}/reject", payload, headers)

    def abort_batch(self, batch_id, headers):
        return self._request("POST", f"/bakery/batches/{batch_id}/abort", {}, headers)

    # --- Sanitation cycles ---
    def create_sanitation_cycle(self, payload, headers):
        return self._request("POST", "/bakery/sanitation-cycles", payload, headers)

    def get_sanitation_cycle(self, cycle_id, headers):
        return self._request("GET", f"/bakery/sanitation-cycles/{cycle_id}", headers=headers)

    def list_sanitation_cycles(self, headers, params=None):
        return self._request("GET", "/bakery/sanitation-cycles", headers=headers, params=params)

    def start_sanitation_cycle(self, cycle_id, headers):
        return self._request("POST", f"/bakery/sanitation-cycles/{cycle_id}/start", {}, headers)

    def verify_sanitation_cycle(self, cycle_id, headers):
        return self._request("POST", f"/bakery/sanitation-cycles/{cycle_id}/verify", {}, headers)

    def fail_sanitation_cycle(self, cycle_id, headers):
        return self._request("POST", f"/bakery/sanitation-cycles/{cycle_id}/fail", {}, headers)

    # --- Routes ---
    def create_route(self, payload, headers):
        return self._request("POST", "/bakery/routes", payload, headers)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/bakery/routes/{route_id}", headers=headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/bakery/routes", headers=headers, params=params)

    def start_loading(self, route_id, headers):
        return self._request("POST", f"/bakery/routes/{route_id}/start-loading", {}, headers)

    def dispatch_route(self, route_id, headers):
        return self._request("POST", f"/bakery/routes/{route_id}/dispatch", {}, headers)

    def complete_route(self, route_id, headers):
        return self._request("POST", f"/bakery/routes/{route_id}/complete", {}, headers)

    def settle_route(self, route_id, payload, headers):
        return self._request("POST", f"/bakery/routes/{route_id}/settle", payload, headers)

    def cancel_route(self, route_id, headers):
        return self._request("POST", f"/bakery/routes/{route_id}/cancel", {}, headers)

    # --- Route stops ---
    def create_route_stop(self, payload, headers):
        return self._request("POST", "/bakery/route-stops", payload, headers)

    def get_route_stop(self, stop_id, headers):
        return self._request("GET", f"/bakery/route-stops/{stop_id}", headers=headers)

    def list_route_stops(self, headers, params=None):
        return self._request("GET", "/bakery/route-stops", headers=headers, params=params)

    def deliver_route_stop(self, stop_id, payload, headers):
        return self._request("POST", f"/bakery/route-stops/{stop_id}/deliver", payload, headers)

    def skip_route_stop(self, stop_id, payload, headers):
        return self._request("POST", f"/bakery/route-stops/{stop_id}/skip", payload, headers)

    def reconcile_route_stop(self, stop_id, headers):
        return self._request("POST", f"/bakery/route-stops/{stop_id}/reconcile", {}, headers)

    # --- Stale returns ---
    def create_stale_return(self, payload, headers):
        return self._request("POST", "/bakery/stale-returns", payload, headers)

    def get_stale_return(self, return_id, headers):
        return self._request("GET", f"/bakery/stale-returns/{return_id}", headers=headers)

    def list_stale_returns(self, headers, params=None):
        return self._request("GET", "/bakery/stale-returns", headers=headers, params=params)

    def verify_stale_return(self, return_id, payload, headers):
        return self._request("POST", f"/bakery/stale-returns/{return_id}/verify", payload, headers)

    def dispute_stale_return(self, return_id, headers):
        return self._request("POST", f"/bakery/stale-returns/{return_id}/dispute", {}, headers)

    def resolve_dispute_stale_return(self, return_id, payload, headers):
        return self._request("POST", f"/bakery/stale-returns/{return_id}/resolve-dispute", payload, headers)

    def credit_stale_return(self, return_id, headers):
        return self._request("POST", f"/bakery/stale-returns/{return_id}/credit", {}, headers)

    def reverse_credit_stale_return(self, return_id, headers):
        return self._request("POST", f"/bakery/stale-returns/{return_id}/reverse-credit", {}, headers)

    def reject_stale_return(self, return_id, payload, headers):
        return self._request("POST", f"/bakery/stale-returns/{return_id}/reject", payload, headers)

    # --- Thrift sales ---
    def create_thrift_sale(self, payload, headers):
        return self._request("POST", "/bakery/thrift-sales", payload, headers)

    def get_thrift_sale(self, sale_id, headers):
        return self._request("GET", f"/bakery/thrift-sales/{sale_id}", headers=headers)

    def list_thrift_sales(self, headers, params=None):
        return self._request("GET", "/bakery/thrift-sales", headers=headers, params=params)

    def void_thrift_sale(self, sale_id, headers):
        return self._request("POST", f"/bakery/thrift-sales/{sale_id}/void", {}, headers)

    # --- Ingredient indices ---
    def create_ingredient_index(self, payload, headers):
        return self._request("POST", "/bakery/ingredient-indices", payload, headers)

    def get_ingredient_index(self, index_id, headers):
        return self._request("GET", f"/bakery/ingredient-indices/{index_id}", headers=headers)

    def list_ingredient_indices(self, headers, params=None):
        return self._request("GET", "/bakery/ingredient-indices", headers=headers, params=params)

    def publish_ingredient_index(self, index_id, payload, headers):
        return self._request("POST", f"/bakery/ingredient-indices/{index_id}/publish", payload, headers)

    # --- Surcharge schedules ---
    def create_surcharge_schedule(self, payload, headers):
        return self._request("POST", "/bakery/surcharge-schedules", payload, headers)

    def get_surcharge_schedule(self, schedule_id, headers):
        return self._request("GET", f"/bakery/surcharge-schedules/{schedule_id}", headers=headers)

    def list_surcharge_schedules(self, headers, params=None):
        return self._request("GET", "/bakery/surcharge-schedules", headers=headers, params=params)


api_client = ApiClient()
