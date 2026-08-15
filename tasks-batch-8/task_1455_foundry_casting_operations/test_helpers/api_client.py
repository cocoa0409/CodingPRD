"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD §2.4) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Foundry ---
    def create_foundry(self, payload, headers):
        return self._request("POST", "/api/foundries", payload, headers)

    def get_foundry(self, foundry_id, headers):
        return self._request("GET", f"/api/foundries/{foundry_id}", headers=headers)

    def run_ops(self, foundry_id, payload, headers):
        return self._request("POST", f"/api/foundries/{foundry_id}/run-ops", payload, headers)

    # --- Customer ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/api/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/api/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/api/customers", headers=headers, params=params)

    # --- Pattern ---
    def create_pattern(self, payload, headers):
        return self._request("POST", "/api/patterns", payload, headers)

    def get_pattern(self, pattern_id, headers):
        return self._request("GET", f"/api/patterns/{pattern_id}", headers=headers)

    def list_patterns(self, headers, params=None):
        return self._request("GET", "/api/patterns", headers=headers, params=params)

    def qualify_pattern(self, pattern_id, payload, headers):
        return self._request("POST", f"/api/patterns/{pattern_id}/qualify", payload, headers)

    def retire_pattern(self, pattern_id, headers):
        return self._request("POST", f"/api/patterns/{pattern_id}/retire", {}, headers)

    # --- CustomerOrder ---
    def create_order(self, payload, headers):
        return self._request("POST", "/api/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/api/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/api/orders", headers=headers, params=params)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/api/orders/{order_id}/cancel", {}, headers)

    # --- Equipment ---
    def create_equipment(self, payload, headers):
        return self._request("POST", "/api/equipment", payload, headers)

    def get_equipment(self, equipment_id, headers):
        return self._request("GET", f"/api/equipment/{equipment_id}", headers=headers)

    def list_equipment(self, headers, params=None):
        return self._request("GET", "/api/equipment", headers=headers, params=params)

    def add_equipment_window(self, equipment_id, payload, headers):
        return self._request("POST", f"/api/equipment/{equipment_id}/windows", payload, headers)

    # --- MeltHeat ---
    def create_heat(self, payload, headers):
        return self._request("POST", "/api/heats", payload, headers)

    def get_heat(self, heat_id, headers):
        return self._request("GET", f"/api/heats/{heat_id}", headers=headers)

    def list_heats(self, headers, params=None):
        return self._request("GET", "/api/heats", headers=headers, params=params)

    def add_heat_charges(self, heat_id, payload, headers):
        return self._request("POST", f"/api/heats/{heat_id}/charges", payload, headers)

    def add_heat_sample(self, heat_id, payload, headers):
        return self._request("POST", f"/api/heats/{heat_id}/samples", payload, headers)

    def tap_heat(self, heat_id, payload, headers):
        return self._request("POST", f"/api/heats/{heat_id}/tap", payload, headers)

    # --- PourSlot ---
    def create_pour_slot(self, payload, headers):
        return self._request("POST", "/api/pour-slots", payload, headers)

    def get_pour_slot(self, slot_id, headers):
        return self._request("GET", f"/api/pour-slots/{slot_id}", headers=headers)

    def list_pour_slots(self, headers, params=None):
        return self._request("GET", "/api/pour-slots", headers=headers, params=params)

    def cancel_pour_slot(self, slot_id, headers):
        return self._request("POST", f"/api/pour-slots/{slot_id}/cancel", {}, headers)

    def complete_pour_slot(self, slot_id, headers):
        return self._request("POST", f"/api/pour-slots/{slot_id}/complete", {}, headers)

    # --- Mold ---
    def create_mold(self, payload, headers):
        return self._request("POST", "/api/molds", payload, headers)

    def get_mold(self, mold_id, headers):
        return self._request("GET", f"/api/molds/{mold_id}", headers=headers)

    def list_molds(self, headers, params=None):
        return self._request("GET", "/api/molds", headers=headers, params=params)

    def shakeout_mold(self, mold_id, headers):
        return self._request("POST", f"/api/molds/{mold_id}/shakeout", {}, headers)

    # --- Casting ---
    def get_casting(self, casting_id, headers):
        return self._request("GET", f"/api/castings/{casting_id}", headers=headers)

    def list_castings(self, headers, params=None):
        return self._request("GET", "/api/castings", headers=headers, params=params)

    def advance_casting(self, casting_id, headers):
        return self._request("POST", f"/api/castings/{casting_id}/advance", {}, headers)

    # --- InspectionReport ---
    def create_inspection(self, payload, headers):
        return self._request("POST", "/api/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/api/inspections/{inspection_id}", headers=headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/api/inspections", headers=headers, params=params)

    def disposition_inspection(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"/api/inspections/{inspection_id}/disposition", payload, headers
        )

    # --- ScrapRecord ---
    def get_scrap_record(self, scrap_id, headers):
        return self._request("GET", f"/api/scrap-records/{scrap_id}", headers=headers)

    def list_scrap_records(self, headers, params=None):
        return self._request("GET", "/api/scrap-records", headers=headers, params=params)

    def weigh_scrap_record(self, scrap_id, payload, headers):
        return self._request("POST", f"/api/scrap-records/{scrap_id}/weigh", payload, headers)

    # --- ReturnLot ---
    def create_return_lot(self, payload, headers):
        return self._request("POST", "/api/return-lots", payload, headers)

    def get_return_lot(self, lot_id, headers):
        return self._request("GET", f"/api/return-lots/{lot_id}", headers=headers)

    def list_return_lots(self, headers, params=None):
        return self._request("GET", "/api/return-lots", headers=headers, params=params)

    def assay_return_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/api/return-lots/{lot_id}/assay", payload, headers)

    # --- SandBatch ---
    def create_sand_batch(self, payload, headers):
        return self._request("POST", "/api/sand-batches", payload, headers)

    def get_sand_batch(self, batch_id, headers):
        return self._request("GET", f"/api/sand-batches/{batch_id}", headers=headers)

    def list_sand_batches(self, headers, params=None):
        return self._request("GET", "/api/sand-batches", headers=headers, params=params)

    def test_sand_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/api/sand-batches/{batch_id}/test", payload, headers)

    def reclaim_sand_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/api/sand-batches/{batch_id}/reclaim", payload, headers)

    # --- WarrantyClaim ---
    def create_claim(self, payload, headers):
        return self._request("POST", "/api/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/api/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/api/claims", headers=headers, params=params)

    def review_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/api/claims/{claim_id}/review", payload, headers)

    def settle_claim(self, claim_id, headers):
        return self._request("POST", f"/api/claims/{claim_id}/settle", {}, headers)


api_client = ApiClient()
