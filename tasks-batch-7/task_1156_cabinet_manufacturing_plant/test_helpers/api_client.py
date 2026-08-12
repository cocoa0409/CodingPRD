"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Dealers ---
    def create_dealer(self, payload, headers):
        return self._request("POST", "/kcma/dealers", payload, headers)

    def update_dealer(self, dealer_id, payload, headers):
        return self._request("PUT", f"/kcma/dealers/{dealer_id}", payload, headers)

    def list_dealers(self, headers, params=None):
        return self._request("GET", "/kcma/dealers", headers=headers, params=params)

    # --- Catalog: door styles & finish specs ---
    def create_door_style(self, payload, headers):
        return self._request("POST", "/kcma/door-styles", payload, headers)

    def list_door_styles(self, headers, params=None):
        return self._request("GET", "/kcma/door-styles", headers=headers, params=params)

    def create_finish_spec(self, payload, headers):
        return self._request("POST", "/kcma/finish-specs", payload, headers)

    def list_finish_specs(self, headers, params=None):
        return self._request("GET", "/kcma/finish-specs", headers=headers, params=params)

    # --- Components / inventory ---
    def create_component(self, payload, headers):
        return self._request("POST", "/kcma/components", payload, headers)

    def list_components(self, headers, params=None):
        return self._request("GET", "/kcma/components", headers=headers, params=params)

    def get_component(self, component_id, headers):
        return self._request("GET", f"/kcma/components/{component_id}", headers=headers)

    def receive_component(self, component_id, payload, headers):
        return self._request("POST", f"/kcma/components/{component_id}/receipts", payload, headers)

    def list_component_holds(self, component_id, headers, params=None):
        return self._request("GET", f"/kcma/components/{component_id}/holds", headers=headers, params=params)

    # --- Orders ---
    def create_order(self, headers, payload=None):
        return self._request("POST", "/kcma/orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/kcma/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/kcma/orders/{order_id}", headers=headers)

    def create_order_line(self, order_id, payload, headers):
        return self._request("POST", f"/kcma/orders/{order_id}/lines", payload, headers)

    def list_order_holds(self, order_id, headers, params=None):
        return self._request("GET", f"/kcma/orders/{order_id}/holds", headers=headers, params=params)

    def submit_order(self, order_id, headers):
        return self._request("POST", f"/kcma/orders/{order_id}/submit", headers=headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/kcma/orders/{order_id}/cancel", headers=headers)

    # --- Order lines ---
    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/kcma/order-lines", headers=headers, params=params)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/kcma/order-lines/{line_id}", headers=headers)

    # --- Modifications ---
    def create_modification(self, line_id, payload, headers):
        return self._request("POST", f"/kcma/order-lines/{line_id}/modifications", payload, headers)

    def list_modifications(self, line_id, headers, params=None):
        return self._request("GET", f"/kcma/order-lines/{line_id}/modifications", headers=headers, params=params)

    def review_modification(self, mod_id, payload, headers):
        return self._request("POST", f"/kcma/modifications/{mod_id}/review", payload, headers)

    def resubmit_modification(self, mod_id, payload, headers):
        return self._request("POST", f"/kcma/modifications/{mod_id}/resubmit", payload, headers)

    # --- Finish batches ---
    def create_finish_batch(self, payload, headers):
        return self._request("POST", "/kcma/finish-batches", payload, headers)

    def list_finish_batches(self, headers, params=None):
        return self._request("GET", "/kcma/finish-batches", headers=headers, params=params)

    def get_finish_batch(self, batch_id, headers):
        return self._request("GET", f"/kcma/finish-batches/{batch_id}", headers=headers)

    def record_batch_qc(self, batch_id, payload, headers):
        return self._request("POST", f"/kcma/finish-batches/{batch_id}/qc-record", payload, headers)

    def assign_batch_line(self, batch_id, payload, headers):
        return self._request("POST", f"/kcma/finish-batches/{batch_id}/assign", payload, headers)

    def remix_batch(self, batch_id, headers):
        return self._request("POST", f"/kcma/finish-batches/{batch_id}/remix", headers=headers)

    # --- Nesting stations & runs ---
    def create_nesting_station(self, payload, headers):
        return self._request("POST", "/kcma/nesting-stations", payload, headers)

    def list_nesting_stations(self, headers, params=None):
        return self._request("GET", "/kcma/nesting-stations", headers=headers, params=params)

    def create_nesting_run(self, payload, headers):
        return self._request("POST", "/kcma/nesting-runs", payload, headers)

    def list_nesting_runs(self, headers, params=None):
        return self._request("GET", "/kcma/nesting-runs", headers=headers, params=params)

    def get_nesting_run(self, run_id, headers):
        return self._request("GET", f"/kcma/nesting-runs/{run_id}", headers=headers)

    def release_nesting_run(self, run_id, headers):
        return self._request("POST", f"/kcma/nesting-runs/{run_id}/release", headers=headers)

    def cancel_nesting_run(self, run_id, headers):
        return self._request("POST", f"/kcma/nesting-runs/{run_id}/cancel", headers=headers)

    # --- Parts ---
    def list_parts(self, headers, params=None):
        return self._request("GET", "/kcma/parts", headers=headers, params=params)

    def get_part(self, part_id, headers):
        return self._request("GET", f"/kcma/parts/{part_id}", headers=headers)

    # --- Assembly lines & sub-lots ---
    def create_assembly_line(self, payload, headers):
        return self._request("POST", "/kcma/assembly-lines", payload, headers)

    def list_assembly_lines(self, headers, params=None):
        return self._request("GET", "/kcma/assembly-lines", headers=headers, params=params)

    def create_sub_lot(self, payload, headers):
        return self._request("POST", "/kcma/sub-lots", payload, headers)

    def list_sub_lots(self, headers, params=None):
        return self._request("GET", "/kcma/sub-lots", headers=headers, params=params)

    def get_sub_lot(self, sub_lot_id, headers):
        return self._request("GET", f"/kcma/sub-lots/{sub_lot_id}", headers=headers)

    def complete_sub_lot(self, sub_lot_id, headers):
        return self._request("POST", f"/kcma/sub-lots/{sub_lot_id}/complete", headers=headers)

    # --- Replacement claims ---
    def create_replacement_claim(self, payload, headers):
        return self._request("POST", "/kcma/replacement-claims", payload, headers)

    def list_replacement_claims(self, headers, params=None):
        return self._request("GET", "/kcma/replacement-claims", headers=headers, params=params)

    def get_replacement_claim(self, claim_id, headers):
        return self._request("GET", f"/kcma/replacement-claims/{claim_id}", headers=headers)

    def adjudicate_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/kcma/replacement-claims/{claim_id}/adjudicate", payload, headers)

    # --- Delivery routes ---
    def create_delivery_route(self, payload, headers):
        return self._request("POST", "/kcma/delivery-routes", payload, headers)

    def list_delivery_routes(self, headers, params=None):
        return self._request("GET", "/kcma/delivery-routes", headers=headers, params=params)

    def assign_order_to_route(self, route_id, payload, headers):
        return self._request("POST", f"/kcma/delivery-routes/{route_id}/assign-order", payload, headers)

    def lock_route(self, route_id, headers):
        return self._request("POST", f"/kcma/delivery-routes/{route_id}/lock", headers=headers)

    def dispatch_route(self, route_id, headers):
        return self._request("POST", f"/kcma/delivery-routes/{route_id}/dispatch", headers=headers)

    # --- Holds ---
    def release_order_hold(self, hold_id, headers):
        return self._request("POST", f"/kcma/order-holds/{hold_id}/release", headers=headers)

    # --- Logical clock ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/kcma/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
