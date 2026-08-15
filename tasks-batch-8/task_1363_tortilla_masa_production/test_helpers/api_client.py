"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD §2.4) ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/plant/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- Ingredient lots ---
    def create_ingredient_lot(self, payload, headers):
        return self._request("POST", "/plant/ingredient-lots", payload, headers)

    def list_ingredient_lots(self, headers, params=None):
        return self._request("GET", "/plant/ingredient-lots", headers=headers, params=params)

    def get_ingredient_lot(self, lot_id, headers):
        return self._request("GET", f"/plant/ingredient-lots/{lot_id}", headers=headers)

    def condition_ingredient_lot(self, lot_id, payload, headers):
        return self._request(
            "POST", f"/plant/ingredient-lots/{lot_id}/condition", payload, headers
        )

    def list_lot_batches(self, lot_id, headers, params=None):
        return self._request(
            "GET", f"/plant/ingredient-lots/{lot_id}/batches", headers=headers, params=params
        )

    # --- Nixtamal batches ---
    def create_nixtamal_batch(self, payload, headers):
        return self._request("POST", "/plant/nixtamal-batches", payload, headers)

    def get_nixtamal_batch(self, batch_id, headers):
        return self._request("GET", f"/plant/nixtamal-batches/{batch_id}", headers=headers)

    def start_cook(self, batch_id, headers):
        return self._request(
            "POST", f"/plant/nixtamal-batches/{batch_id}/start-cook", {}, headers
        )

    def start_steep(self, batch_id, headers):
        return self._request(
            "POST", f"/plant/nixtamal-batches/{batch_id}/start-steep", {}, headers
        )

    def evaluate_batch(self, batch_id, decision, headers):
        return self._request(
            "POST",
            f"/plant/nixtamal-batches/{batch_id}/evaluate",
            {"decision": decision},
            headers,
        )

    def mill_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/plant/nixtamal-batches/{batch_id}/mill", payload, headers
        )

    def quarantine_batch(self, batch_id, headers):
        return self._request(
            "POST", f"/plant/nixtamal-batches/{batch_id}/quarantine", {}, headers
        )

    def release_quarantine(self, batch_id, headers):
        return self._request(
            "POST", f"/plant/nixtamal-batches/{batch_id}/release-quarantine", {}, headers
        )

    def list_batch_allocations(self, batch_id, headers, params=None):
        return self._request(
            "GET",
            f"/plant/nixtamal-batches/{batch_id}/allocations",
            headers=headers,
            params=params,
        )

    # --- Products ---
    def create_product(self, payload, headers):
        return self._request("POST", "/plant/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/plant/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/plant/products/{product_id}", headers=headers)

    def discontinue_product(self, product_id, headers):
        return self._request(
            "POST", f"/plant/products/{product_id}/discontinue", {}, headers
        )

    def list_product_runs(self, product_id, headers, params=None):
        return self._request(
            "GET", f"/plant/products/{product_id}/runs", headers=headers, params=params
        )

    # --- Production lines ---
    def create_line(self, payload, headers):
        return self._request("POST", "/plant/lines", payload, headers)

    def list_lines(self, headers, params=None):
        return self._request("GET", "/plant/lines", headers=headers, params=params)

    def get_line(self, line_id, headers):
        return self._request("GET", f"/plant/lines/{line_id}", headers=headers)

    def set_line_status(self, line_id, line_status, headers):
        return self._request(
            "POST",
            f"/plant/lines/{line_id}/set-status",
            {"line_status": line_status},
            headers,
        )

    def list_line_runs(self, line_id, headers, params=None):
        return self._request(
            "GET", f"/plant/lines/{line_id}/runs", headers=headers, params=params
        )

    def list_line_changeovers(self, line_id, headers, params=None):
        return self._request(
            "GET", f"/plant/lines/{line_id}/changeovers", headers=headers, params=params
        )

    # --- Production runs ---
    def create_run(self, payload, headers):
        return self._request("POST", "/plant/runs", payload, headers)

    def get_run(self, run_id, headers):
        return self._request("GET", f"/plant/runs/{run_id}", headers=headers)

    def schedule_run(self, run_id, headers):
        return self._request("POST", f"/plant/runs/{run_id}/schedule", {}, headers)

    def start_run(self, run_id, headers):
        return self._request("POST", f"/plant/runs/{run_id}/start", {}, headers)

    def complete_run(self, run_id, headers):
        return self._request("POST", f"/plant/runs/{run_id}/complete", {}, headers)

    def cancel_run(self, run_id, headers):
        return self._request("POST", f"/plant/runs/{run_id}/cancel", {}, headers)

    def qc_hold_run(self, run_id, headers):
        return self._request("POST", f"/plant/runs/{run_id}/qc-hold", {}, headers)

    def qc_release_run(self, run_id, headers):
        return self._request("POST", f"/plant/runs/{run_id}/qc-release", {}, headers)

    def list_run_allocations(self, run_id, headers, params=None):
        return self._request(
            "GET", f"/plant/runs/{run_id}/allocations", headers=headers, params=params
        )

    def list_run_pack_orders(self, run_id, headers, params=None):
        return self._request(
            "GET", f"/plant/runs/{run_id}/pack-orders", headers=headers, params=params
        )

    def list_run_changeovers(self, run_id, headers, params=None):
        return self._request(
            "GET", f"/plant/runs/{run_id}/changeovers", headers=headers, params=params
        )

    # --- Batch allocations ---
    def create_allocation(self, payload, headers):
        return self._request("POST", "/plant/allocations", payload, headers)

    def get_allocation(self, allocation_id, headers):
        return self._request("GET", f"/plant/allocations/{allocation_id}", headers=headers)

    def release_allocation(self, allocation_id, headers):
        return self._request(
            "POST", f"/plant/allocations/{allocation_id}/release", {}, headers
        )

    def consume_allocation(self, allocation_id, headers):
        return self._request(
            "POST", f"/plant/allocations/{allocation_id}/consume", {}, headers
        )

    # --- Changeovers ---
    def create_changeover(self, payload, headers):
        return self._request("POST", "/plant/changeovers", payload, headers)

    def list_changeovers(self, headers, params=None):
        return self._request("GET", "/plant/changeovers", headers=headers, params=params)

    def get_changeover(self, changeover_id, headers):
        return self._request("GET", f"/plant/changeovers/{changeover_id}", headers=headers)

    def begin_changeover(self, changeover_id, headers):
        return self._request(
            "POST", f"/plant/changeovers/{changeover_id}/begin", {}, headers
        )

    def verify_changeover(self, changeover_id, headers):
        return self._request(
            "POST", f"/plant/changeovers/{changeover_id}/verify", {}, headers
        )

    def fail_changeover(self, changeover_id, headers):
        return self._request("POST", f"/plant/changeovers/{changeover_id}/fail", {}, headers)

    # --- Pack orders ---
    def create_pack_order(self, payload, headers):
        return self._request("POST", "/plant/pack-orders", payload, headers)

    def get_pack_order(self, pack_order_id, headers):
        return self._request("GET", f"/plant/pack-orders/{pack_order_id}", headers=headers)

    def start_packing(self, pack_order_id, headers):
        return self._request(
            "POST", f"/plant/pack-orders/{pack_order_id}/start-packing", {}, headers
        )

    def weight_check(self, pack_order_id, payload, headers):
        return self._request(
            "POST", f"/plant/pack-orders/{pack_order_id}/weight-check", payload, headers
        )

    def seal_pack_order(self, pack_order_id, headers):
        return self._request("POST", f"/plant/pack-orders/{pack_order_id}/seal", {}, headers)

    def reject_pack_order(self, pack_order_id, headers):
        return self._request(
            "POST", f"/plant/pack-orders/{pack_order_id}/reject", {}, headers
        )

    def list_pack_order_stops(self, pack_order_id, headers, params=None):
        return self._request(
            "GET", f"/plant/pack-orders/{pack_order_id}/stops", headers=headers, params=params
        )

    # --- Seasonal windows / allotments ---
    def create_seasonal_window(self, payload, headers):
        return self._request("POST", "/plant/seasonal-windows", payload, headers)

    def list_seasonal_windows(self, headers, params=None):
        return self._request("GET", "/plant/seasonal-windows", headers=headers, params=params)

    def get_seasonal_window(self, window_id, headers):
        return self._request("GET", f"/plant/seasonal-windows/{window_id}", headers=headers)

    def activate_seasonal_window(self, window_id, headers):
        return self._request(
            "POST", f"/plant/seasonal-windows/{window_id}/activate", {}, headers
        )

    def close_seasonal_window(self, window_id, headers):
        return self._request(
            "POST", f"/plant/seasonal-windows/{window_id}/close", {}, headers
        )

    def list_window_allotments(self, window_id, headers, params=None):
        return self._request(
            "GET",
            f"/plant/seasonal-windows/{window_id}/allotments",
            headers=headers,
            params=params,
        )

    def get_allotment(self, allotment_id, headers):
        return self._request("GET", f"/plant/allotments/{allotment_id}", headers=headers)

    # --- Customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/plant/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/plant/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/plant/customers/{customer_id}", headers=headers)

    def set_credit_standing(self, customer_id, credit_standing, headers):
        return self._request(
            "POST",
            f"/plant/customers/{customer_id}/set-credit-standing",
            {"credit_standing": credit_standing},
            headers,
        )

    def list_customer_stops(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/plant/customers/{customer_id}/stops", headers=headers, params=params
        )

    def list_customer_allotments(self, customer_id, headers, params=None):
        return self._request(
            "GET",
            f"/plant/customers/{customer_id}/allotments",
            headers=headers,
            params=params,
        )

    # --- Routes / stops ---
    def create_route(self, payload, headers):
        return self._request("POST", "/plant/routes", payload, headers)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/plant/routes/{route_id}", headers=headers)

    def dispatch_route(self, route_id, headers):
        return self._request("POST", f"/plant/routes/{route_id}/dispatch", {}, headers)

    def complete_route(self, route_id, headers):
        return self._request("POST", f"/plant/routes/{route_id}/complete", {}, headers)

    def cancel_route(self, route_id, headers):
        return self._request("POST", f"/plant/routes/{route_id}/cancel", {}, headers)

    def list_route_stops(self, route_id, headers, params=None):
        return self._request(
            "GET", f"/plant/routes/{route_id}/stops", headers=headers, params=params
        )

    def create_route_stop(self, route_id, payload, headers):
        return self._request("POST", f"/plant/routes/{route_id}/stops", payload, headers)

    def get_stop(self, stop_id, headers):
        return self._request("GET", f"/plant/stops/{stop_id}", headers=headers)

    def deliver_stop(self, stop_id, delivered_cases, headers):
        return self._request(
            "POST",
            f"/plant/stops/{stop_id}/deliver",
            {"delivered_cases": delivered_cases},
            headers,
        )

    def short_stop(self, stop_id, headers):
        return self._request("POST", f"/plant/stops/{stop_id}/short", {}, headers)


api_client = ApiClient()
