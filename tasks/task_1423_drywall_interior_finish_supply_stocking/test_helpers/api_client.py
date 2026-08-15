"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- ContractorAccount ---
    def create_contractor_account(self, payload, headers):
        return self._request("POST", "/supply/contractor-accounts", payload, headers)

    def get_contractor_account(self, account_id, headers):
        return self._request("GET", f"/supply/contractor-accounts/{account_id}", headers=headers)

    def list_contractor_accounts(self, headers, params=None):
        return self._request("GET", "/supply/contractor-accounts", headers=headers, params=params)

    def suspend_contractor_account(self, account_id, headers):
        return self._request("POST", f"/supply/contractor-accounts/{account_id}/suspend", headers=headers)

    def reinstate_contractor_account(self, account_id, headers):
        return self._request("POST", f"/supply/contractor-accounts/{account_id}/reinstate", headers=headers)

    def close_contractor_account(self, account_id, headers):
        return self._request("POST", f"/supply/contractor-accounts/{account_id}/close", headers=headers)

    # --- Product ---
    def create_product(self, payload, headers):
        return self._request("POST", "/supply/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/supply/products/{product_id}", headers=headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/supply/products", headers=headers, params=params)

    def update_product(self, product_id, payload, headers):
        return self._request("PATCH", f"/supply/products/{product_id}", payload, headers)

    # --- BoomTruck ---
    def create_boom_truck(self, payload, headers):
        return self._request("POST", "/supply/boom-trucks", payload, headers)

    def get_boom_truck(self, truck_id, headers):
        return self._request("GET", f"/supply/boom-trucks/{truck_id}", headers=headers)

    def list_boom_trucks(self, headers, params=None):
        return self._request("GET", "/supply/boom-trucks", headers=headers, params=params)

    def update_boom_truck(self, truck_id, payload, headers):
        return self._request("PATCH", f"/supply/boom-trucks/{truck_id}", payload, headers)

    # --- Project ---
    def create_project(self, payload, headers):
        return self._request("POST", "/supply/projects", payload, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/supply/projects/{project_id}", headers=headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/supply/projects", headers=headers, params=params)

    def update_project(self, project_id, payload, headers):
        return self._request("PATCH", f"/supply/projects/{project_id}", payload, headers)

    def open_stocking(self, project_id, headers):
        return self._request("POST", f"/supply/projects/{project_id}/open-stocking", headers=headers)

    def close_stocking(self, project_id, headers):
        return self._request("POST", f"/supply/projects/{project_id}/close-stocking", headers=headers)

    def cancel_project(self, project_id, headers):
        return self._request("POST", f"/supply/projects/{project_id}/cancel", headers=headers)

    # --- Takeoff / TakeoffLine ---
    def create_takeoff(self, payload, headers):
        return self._request("POST", "/supply/takeoffs", payload, headers)

    def get_takeoff(self, takeoff_id, headers):
        return self._request("GET", f"/supply/takeoffs/{takeoff_id}", headers=headers)

    def list_takeoffs(self, headers, params=None):
        return self._request("GET", "/supply/takeoffs", headers=headers, params=params)

    def add_takeoff_line(self, takeoff_id, payload, headers):
        return self._request("POST", f"/supply/takeoffs/{takeoff_id}/lines", payload, headers)

    def list_takeoff_lines(self, headers, params=None):
        return self._request("GET", "/supply/takeoff-lines", headers=headers, params=params)

    def get_takeoff_line(self, line_id, headers):
        return self._request("GET", f"/supply/takeoff-lines/{line_id}", headers=headers)

    def delete_takeoff_line(self, takeoff_id, line_id, headers):
        return self._request("DELETE", f"/supply/takeoffs/{takeoff_id}/lines/{line_id}", headers=headers)

    def submit_takeoff(self, takeoff_id, headers):
        return self._request("POST", f"/supply/takeoffs/{takeoff_id}/submit", headers=headers)

    def lock_takeoff(self, takeoff_id, payload, headers):
        return self._request("POST", f"/supply/takeoffs/{takeoff_id}/lock", payload, headers)

    def cancel_takeoff(self, takeoff_id, headers):
        return self._request("POST", f"/supply/takeoffs/{takeoff_id}/cancel", headers=headers)

    # --- StockingOrder / StockingDrop ---
    def create_stocking_order(self, payload, headers):
        return self._request("POST", "/supply/stocking-orders", payload, headers)

    def get_stocking_order(self, order_id, headers):
        return self._request("GET", f"/supply/stocking-orders/{order_id}", headers=headers)

    def list_stocking_orders(self, headers, params=None):
        return self._request("GET", "/supply/stocking-orders", headers=headers, params=params)

    def list_stocking_drops(self, headers, params=None):
        return self._request("GET", "/supply/stocking-drops", headers=headers, params=params)

    def get_stocking_drop(self, drop_id, headers):
        return self._request("GET", f"/supply/stocking-drops/{drop_id}", headers=headers)

    def add_stocking_drop(self, order_id, payload, headers):
        return self._request("POST", f"/supply/stocking-orders/{order_id}/drops", payload, headers)

    def list_order_drops(self, order_id, headers):
        return self._request("GET", f"/supply/stocking-orders/{order_id}/drops", headers=headers)

    def schedule_stocking_order(self, order_id, headers):
        return self._request("POST", f"/supply/stocking-orders/{order_id}/schedule", headers=headers)

    def dispatch_stocking_order(self, order_id, headers):
        return self._request("POST", f"/supply/stocking-orders/{order_id}/dispatch", headers=headers)

    def mark_stocked(self, order_id, headers):
        return self._request("POST", f"/supply/stocking-orders/{order_id}/mark-stocked", headers=headers)

    def cancel_stocking_order(self, order_id, headers):
        return self._request("POST", f"/supply/stocking-orders/{order_id}/cancel", headers=headers)

    # --- DrawRequest / Payment ---
    def get_draw_request(self, draw_id, headers):
        return self._request("GET", f"/supply/draw-requests/{draw_id}", headers=headers)

    def list_draw_requests(self, headers, params=None):
        return self._request("GET", "/supply/draw-requests", headers=headers, params=params)

    def apply_payment(self, draw_id, payload, headers):
        return self._request("POST", f"/supply/draw-requests/{draw_id}/payments", payload, headers)

    def list_payments(self, draw_id, headers):
        return self._request("GET", f"/supply/draw-requests/{draw_id}/payments", headers=headers)

    def void_draw_request(self, draw_id, headers):
        return self._request("POST", f"/supply/draw-requests/{draw_id}/void", headers=headers)

    # --- BundleReturn ---
    def create_bundle_return(self, payload, headers):
        return self._request("POST", "/supply/bundle-returns", payload, headers)

    def get_bundle_return(self, return_id, headers):
        return self._request("GET", f"/supply/bundle-returns/{return_id}", headers=headers)

    def list_bundle_returns(self, headers, params=None):
        return self._request("GET", "/supply/bundle-returns", headers=headers, params=params)

    def accept_bundle_return(self, return_id, headers):
        return self._request("POST", f"/supply/bundle-returns/{return_id}/accept", headers=headers)

    def reject_bundle_return(self, return_id, headers):
        return self._request("POST", f"/supply/bundle-returns/{return_id}/reject", headers=headers)

    # --- Logical clock (test-driving) ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/supply/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
