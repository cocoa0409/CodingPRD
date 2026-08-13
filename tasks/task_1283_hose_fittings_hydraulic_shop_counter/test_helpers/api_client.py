"""API client: one method per endpoint defined in the PRD (all under /api)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD §2.5) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # --- Customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/api/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/api/customers/{customer_id}", headers=headers)

    def update_customer(self, customer_id, payload, headers):
        return self._request("PATCH", f"/api/customers/{customer_id}", payload, headers)

    # --- Equipment assets ---
    def create_equipment_asset(self, payload, headers):
        return self._request("POST", "/api/equipment-assets", payload, headers)

    def list_equipment_assets(self, headers, params=None):
        return self._request("GET", "/api/equipment-assets", headers=headers, params=params)

    def get_equipment_asset(self, asset_id, headers):
        return self._request("GET", f"/api/equipment-assets/{asset_id}", headers=headers)

    def decommission_equipment_asset(self, asset_id, headers):
        return self._request("POST", f"/api/equipment-assets/{asset_id}/decommission", {}, headers)

    def create_inspection(self, asset_id, payload, headers):
        return self._request("POST", f"/api/equipment-assets/{asset_id}/inspections", payload, headers)

    def list_inspections(self, asset_id, headers, params=None):
        return self._request("GET", f"/api/equipment-assets/{asset_id}/inspections", headers=headers, params=params)

    # --- Inspections ---
    def start_inspection(self, inspection_id, headers):
        return self._request("POST", f"/api/inspections/{inspection_id}/start", {}, headers)

    def complete_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/api/inspections/{inspection_id}/complete", payload, headers)

    # --- Reels ---
    def create_reel(self, payload, headers):
        return self._request("POST", "/api/reels", payload, headers)

    def get_reel(self, reel_id, headers):
        return self._request("GET", f"/api/reels/{reel_id}", headers=headers)

    def retire_reel(self, reel_id, headers):
        return self._request("POST", f"/api/reels/{reel_id}/retire", {}, headers)

    # --- Couplings ---
    def create_coupling(self, payload, headers):
        return self._request("POST", "/api/couplings", payload, headers)

    def get_coupling(self, coupling_id, headers):
        return self._request("GET", f"/api/couplings/{coupling_id}", headers=headers)

    def create_coupling_receipt(self, coupling_id, payload, headers):
        return self._request("POST", f"/api/couplings/{coupling_id}/receipts", payload, headers)

    def list_coupling_assembly_lines(self, coupling_id, headers, params=None):
        return self._request("GET", f"/api/couplings/{coupling_id}/assembly-lines", headers=headers, params=params)

    # --- Assembly orders ---
    def create_assembly_order(self, payload, headers):
        return self._request("POST", "/api/assembly-orders", payload, headers)

    def list_assembly_orders(self, headers, params=None):
        return self._request("GET", "/api/assembly-orders", headers=headers, params=params)

    def get_assembly_order(self, order_id, headers):
        return self._request("GET", f"/api/assembly-orders/{order_id}", headers=headers)

    def list_assembly_order_lines(self, order_id, headers, params=None):
        return self._request("GET", f"/api/assembly-orders/{order_id}/lines", headers=headers, params=params)

    def confirm_assembly_order(self, order_id, payload, headers):
        return self._request("POST", f"/api/assembly-orders/{order_id}/confirm", payload, headers)

    def complete_build(self, order_id, payload, headers):
        return self._request("POST", f"/api/assembly-orders/{order_id}/complete-build", payload, headers)

    def record_pressure_test(self, order_id, payload, headers):
        return self._request("POST", f"/api/assembly-orders/{order_id}/record-pressure-test", payload, headers)

    def rework_assembly_order(self, order_id, headers):
        return self._request("POST", f"/api/assembly-orders/{order_id}/rework", {}, headers)

    def tag_assembly_order(self, order_id, payload, headers):
        return self._request("POST", f"/api/assembly-orders/{order_id}/tag", payload, headers)

    def complete_assembly_order(self, order_id, headers):
        return self._request("POST", f"/api/assembly-orders/{order_id}/complete", {}, headers)

    def cancel_assembly_order(self, order_id, headers):
        return self._request("POST", f"/api/assembly-orders/{order_id}/cancel", {}, headers)

    # --- Service dispatches ---
    def create_service_dispatch(self, payload, headers):
        return self._request("POST", "/api/service-dispatches", payload, headers)

    def list_service_dispatches(self, headers, params=None):
        return self._request("GET", "/api/service-dispatches", headers=headers, params=params)

    def get_service_dispatch(self, dispatch_id, headers):
        return self._request("GET", f"/api/service-dispatches/{dispatch_id}", headers=headers)

    def advance_service_dispatch(self, dispatch_id, headers):
        return self._request("POST", f"/api/service-dispatches/{dispatch_id}/advance", {}, headers)

    def complete_service_dispatch(self, dispatch_id, payload, headers):
        return self._request("POST", f"/api/service-dispatches/{dispatch_id}/complete", payload, headers)

    def abort_service_dispatch(self, dispatch_id, headers):
        return self._request("POST", f"/api/service-dispatches/{dispatch_id}/abort", {}, headers)


api_client = ApiClient()
