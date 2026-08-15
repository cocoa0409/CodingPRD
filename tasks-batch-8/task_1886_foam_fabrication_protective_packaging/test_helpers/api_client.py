"""API client: one method per endpoint defined in PRD §4."""
from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601: str, headers: Dict):
        return self._request(
            "POST", "/api/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- customers ---
    def create_customer(self, payload: Dict, headers: Dict):
        return self._request("POST", "/api/customers", payload, headers)

    def get_customer(self, customer_id: str, headers: Dict):
        return self._request("GET", f"/api/customers/{customer_id}", headers=headers)

    # --- materials ---
    def create_material(self, payload: Dict, headers: Dict):
        return self._request("POST", "/api/materials", payload, headers)

    def get_material(self, material_id: str, headers: Dict):
        return self._request("GET", f"/api/materials/{material_id}", headers=headers)

    def patch_material(self, material_id: str, payload: Dict, headers: Dict):
        return self._request("PATCH", f"/api/materials/{material_id}", payload, headers)

    # --- package specs ---
    def create_package_spec(self, payload: Dict, headers: Dict):
        return self._request("POST", "/api/package-specs", payload, headers)

    def get_package_spec(self, spec_id: str, headers: Dict):
        return self._request("GET", f"/api/package-specs/{spec_id}", headers=headers)

    def list_package_specs(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/api/package-specs", headers=headers, params=params)

    def patch_package_spec(self, spec_id: str, payload: Dict, headers: Dict):
        return self._request("PATCH", f"/api/package-specs/{spec_id}", payload, headers)

    def submit_spec(self, spec_id: str, headers: Dict):
        return self._request("POST", f"/api/package-specs/{spec_id}/submit", {}, headers)

    def begin_validation(self, spec_id: str, headers: Dict):
        return self._request(
            "POST", f"/api/package-specs/{spec_id}/begin-validation", {}, headers,
        )

    def return_for_revision(self, spec_id: str, headers: Dict):
        return self._request(
            "POST", f"/api/package-specs/{spec_id}/return-for-revision", {}, headers,
        )

    def approve_spec(self, spec_id: str, headers: Dict):
        return self._request(
            "POST", f"/api/package-specs/{spec_id}/approve", {}, headers,
        )

    # --- cut programs ---
    def create_cut_program(self, payload: Dict, headers: Dict):
        return self._request("POST", "/api/cut-programs", payload, headers)

    def get_cut_program(self, program_id: str, headers: Dict):
        return self._request("GET", f"/api/cut-programs/{program_id}", headers=headers)

    def list_cut_programs(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/api/cut-programs", headers=headers, params=params)

    def nest_cut_program(self, program_id: str, headers: Dict):
        return self._request(
            "POST", f"/api/cut-programs/{program_id}/nest", {}, headers,
        )

    def lock_cut_program(self, program_id: str, headers: Dict):
        return self._request(
            "POST", f"/api/cut-programs/{program_id}/lock", {}, headers,
        )

    # --- tooling ---
    def create_tooling(self, payload: Dict, headers: Dict):
        return self._request("POST", "/api/toolings", payload, headers)

    def get_tooling(self, tooling_id: str, headers: Dict):
        return self._request("GET", f"/api/toolings/{tooling_id}", headers=headers)

    def list_toolings(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/api/toolings", headers=headers, params=params)

    def commission_tooling(self, tooling_id: str, headers: Dict):
        return self._request(
            "POST", f"/api/toolings/{tooling_id}/commission", {}, headers,
        )

    def retire_tooling(self, tooling_id: str, headers: Dict):
        return self._request("POST", f"/api/toolings/{tooling_id}/retire", {}, headers)

    # --- drop tests ---
    def create_drop_test(self, payload: Dict, headers: Dict):
        return self._request("POST", "/api/drop-tests", payload, headers)

    def get_drop_test(self, drop_test_id: str, headers: Dict):
        return self._request("GET", f"/api/drop-tests/{drop_test_id}", headers=headers)

    def list_drop_tests(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/api/drop-tests", headers=headers, params=params)

    def record_drop_test(self, drop_test_id: str, measured_peak_g: int, headers: Dict):
        return self._request(
            "POST", f"/api/drop-tests/{drop_test_id}/record",
            {"measured_peak_g": measured_peak_g}, headers,
        )

    # --- production orders ---
    def create_production_order(self, payload: Dict, headers: Dict):
        return self._request("POST", "/api/production-orders", payload, headers)

    def get_production_order(self, order_id: str, headers: Dict):
        return self._request(
            "GET", f"/api/production-orders/{order_id}", headers=headers,
        )

    def list_production_orders(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", "/api/production-orders", headers=headers, params=params,
        )

    def confirm_production_order(self, order_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/api/production-orders/{order_id}/confirm", payload, headers,
        )

    def start_production_order(self, order_id: str, headers: Dict):
        return self._request(
            "POST", f"/api/production-orders/{order_id}/start", {}, headers,
        )

    def complete_production_order(self, order_id: str, headers: Dict):
        return self._request(
            "POST", f"/api/production-orders/{order_id}/complete", {}, headers,
        )

    def cancel_production_order(self, order_id: str, headers: Dict):
        return self._request(
            "POST", f"/api/production-orders/{order_id}/cancel", {}, headers,
        )

    def hold_production_order(self, order_id: str, headers: Dict):
        return self._request(
            "POST", f"/api/production-orders/{order_id}/hold", {}, headers,
        )

    def release_hold_production_order(self, order_id: str, headers: Dict):
        return self._request(
            "POST", f"/api/production-orders/{order_id}/release-hold", {}, headers,
        )

    # --- inventory programs ---
    def create_inventory_program(self, payload: Dict, headers: Dict):
        return self._request("POST", "/api/inventory-programs", payload, headers)

    def get_inventory_program(self, program_id: str, headers: Dict):
        return self._request(
            "GET", f"/api/inventory-programs/{program_id}", headers=headers,
        )

    def list_inventory_programs(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", "/api/inventory-programs", headers=headers, params=params,
        )

    def activate_program(self, program_id: str, headers: Dict):
        return self._request(
            "POST", f"/api/inventory-programs/{program_id}/activate", {}, headers,
        )

    def suspend_program(self, program_id: str, headers: Dict):
        return self._request(
            "POST", f"/api/inventory-programs/{program_id}/suspend", {}, headers,
        )

    def resume_program(self, program_id: str, headers: Dict):
        return self._request(
            "POST", f"/api/inventory-programs/{program_id}/resume", {}, headers,
        )

    def close_program(self, program_id: str, headers: Dict):
        return self._request(
            "POST", f"/api/inventory-programs/{program_id}/close", {}, headers,
        )

    def replenish_program(self, program_id: str, qty: int, headers: Dict):
        return self._request(
            "POST", f"/api/inventory-programs/{program_id}/replenish",
            {"qty": qty}, headers,
        )

    # --- release orders ---
    def create_release_order(self, payload: Dict, headers: Dict):
        return self._request("POST", "/api/release-orders", payload, headers)

    def get_release_order(self, release_id: str, headers: Dict):
        return self._request("GET", f"/api/release-orders/{release_id}", headers=headers)

    def list_release_orders(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/api/release-orders", headers=headers, params=params)

    def allocate_release(self, release_id: str, headers: Dict):
        return self._request(
            "POST", f"/api/release-orders/{release_id}/allocate", {}, headers,
        )

    def deallocate_release(self, release_id: str, headers: Dict):
        return self._request(
            "POST", f"/api/release-orders/{release_id}/deallocate", {}, headers,
        )

    def ship_release(self, release_id: str, headers: Dict):
        return self._request(
            "POST", f"/api/release-orders/{release_id}/ship", {}, headers,
        )

    def cancel_release(self, release_id: str, headers: Dict):
        return self._request(
            "POST", f"/api/release-orders/{release_id}/cancel", {}, headers,
        )

    # --- scrap batches ---
    def create_scrap_batch(self, payload: Dict, headers: Dict):
        return self._request("POST", "/api/scrap-batches", payload, headers)

    def get_scrap_batch(self, batch_id: str, headers: Dict):
        return self._request("GET", f"/api/scrap-batches/{batch_id}", headers=headers)

    def list_scrap_batches(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/api/scrap-batches", headers=headers, params=params)

    def process_scrap_batch(self, batch_id: str, headers: Dict):
        return self._request(
            "POST", f"/api/scrap-batches/{batch_id}/process", {}, headers,
        )

    def credit_scrap_batch(self, batch_id: str, headers: Dict):
        return self._request(
            "POST", f"/api/scrap-batches/{batch_id}/credit", {}, headers,
        )


api_client = ApiClient()
