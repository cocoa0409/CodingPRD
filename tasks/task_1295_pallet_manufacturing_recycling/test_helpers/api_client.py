"""API client: one method per endpoint defined in the PRD."""
import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    def _request(self, method, path, payload=None, headers=None, params=None):
        """Transport-level resilience against the per-test server restart.

        The harness SIGKILLs and respawns the server between tests; this
        session's pooled keep-alive connections then point at the dead
        server, and the first request of the next test can fail with a
        bare ConnectionError (RST on a stale pooled socket). That request
        could not have reached the server (the kill happened before the
        test began), so dropping the pool and retrying exactly once is
        side-effect-free. Only transport failures are retried -- a
        completed HTTP response (including error envelopes) is returned
        untouched, so no assertion is ever weakened.
        """
        try:
            return super()._request(method, path, payload=payload,
                                    headers=headers, params=params)
        except requests.ConnectionError:
            self.session.close()
            self.session = requests.Session()
            return super()._request(method, path, payload=payload,
                                    headers=headers, params=params)


    # --- PalletSpec ---
    def create_spec(self, payload, headers):
        return self._request("POST", "/pallet-ops/specs", payload, headers)

    def list_specs(self, headers, params=None):
        return self._request("GET", "/pallet-ops/specs", headers=headers,
                             params=params)

    def get_spec(self, spec_id, headers):
        return self._request("GET", f"/pallet-ops/specs/{spec_id}",
                             headers=headers)

    def activate_spec(self, spec_id, headers):
        return self._request("POST", f"/pallet-ops/specs/{spec_id}/activate",
                             headers=headers)

    def retire_spec(self, spec_id, headers):
        return self._request("POST", f"/pallet-ops/specs/{spec_id}/retire",
                             headers=headers)

    # --- LumberPriceIndex / SeasonalPriceIndex ---
    def create_lumber_index(self, payload, headers):
        return self._request("POST", "/pallet-ops/lumber-index", payload,
                             headers)

    def list_lumber_index(self, headers, params=None):
        return self._request("GET", "/pallet-ops/lumber-index",
                             headers=headers, params=params)

    def create_seasonal_index(self, payload, headers):
        return self._request("POST", "/pallet-ops/seasonal-index", payload,
                             headers)

    def list_seasonal_index(self, headers, params=None):
        return self._request("GET", "/pallet-ops/seasonal-index",
                             headers=headers, params=params)

    # --- CorePurchaseBatch / CoreUnit ---
    def create_core_batch(self, payload, headers):
        return self._request("POST", "/pallet-ops/core-batches", payload,
                             headers)

    def list_core_batches(self, headers, params=None):
        return self._request("GET", "/pallet-ops/core-batches",
                             headers=headers, params=params)

    def get_core_batch(self, batch_id, headers):
        return self._request("GET", f"/pallet-ops/core-batches/{batch_id}",
                             headers=headers)

    def begin_sorting(self, batch_id, headers):
        return self._request(
            "POST", f"/pallet-ops/core-batches/{batch_id}/begin-sorting",
            headers=headers)

    def finish_sorting(self, batch_id, headers):
        return self._request(
            "POST", f"/pallet-ops/core-batches/{batch_id}/finish-sorting",
            headers=headers)

    def close_batch(self, batch_id, headers):
        return self._request(
            "POST", f"/pallet-ops/core-batches/{batch_id}/close",
            headers=headers)

    def create_core_unit(self, payload, headers):
        return self._request("POST", "/pallet-ops/core-units", payload,
                             headers)

    def list_core_units(self, headers, params=None):
        return self._request("GET", "/pallet-ops/core-units", headers=headers,
                             params=params)

    def get_core_unit(self, core_id, headers):
        return self._request("GET", f"/pallet-ops/core-units/{core_id}",
                             headers=headers)

    def sort_core(self, core_id, payload, headers):
        return self._request("POST", f"/pallet-ops/core-units/{core_id}/sort",
                             payload, headers)

    # --- RepairWorkOrder ---
    def create_repair_order(self, payload, headers):
        return self._request("POST", "/pallet-ops/repair-orders", payload,
                             headers)

    def list_repair_orders(self, headers, params=None):
        return self._request("GET", "/pallet-ops/repair-orders",
                             headers=headers, params=params)

    def get_repair_order(self, wo_id, headers):
        return self._request("GET", f"/pallet-ops/repair-orders/{wo_id}",
                             headers=headers)

    def start_repair_order(self, wo_id, headers):
        return self._request(
            "POST", f"/pallet-ops/repair-orders/{wo_id}/start",
            headers=headers)

    def complete_repair_order(self, wo_id, payload, headers):
        return self._request(
            "POST", f"/pallet-ops/repair-orders/{wo_id}/complete", payload,
            headers)

    def abort_repair_order(self, wo_id, headers):
        return self._request(
            "POST", f"/pallet-ops/repair-orders/{wo_id}/abort",
            headers=headers)

    # --- InventoryLot / HeatTreatmentRun ---
    def create_inventory_lot(self, payload, headers):
        return self._request("POST", "/pallet-ops/inventory-lots", payload,
                             headers)

    def list_inventory_lots(self, headers, params=None):
        return self._request("GET", "/pallet-ops/inventory-lots",
                             headers=headers, params=params)

    def get_inventory_lot(self, lot_id, headers):
        return self._request("GET", f"/pallet-ops/inventory-lots/{lot_id}",
                             headers=headers)

    def quarantine_lot(self, lot_id, headers):
        return self._request(
            "POST", f"/pallet-ops/inventory-lots/{lot_id}/quarantine",
            headers=headers)

    def create_ht_run(self, payload, headers):
        return self._request("POST", "/pallet-ops/ht-runs", payload, headers)

    def list_ht_runs(self, headers, params=None):
        return self._request("GET", "/pallet-ops/ht-runs", headers=headers,
                             params=params)

    def get_ht_run(self, run_id, headers):
        return self._request("GET", f"/pallet-ops/ht-runs/{run_id}",
                             headers=headers)

    def assign_lot_to_run(self, run_id, payload, headers):
        return self._request(
            "POST", f"/pallet-ops/ht-runs/{run_id}/assign-lot", payload,
            headers)

    def start_ht_run(self, run_id, headers):
        return self._request("POST", f"/pallet-ops/ht-runs/{run_id}/start",
                             headers=headers)

    def complete_ht_run(self, run_id, headers):
        return self._request("POST",
                             f"/pallet-ops/ht-runs/{run_id}/complete",
                             headers=headers)

    def fail_ht_run(self, run_id, headers):
        return self._request("POST", f"/pallet-ops/ht-runs/{run_id}/fail",
                             headers=headers)

    # --- Customer / SalesOrder / OrderLine / PoolReturn ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/pallet-ops/customers", payload,
                             headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/pallet-ops/customers", headers=headers,
                             params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/pallet-ops/customers/{customer_id}",
                             headers=headers)

    def suspend_customer(self, customer_id, headers):
        return self._request(
            "POST", f"/pallet-ops/customers/{customer_id}/suspend",
            headers=headers)

    def reinstate_customer(self, customer_id, headers):
        return self._request(
            "POST", f"/pallet-ops/customers/{customer_id}/reinstate",
            headers=headers)

    def close_customer(self, customer_id, headers):
        return self._request(
            "POST", f"/pallet-ops/customers/{customer_id}/close",
            headers=headers)

    def create_order(self, payload, headers):
        return self._request("POST", "/pallet-ops/orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/pallet-ops/orders", headers=headers,
                             params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/pallet-ops/orders/{order_id}",
                             headers=headers)

    def add_order_line(self, order_id, payload, headers):
        return self._request("POST", f"/pallet-ops/orders/{order_id}/lines",
                             payload, headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/pallet-ops/order-lines", headers=headers,
                             params=params)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/pallet-ops/order-lines/{line_id}",
                             headers=headers)

    def confirm_order(self, order_id, payload, headers):
        return self._request("POST", f"/pallet-ops/orders/{order_id}/confirm",
                             payload, headers)

    def allocate_order(self, order_id, payload, headers):
        return self._request("POST",
                             f"/pallet-ops/orders/{order_id}/allocate",
                             payload, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/pallet-ops/orders/{order_id}/cancel",
                             headers=headers)

    def record_payment(self, order_id, payload, headers):
        return self._request(
            "POST", f"/pallet-ops/orders/{order_id}/record-payment", payload,
            headers)

    def create_pool_return(self, payload, headers):
        return self._request("POST", "/pallet-ops/pool-returns", payload,
                             headers)

    def list_pool_returns(self, headers, params=None):
        return self._request("GET", "/pallet-ops/pool-returns",
                             headers=headers, params=params)

    def get_pool_return(self, return_id, headers):
        return self._request("GET", f"/pallet-ops/pool-returns/{return_id}",
                             headers=headers)

    def grade_pool_return(self, return_id, payload, headers):
        return self._request(
            "POST", f"/pallet-ops/pool-returns/{return_id}/grade", payload,
            headers)

    def credit_pool_return(self, return_id, headers):
        return self._request(
            "POST", f"/pallet-ops/pool-returns/{return_id}/credit",
            headers=headers)

    def dispute_pool_return(self, return_id, headers):
        return self._request(
            "POST", f"/pallet-ops/pool-returns/{return_id}/dispute",
            headers=headers)

    # --- DeliveryRoute / RouteStop ---
    def create_route(self, payload, headers):
        return self._request("POST", "/pallet-ops/routes", payload, headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/pallet-ops/routes", headers=headers,
                             params=params)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/pallet-ops/routes/{route_id}",
                             headers=headers)

    def add_route_stop(self, route_id, payload, headers):
        return self._request("POST", f"/pallet-ops/routes/{route_id}/stops",
                             payload, headers)

    def list_route_stops(self, headers, params=None):
        return self._request("GET", "/pallet-ops/route-stops", headers=headers,
                             params=params)

    def get_route_stop(self, stop_id, headers):
        return self._request("GET", f"/pallet-ops/route-stops/{stop_id}",
                             headers=headers)

    def dispatch_route(self, route_id, payload, headers):
        return self._request("POST",
                             f"/pallet-ops/routes/{route_id}/dispatch",
                             payload, headers)

    def arrive_stop(self, stop_id, headers):
        return self._request("POST",
                             f"/pallet-ops/route-stops/{stop_id}/arrive",
                             headers=headers)

    def complete_stop(self, stop_id, headers):
        return self._request("POST",
                             f"/pallet-ops/route-stops/{stop_id}/complete",
                             headers=headers)

    def skip_stop(self, stop_id, headers):
        return self._request("POST",
                             f"/pallet-ops/route-stops/{stop_id}/skip",
                             headers=headers)

    def close_route(self, route_id, payload, headers):
        return self._request("POST", f"/pallet-ops/routes/{route_id}/close",
                             payload, headers)

    def cancel_route(self, route_id, headers):
        return self._request("POST", f"/pallet-ops/routes/{route_id}/cancel",
                             headers=headers)

    # --- GrindingBatch ---
    def create_grinding_batch(self, payload, headers):
        return self._request("POST", "/pallet-ops/grinding-batches", payload,
                             headers)

    def list_grinding_batches(self, headers, params=None):
        return self._request("GET", "/pallet-ops/grinding-batches",
                             headers=headers, params=params)

    def get_grinding_batch(self, batch_id, headers):
        return self._request("GET",
                             f"/pallet-ops/grinding-batches/{batch_id}",
                             headers=headers)

    def start_grinding_batch(self, batch_id, headers):
        return self._request(
            "POST", f"/pallet-ops/grinding-batches/{batch_id}/start",
            headers=headers)

    def complete_grinding_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/pallet-ops/grinding-batches/{batch_id}/complete",
            payload, headers)

    # --- Logical clock (test-driving admin) ---
    def set_clock(self, payload, headers):
        return self._request(
            "POST", "/pallet-ops/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
