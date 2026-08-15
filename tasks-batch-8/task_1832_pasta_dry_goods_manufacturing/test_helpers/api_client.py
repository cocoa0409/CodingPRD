"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- IngredientContract ---
    def create_contract(self, payload, headers):
        return self._request("POST", "/ingredient-contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/ingredient-contracts/{contract_id}", headers=headers)

    def activate_contract(self, contract_id, headers):
        return self._request("POST", f"/ingredient-contracts/{contract_id}/activate", {}, headers)

    def close_contract(self, contract_id, headers):
        return self._request("POST", f"/ingredient-contracts/{contract_id}/close", {}, headers)

    def create_index_reading(self, contract_id, payload, headers):
        return self._request("POST", f"/ingredient-contracts/{contract_id}/index-readings", payload, headers)

    def list_index_readings(self, contract_id, headers, params=None):
        return self._request("GET", f"/ingredient-contracts/{contract_id}/index-readings", headers=headers, params=params)

    # --- SemolinaLot ---
    def create_semolina_lot(self, payload, headers):
        return self._request("POST", "/semolina-lots", payload, headers)

    def list_semolina_lots(self, headers, params=None):
        return self._request("GET", "/semolina-lots", headers=headers, params=params)

    def get_semolina_lot(self, lot_id, headers):
        return self._request("GET", f"/semolina-lots/{lot_id}", headers=headers)

    def submit_lot_lab_results(self, lot_id, payload, headers):
        return self._request("POST", f"/semolina-lots/{lot_id}/lab-results", payload, headers)

    def accept_lot(self, lot_id, headers):
        return self._request("POST", f"/semolina-lots/{lot_id}/accept", {}, headers)

    def reject_lot(self, lot_id, headers):
        return self._request("POST", f"/semolina-lots/{lot_id}/reject", {}, headers)

    # --- Recipe ---
    def create_recipe(self, payload, headers):
        return self._request("POST", "/recipes", payload, headers)

    def list_recipes(self, headers, params=None):
        return self._request("GET", "/recipes", headers=headers, params=params)

    def get_recipe(self, recipe_id, headers):
        return self._request("GET", f"/recipes/{recipe_id}", headers=headers)

    def list_recipe_ingredients(self, recipe_id, headers, params=None):
        return self._request("GET", f"/recipes/{recipe_id}/ingredients", headers=headers, params=params)

    def approve_recipe(self, recipe_id, headers):
        return self._request("POST", f"/recipes/{recipe_id}/approve", {}, headers)

    def amend_recipe(self, recipe_id, payload, headers):
        return self._request("POST", f"/recipes/{recipe_id}/amend", payload, headers)

    def retire_recipe(self, recipe_id, headers):
        return self._request("POST", f"/recipes/{recipe_id}/retire", {}, headers)

    # --- ProductionLine ---
    def create_production_line(self, payload, headers):
        return self._request("POST", "/production-lines", payload, headers)

    def get_production_line(self, line_id, headers):
        return self._request("GET", f"/production-lines/{line_id}", headers=headers)

    def start_line_cleaning(self, line_id, headers):
        return self._request("POST", f"/production-lines/{line_id}/start-cleaning", {}, headers)

    def complete_line_cleaning(self, line_id, headers):
        return self._request("POST", f"/production-lines/{line_id}/complete-cleaning", {}, headers)

    # --- ExtrusionDie ---
    def create_extrusion_die(self, payload, headers):
        return self._request("POST", "/extrusion-dies", payload, headers)

    def list_extrusion_dies(self, headers, params=None):
        return self._request("GET", "/extrusion-dies", headers=headers, params=params)

    def get_extrusion_die(self, die_id, headers):
        return self._request("GET", f"/extrusion-dies/{die_id}", headers=headers)

    def mount_die(self, die_id, payload, headers):
        return self._request("POST", f"/extrusion-dies/{die_id}/mount", payload, headers)

    def unmount_die(self, die_id, headers):
        return self._request("POST", f"/extrusion-dies/{die_id}/unmount", {}, headers)

    def complete_die_cleaning(self, die_id, payload, headers):
        return self._request("POST", f"/extrusion-dies/{die_id}/complete-cleaning", payload, headers)

    # --- ProductionRun ---
    def create_production_run(self, payload, headers):
        return self._request("POST", "/production-runs", payload, headers)

    def list_production_runs(self, headers, params=None):
        return self._request("GET", "/production-runs", headers=headers, params=params)

    def get_production_run(self, run_id, headers):
        return self._request("GET", f"/production-runs/{run_id}", headers=headers)

    def reschedule_run(self, run_id, payload, headers):
        return self._request("PATCH", f"/production-runs/{run_id}", payload, headers)

    def advance_run(self, run_id, payload, headers):
        return self._request("POST", f"/production-runs/{run_id}/advance", payload, headers)

    def abort_run(self, run_id, headers):
        return self._request("POST", f"/production-runs/{run_id}/abort", {}, headers)

    def quality_hold_run(self, run_id, headers):
        return self._request("POST", f"/production-runs/{run_id}/quality-hold", {}, headers)

    def quality_release_run(self, run_id, headers):
        return self._request("POST", f"/production-runs/{run_id}/quality-release", {}, headers)

    def quality_reject_run(self, run_id, headers):
        return self._request("POST", f"/production-runs/{run_id}/quality-reject", {}, headers)

    # --- DryingSession ---
    def list_drying_sessions(self, headers, params=None):
        return self._request("GET", "/drying-sessions", headers=headers, params=params)

    def get_drying_session(self, session_id, headers):
        return self._request("GET", f"/drying-sessions/{session_id}", headers=headers)

    def record_inline_reading(self, session_id, headers):
        return self._request("POST", f"/drying-sessions/{session_id}/inline-readings", {}, headers)

    def finish_drying_session(self, session_id, headers):
        return self._request("POST", f"/drying-sessions/{session_id}/finish", {}, headers)

    def submit_drying_lab_results(self, session_id, payload, headers):
        return self._request("POST", f"/drying-sessions/{session_id}/lab-results", payload, headers)

    def redry_session(self, session_id, headers):
        return self._request("POST", f"/drying-sessions/{session_id}/redry", {}, headers)

    # --- PackagingJob ---
    def list_packaging_jobs(self, headers, params=None):
        return self._request("GET", "/packaging-jobs", headers=headers, params=params)

    def get_packaging_job(self, job_id, headers):
        return self._request("GET", f"/packaging-jobs/{job_id}", headers=headers)

    def verify_labels(self, job_id, headers):
        return self._request("POST", f"/packaging-jobs/{job_id}/verify-labels", {}, headers)

    def complete_packaging_job(self, job_id, headers):
        return self._request("POST", f"/packaging-jobs/{job_id}/complete", {}, headers)

    # --- WarehouseZone ---
    def create_warehouse_zone(self, payload, headers):
        return self._request("POST", "/warehouse-zones", payload, headers)

    def get_warehouse_zone(self, zone_id, headers):
        return self._request("GET", f"/warehouse-zones/{zone_id}", headers=headers)

    def lift_quarantine(self, zone_id, headers):
        return self._request("POST", f"/warehouse-zones/{zone_id}/lift-quarantine", {}, headers)

    # --- FinishedGoodsLot ---
    def list_finished_goods_lots(self, headers, params=None):
        return self._request("GET", "/finished-goods-lots", headers=headers, params=params)

    def get_finished_goods_lot(self, lot_id, headers):
        return self._request("GET", f"/finished-goods-lots/{lot_id}", headers=headers)

    def put_away_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/finished-goods-lots/{lot_id}/put-away", payload, headers)

    def release_goods_lot(self, lot_id, headers):
        return self._request("POST", f"/finished-goods-lots/{lot_id}/release", {}, headers)

    # --- PestInspection ---
    def create_pest_inspection(self, payload, headers):
        return self._request("POST", "/pest-inspections", payload, headers)

    def list_pest_inspections(self, headers, params=None):
        return self._request("GET", "/pest-inspections", headers=headers, params=params)

    def get_pest_inspection(self, inspection_id, headers):
        return self._request("GET", f"/pest-inspections/{inspection_id}", headers=headers)

    def verify_pest_inspection(self, inspection_id, headers):
        return self._request("POST", f"/pest-inspections/{inspection_id}/verify", {}, headers)

    # --- GlutenTest ---
    def create_gluten_test(self, payload, headers):
        return self._request("POST", "/gluten-tests", payload, headers)

    def list_gluten_tests(self, headers, params=None):
        return self._request("GET", "/gluten-tests", headers=headers, params=params)

    def get_gluten_test(self, test_id, headers):
        return self._request("GET", f"/gluten-tests/{test_id}", headers=headers)

    def verify_gluten_test(self, test_id, headers):
        return self._request("POST", f"/gluten-tests/{test_id}/verify", {}, headers)


api_client = ApiClient()
