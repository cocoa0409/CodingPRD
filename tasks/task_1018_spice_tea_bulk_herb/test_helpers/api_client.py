"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Product ---
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers=headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    def discontinue_product(self, product_id, headers):
        return self._request("POST", f"/products/{product_id}/discontinue", headers=headers)

    # --- BlendComponent ---
    def create_blend_component(self, payload, headers):
        return self._request("POST", "/blend-components", payload, headers=headers)

    def get_blend_component(self, component_id, headers):
        return self._request("GET", f"/blend-components/{component_id}", headers=headers)

    def list_blend_components(self, headers, params=None):
        return self._request("GET", "/blend-components", headers=headers, params=params)

    # --- InventoryLot ---
    def create_inventory_lot(self, payload, headers):
        return self._request("POST", "/inventory-lots", payload, headers=headers)

    def get_inventory_lot(self, lot_id, headers):
        return self._request("GET", f"/inventory-lots/{lot_id}", headers=headers)

    def list_inventory_lots(self, headers, params=None):
        return self._request("GET", "/inventory-lots", headers=headers, params=params)

    # --- ProductionLine ---
    def create_production_line(self, payload, headers):
        return self._request("POST", "/production-lines", payload, headers=headers)

    def get_production_line(self, line_id, headers):
        return self._request("GET", f"/production-lines/{line_id}", headers=headers)

    # --- Batch ---
    def create_batch(self, payload, headers):
        return self._request("POST", "/batches", payload, headers=headers)

    def get_batch(self, batch_id, headers):
        return self._request("GET", f"/batches/{batch_id}", headers=headers)

    def list_batches(self, headers, params=None):
        return self._request("GET", "/batches", headers=headers, params=params)

    def produce_batch(self, batch_id, headers):
        return self._request("POST", f"/batches/{batch_id}/produce", headers=headers)

    # --- LabelingStation ---
    def create_labeling_station(self, payload, headers):
        return self._request("POST", "/labeling-stations", payload, headers=headers)

    def get_labeling_station(self, station_id, headers):
        return self._request("GET", f"/labeling-stations/{station_id}", headers=headers)

    # --- TinRun ---
    def create_tin_run(self, payload, headers):
        return self._request("POST", "/tin-runs", payload, headers=headers)

    def get_tin_run(self, tin_run_id, headers):
        return self._request("GET", f"/tin-runs/{tin_run_id}", headers=headers)

    def list_tin_runs(self, headers, params=None):
        return self._request("GET", "/tin-runs", headers=headers, params=params)

    # --- WholesaleAccount ---
    def create_wholesale_account(self, payload, headers):
        return self._request("POST", "/wholesale-accounts", payload, headers=headers)

    def get_wholesale_account(self, account_id, headers):
        return self._request("GET", f"/wholesale-accounts/{account_id}", headers=headers)

    def list_wholesale_accounts(self, headers, params=None):
        return self._request("GET", "/wholesale-accounts", headers=headers, params=params)

    def suspend_account(self, account_id, headers):
        return self._request("POST", f"/wholesale-accounts/{account_id}/suspend", headers=headers)

    def reinstate_account(self, account_id, headers):
        return self._request("POST", f"/wholesale-accounts/{account_id}/reinstate", headers=headers)

    # --- CustomerOrder ---
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers=headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def add_order_line(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/lines", payload, headers=headers)

    def price_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/price", headers=headers)

    def confirm_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/confirm", payload, headers=headers)

    def pack_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/pack", payload, headers=headers)

    def ship_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/ship", headers=headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", headers=headers)

    # --- OrderLine reads ---
    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/order-lines/{line_id}", headers=headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/order-lines", headers=headers, params=params)

    # --- Test-driving clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers=headers)


api_client = ApiClient()
