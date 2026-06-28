"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Part ----
    def create_part(self, payload, headers):
        return self._request("POST", "/parts", payload, headers)

    def get_part(self, part_id, headers):
        return self._request("GET", f"/parts/{part_id}", headers=headers)

    def list_parts(self, headers, params=None):
        return self._request("GET", "/parts", headers=headers, params=params)

    # ---- Vendor ----
    def create_vendor(self, payload, headers):
        return self._request("POST", "/vendors", payload, headers)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/vendors/{vendor_id}", headers=headers)

    def suspend_vendor(self, vendor_id, headers):
        return self._request("POST", f"/vendors/{vendor_id}/suspend", {}, headers)

    # ---- AVL ----
    def create_avl_entry(self, payload, headers):
        return self._request("POST", "/avl-entries", payload, headers)

    def get_avl_entry(self, avl_id, headers):
        return self._request("GET", f"/avl-entries/{avl_id}", headers=headers)

    def list_avl_entries(self, headers, params=None):
        return self._request("GET", "/avl-entries", headers=headers, params=params)

    def revoke_avl_entry(self, avl_id, headers):
        return self._request("POST", f"/avl-entries/{avl_id}/revoke", {}, headers)

    def receive_lot(self, avl_id, payload, headers):
        return self._request("POST", f"/avl-entries/{avl_id}/receive-lot", payload, headers)

    # ---- InventoryLot ----
    def get_inventory_lot(self, lot_id, headers):
        return self._request("GET", f"/inventory-lots/{lot_id}", headers=headers)

    def list_inventory_lots(self, headers, params=None):
        return self._request("GET", "/inventory-lots", headers=headers, params=params)

    def quarantine_lot(self, lot_id, headers):
        return self._request("POST", f"/inventory-lots/{lot_id}/quarantine", {}, headers)

    # ---- BOM ----
    def create_bom(self, payload, headers):
        return self._request("POST", "/boms", payload, headers)

    def get_bom(self, bom_id, headers):
        return self._request("GET", f"/boms/{bom_id}", headers=headers)

    def list_boms(self, headers, params=None):
        return self._request("GET", "/boms", headers=headers, params=params)

    def add_bom_line(self, bom_id, payload, headers):
        return self._request("POST", f"/boms/{bom_id}/lines", payload, headers)

    def list_bom_lines_of(self, bom_id, headers):
        return self._request("GET", f"/boms/{bom_id}/lines", headers=headers)

    def list_bom_lines(self, headers, params=None):
        return self._request("GET", "/bom-lines", headers=headers, params=params)

    def get_bom_line(self, line_id, headers):
        return self._request("GET", f"/bom-lines/{line_id}", headers=headers)

    def release_bom(self, bom_id, headers):
        return self._request("POST", f"/boms/{bom_id}/release", {}, headers)

    # ---- LineProgram ----
    def create_line_program(self, payload, headers):
        return self._request("POST", "/line-programs", payload, headers)

    def get_line_program(self, prog_id, headers):
        return self._request("GET", f"/line-programs/{prog_id}", headers=headers)

    def list_line_programs(self, headers, params=None):
        return self._request("GET", "/line-programs", headers=headers, params=params)

    def verify_line_program(self, prog_id, headers):
        return self._request("POST", f"/line-programs/{prog_id}/verify", {}, headers)

    # ---- WorkOrder ----
    def create_work_order(self, payload, headers):
        return self._request("POST", "/work-orders", payload, headers)

    def get_work_order(self, wo_id, headers):
        return self._request("GET", f"/work-orders/{wo_id}", headers=headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/work-orders", headers=headers, params=params)

    def kit_work_order(self, wo_id, headers):
        return self._request("POST", f"/work-orders/{wo_id}/kit", {}, headers)

    def setup_work_order(self, wo_id, payload, headers):
        return self._request("POST", f"/work-orders/{wo_id}/setup", payload, headers)

    def start_work_order(self, wo_id, headers):
        return self._request("POST", f"/work-orders/{wo_id}/start", {}, headers)

    def serialize_unit(self, wo_id, headers):
        return self._request("POST", f"/work-orders/{wo_id}/units", {}, headers)

    def list_work_order_units(self, wo_id, headers):
        return self._request("GET", f"/work-orders/{wo_id}/units", headers=headers)

    def list_kit_requirements_of(self, wo_id, headers):
        return self._request("GET", f"/work-orders/{wo_id}/kit-requirements", headers=headers)

    def finalize_test(self, wo_id, headers):
        return self._request("POST", f"/work-orders/{wo_id}/finalize-test", {}, headers)

    def close_work_order(self, wo_id, headers):
        return self._request("POST", f"/work-orders/{wo_id}/close", {}, headers)

    def cancel_work_order(self, wo_id, headers):
        return self._request("POST", f"/work-orders/{wo_id}/cancel", {}, headers)

    def ship_work_order(self, wo_id, payload, headers):
        return self._request("POST", f"/work-orders/{wo_id}/ship", payload, headers)

    # ---- KitRequirement (read) ----
    def get_kit_requirement(self, kr_id, headers):
        return self._request("GET", f"/kit-requirements/{kr_id}", headers=headers)

    def list_all_kit_requirements(self, headers, params=None):
        return self._request("GET", "/kit-requirements", headers=headers, params=params)

    # ---- Unit ----
    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/units/{unit_id}", headers=headers)

    def record_test_result(self, unit_id, payload, headers):
        return self._request("POST", f"/units/{unit_id}/test-result", payload, headers)

    # ---- ReworkOrder ----
    def create_rework_order(self, payload, headers):
        return self._request("POST", "/rework-orders", payload, headers)

    def get_rework_order(self, rwo_id, headers):
        return self._request("GET", f"/rework-orders/{rwo_id}", headers=headers)

    def list_rework_orders(self, headers, params=None):
        return self._request("GET", "/rework-orders", headers=headers, params=params)

    def close_rework_order(self, rwo_id, payload, headers):
        return self._request("POST", f"/rework-orders/{rwo_id}/close", payload, headers)

    def abandon_rework_order(self, rwo_id, headers):
        return self._request("POST", f"/rework-orders/{rwo_id}/abandon", {}, headers)

    # ---- ECO ----
    def create_eco(self, payload, headers):
        return self._request("POST", "/ecos", payload, headers)

    def get_eco(self, eco_id, headers):
        return self._request("GET", f"/ecos/{eco_id}", headers=headers)

    def list_ecos(self, headers, params=None):
        return self._request("GET", "/ecos", headers=headers, params=params)

    def submit_eco(self, eco_id, payload, headers):
        return self._request("POST", f"/ecos/{eco_id}/submit", payload, headers)

    def approve_eco(self, eco_id, payload, headers):
        return self._request("POST", f"/ecos/{eco_id}/approve", payload, headers)

    def reject_eco(self, eco_id, headers):
        return self._request("POST", f"/ecos/{eco_id}/reject", {}, headers)

    def implement_eco(self, eco_id, headers):
        return self._request("POST", f"/ecos/{eco_id}/implement", {}, headers)

    # ---- RMA ----
    def create_rma(self, payload, headers):
        return self._request("POST", "/rmas", payload, headers)

    def get_rma(self, rma_id, headers):
        return self._request("GET", f"/rmas/{rma_id}", headers=headers)

    def list_rmas(self, headers, params=None):
        return self._request("GET", "/rmas", headers=headers, params=params)

    def triage_rma(self, rma_id, payload, headers):
        return self._request("POST", f"/rmas/{rma_id}/triage", payload, headers)

    def repair_rma(self, rma_id, headers):
        return self._request("POST", f"/rmas/{rma_id}/repair", {}, headers)

    def scrap_rma(self, rma_id, headers):
        return self._request("POST", f"/rmas/{rma_id}/scrap", {}, headers)

    def close_rma(self, rma_id, headers):
        return self._request("POST", f"/rmas/{rma_id}/close", {}, headers)

    # ---- Deterministic build-and-test driver ----
    def build_and_test_units(self, payload, headers):
        return self._request("POST", "/_test/build-and-test-units", payload, headers)


api_client = ApiClient()
