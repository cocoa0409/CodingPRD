"""API client: one method per endpoint defined in the PRD.

Every plant endpoint is mounted under `/plant`; the logical-clock control is
the sole exception and lives at `/_clock/set_current_utc`.
"""

from prd_bench_local_runner.testing import GenericApiClient

BASE = "/plant"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical plant clock
    # ------------------------------------------------------------------

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Refrigerant programs
    # ------------------------------------------------------------------

    def create_refrigerant_program(self, payload, headers):
        return self._request("POST", f"{BASE}/refrigerant-programs", payload, headers)

    def list_refrigerant_programs(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/refrigerant-programs", headers=headers, params=params
        )

    def get_refrigerant_program(self, program_id, headers):
        return self._request(
            "GET", f"{BASE}/refrigerant-programs/{program_id}", headers=headers
        )

    def enter_sell_through(self, program_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/refrigerant-programs/{program_id}/enter-sell-through",
            payload or {},
            headers,
        )

    def expire_refrigerant_program(self, program_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/refrigerant-programs/{program_id}/expire",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # Regional standards
    # ------------------------------------------------------------------

    def create_regional_standard(self, payload, headers):
        return self._request("POST", f"{BASE}/regional-standards", payload, headers)

    def list_regional_standards(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/regional-standards", headers=headers, params=params
        )

    def get_regional_standard(self, standard_id, headers):
        return self._request(
            "GET", f"{BASE}/regional-standards/{standard_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Product platforms
    # ------------------------------------------------------------------

    def create_product_platform(self, payload, headers):
        return self._request("POST", f"{BASE}/product-platforms", payload, headers)

    def list_product_platforms(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/product-platforms", headers=headers, params=params
        )

    def get_product_platform(self, platform_id, headers):
        return self._request(
            "GET", f"{BASE}/product-platforms/{platform_id}", headers=headers
        )

    def update_product_platform(self, platform_id, payload, headers):
        return self._request(
            "PATCH", f"{BASE}/product-platforms/{platform_id}", payload, headers
        )

    def submit_engineering_review(self, platform_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/product-platforms/{platform_id}/submit-engineering-review",
            payload or {},
            headers,
        )

    def return_platform_to_draft(self, platform_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/product-platforms/{platform_id}/return-to-draft",
            payload,
            headers,
        )

    def release_platform(self, platform_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/product-platforms/{platform_id}/release",
            payload or {},
            headers,
        )

    def retire_platform(self, platform_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/product-platforms/{platform_id}/retire", payload, headers
        )

    def list_platform_certification_records(self, platform_id, headers, params=None):
        return self._request(
            "GET",
            f"{BASE}/product-platforms/{platform_id}/certification-records",
            headers=headers,
            params=params,
        )

    def list_platform_warranty_claims(self, platform_id, headers, params=None):
        return self._request(
            "GET",
            f"{BASE}/product-platforms/{platform_id}/warranty-claims",
            headers=headers,
            params=params,
        )

    def get_platform_warranty_analysis(self, platform_id, headers, params=None):
        return self._request(
            "GET",
            f"{BASE}/product-platforms/{platform_id}/warranty-analysis",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Certification records
    # ------------------------------------------------------------------

    def create_certification_record(self, payload, headers):
        return self._request("POST", f"{BASE}/certification-records", payload, headers)

    def list_certification_records(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/certification-records", headers=headers, params=params
        )

    def get_certification_record(self, record_id, headers):
        return self._request(
            "GET", f"{BASE}/certification-records/{record_id}", headers=headers
        )

    def submit_certification_record(self, record_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/certification-records/{record_id}/submit",
            payload or {},
            headers,
        )

    def decide_certification_record(self, record_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/certification-records/{record_id}/decide", payload, headers
        )

    # ------------------------------------------------------------------
    # Component supplies
    # ------------------------------------------------------------------

    def create_component_supply(self, payload, headers):
        return self._request("POST", f"{BASE}/component-supplies", payload, headers)

    def list_component_supplies(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/component-supplies", headers=headers, params=params
        )

    def get_component_supply(self, supply_id, headers):
        return self._request(
            "GET", f"{BASE}/component-supplies/{supply_id}", headers=headers
        )

    def list_supply_allocation_lines(self, supply_id, headers, params=None):
        return self._request(
            "GET",
            f"{BASE}/component-supplies/{supply_id}/allocation-lines",
            headers=headers,
            params=params,
        )

    def list_supply_corrective_actions(self, supply_id, headers, params=None):
        return self._request(
            "GET",
            f"{BASE}/component-supplies/{supply_id}/corrective-actions",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Allocation lines
    # ------------------------------------------------------------------

    def list_allocation_lines(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/allocation-lines", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Distributor orders
    # ------------------------------------------------------------------

    def create_distributor_order(self, payload, headers):
        return self._request("POST", f"{BASE}/distributor-orders", payload, headers)

    def list_distributor_orders(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/distributor-orders", headers=headers, params=params
        )

    def get_distributor_order(self, order_id, headers):
        return self._request(
            "GET", f"{BASE}/distributor-orders/{order_id}", headers=headers
        )

    def allocate_distributor_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/distributor-orders/{order_id}/allocate", payload, headers
        )

    def get_allocation_preview(self, order_id, headers, params=None):
        return self._request(
            "GET",
            f"{BASE}/distributor-orders/{order_id}/allocation-preview",
            headers=headers,
            params=params,
        )

    def stage_distributor_order(self, order_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/distributor-orders/{order_id}/stage",
            payload or {},
            headers,
        )

    def ship_distributor_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/distributor-orders/{order_id}/ship", payload, headers
        )

    def cancel_distributor_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/distributor-orders/{order_id}/cancel", payload, headers
        )

    def list_order_allocation_lines(self, order_id, headers, params=None):
        return self._request(
            "GET",
            f"{BASE}/distributor-orders/{order_id}/allocation-lines",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Warehouses
    # ------------------------------------------------------------------

    def create_warehouse(self, payload, headers):
        return self._request("POST", f"{BASE}/warehouses", payload, headers)

    def list_warehouses(self, headers, params=None):
        return self._request("GET", f"{BASE}/warehouses", headers=headers, params=params)

    def get_warehouse(self, warehouse_id, headers):
        return self._request("GET", f"{BASE}/warehouses/{warehouse_id}", headers=headers)

    def list_warehouse_reservations(self, warehouse_id, headers, params=None):
        return self._request(
            "GET",
            f"{BASE}/warehouses/{warehouse_id}/reservations",
            headers=headers,
            params=params,
        )

    def get_warehouse_occupancy(self, warehouse_id, headers, params=None):
        return self._request(
            "GET",
            f"{BASE}/warehouses/{warehouse_id}/occupancy",
            headers=headers,
            params=params,
        )

    def get_warehouse_carrying_cost(self, warehouse_id, headers, params=None):
        return self._request(
            "GET",
            f"{BASE}/warehouses/{warehouse_id}/carrying-cost",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Warehouse reservations
    # ------------------------------------------------------------------

    def create_warehouse_reservation(self, payload, headers):
        return self._request("POST", f"{BASE}/warehouse-reservations", payload, headers)

    def get_warehouse_reservation(self, reservation_id, headers):
        return self._request(
            "GET", f"{BASE}/warehouse-reservations/{reservation_id}", headers=headers
        )

    def release_warehouse_reservation(self, reservation_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/warehouse-reservations/{reservation_id}/release",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Test cells
    # ------------------------------------------------------------------

    def create_test_cell(self, payload, headers):
        return self._request("POST", f"{BASE}/test-cells", payload, headers)

    def list_test_cells(self, headers, params=None):
        return self._request("GET", f"{BASE}/test-cells", headers=headers, params=params)

    def get_test_cell(self, cell_id, headers):
        return self._request("GET", f"{BASE}/test-cells/{cell_id}", headers=headers)

    def list_test_cell_run_tests(self, cell_id, headers, params=None):
        return self._request(
            "GET",
            f"{BASE}/test-cells/{cell_id}/run-tests",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Build orders
    # ------------------------------------------------------------------

    def create_build_order(self, payload, headers):
        return self._request("POST", f"{BASE}/build-orders", payload, headers)

    def list_build_orders(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/build-orders", headers=headers, params=params
        )

    def get_build_order(self, build_order_id, headers):
        return self._request(
            "GET", f"{BASE}/build-orders/{build_order_id}", headers=headers
        )

    def start_coil_fab(self, build_order_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/build-orders/{build_order_id}/start-coil-fab",
            payload or {},
            headers,
        )

    def complete_brazing(self, build_order_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/build-orders/{build_order_id}/complete-brazing",
            payload or {},
            headers,
        )

    def charge_build_order(self, build_order_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/build-orders/{build_order_id}/charge", payload, headers
        )

    def release_to_stock(self, build_order_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/build-orders/{build_order_id}/release-to-stock",
            payload or {},
            headers,
        )

    def cancel_build_order(self, build_order_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/build-orders/{build_order_id}/cancel", payload, headers
        )

    def list_build_order_leak_tests(self, build_order_id, headers, params=None):
        return self._request(
            "GET",
            f"{BASE}/build-orders/{build_order_id}/leak-tests",
            headers=headers,
            params=params,
        )

    def list_build_order_run_tests(self, build_order_id, headers, params=None):
        return self._request(
            "GET",
            f"{BASE}/build-orders/{build_order_id}/run-tests",
            headers=headers,
            params=params,
        )

    def list_build_order_warehouse_reservations(
        self, build_order_id, headers, params=None
    ):
        return self._request(
            "GET",
            f"{BASE}/build-orders/{build_order_id}/warehouse-reservations",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Leak tests
    # ------------------------------------------------------------------

    def create_leak_test(self, payload, headers):
        return self._request("POST", f"{BASE}/leak-tests", payload, headers)

    def list_leak_tests(self, headers, params=None):
        return self._request("GET", f"{BASE}/leak-tests", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Run tests
    # ------------------------------------------------------------------

    def create_run_test(self, payload, headers):
        return self._request("POST", f"{BASE}/run-tests", payload, headers)

    def list_run_tests(self, headers, params=None):
        return self._request("GET", f"{BASE}/run-tests", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Warranty claims
    # ------------------------------------------------------------------

    def create_warranty_claim(self, payload, headers):
        return self._request("POST", f"{BASE}/warranty-claims", payload, headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/warranty-claims", headers=headers, params=params
        )

    def get_warranty_claim(self, claim_id, headers):
        return self._request(
            "GET", f"{BASE}/warranty-claims/{claim_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Supplier corrective actions
    # ------------------------------------------------------------------

    def list_supplier_corrective_actions(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/supplier-corrective-actions", headers=headers, params=params
        )

    def get_supplier_corrective_action(self, action_id, headers):
        return self._request(
            "GET", f"{BASE}/supplier-corrective-actions/{action_id}", headers=headers
        )

    def close_supplier_corrective_action(self, action_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/supplier-corrective-actions/{action_id}/close",
            payload,
            headers,
        )


api_client = ApiClient()
