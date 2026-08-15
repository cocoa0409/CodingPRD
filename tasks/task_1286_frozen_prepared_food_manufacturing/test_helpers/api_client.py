"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock (PRD §2.6) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/plant/_clock/set_current_utc", payload, headers)

    # --- recipes / components ---
    def create_recipe(self, payload, headers):
        return self._request("POST", "/plant/recipes", payload, headers)

    def list_recipes(self, headers, params=None):
        return self._request("GET", "/plant/recipes", headers=headers, params=params)

    def get_recipe(self, recipe_id, headers):
        return self._request("GET", f"/plant/recipes/{recipe_id}", headers=headers)

    def add_component(self, recipe_id, payload, headers):
        return self._request("POST", f"/plant/recipes/{recipe_id}/components", payload, headers)

    def list_components(self, headers, params=None):
        return self._request("GET", "/plant/components", headers=headers, params=params)

    def get_component(self, component_id, headers):
        return self._request("GET", f"/plant/components/{component_id}", headers=headers)

    def reparent_component(self, component_id, payload, headers):
        return self._request("PATCH", f"/plant/components/{component_id}", payload, headers)

    def approve_recipe(self, recipe_id, headers):
        return self._request("POST", f"/plant/recipes/{recipe_id}/approve", {}, headers)

    def revise_recipe(self, recipe_id, headers):
        return self._request("POST", f"/plant/recipes/{recipe_id}/revise", {}, headers)

    def retire_recipe(self, recipe_id, headers):
        return self._request("POST", f"/plant/recipes/{recipe_id}/retire", {}, headers)

    def scale_preview(self, recipe_id, headers, params=None):
        return self._request("GET", f"/plant/recipes/{recipe_id}/scale-preview", headers=headers, params=params)

    # --- co-pack customers ---
    def create_copack_customer(self, payload, headers):
        return self._request("POST", "/plant/copack-customers", payload, headers)

    def get_copack_customer(self, customer_id, headers):
        return self._request("GET", f"/plant/copack-customers/{customer_id}", headers=headers)

    # --- production orders ---
    def create_production_order(self, payload, headers):
        return self._request("POST", "/plant/production-orders", payload, headers)

    def list_production_orders(self, headers, params=None):
        return self._request("GET", "/plant/production-orders", headers=headers, params=params)

    def get_production_order(self, order_id, headers):
        return self._request("GET", f"/plant/production-orders/{order_id}", headers=headers)

    def cancel_production_order(self, order_id, headers):
        return self._request("POST", f"/plant/production-orders/{order_id}/cancel", {}, headers)

    # --- production batches ---
    def create_batch(self, order_id, payload, headers):
        return self._request("POST", f"/plant/production-orders/{order_id}/batches", payload, headers)

    def list_order_batches(self, order_id, headers, params=None):
        return self._request("GET", f"/plant/production-orders/{order_id}/batches", headers=headers, params=params)

    def list_batches(self, headers, params=None):
        return self._request("GET", "/plant/production-batches", headers=headers, params=params)

    def get_batch(self, batch_id, headers):
        return self._request("GET", f"/plant/production-batches/{batch_id}", headers=headers)

    def kit_batch(self, batch_id, headers):
        return self._request("POST", f"/plant/production-batches/{batch_id}/kit", {}, headers)

    def cook_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/plant/production-batches/{batch_id}/cook", payload, headers)

    def complete_batch(self, batch_id, headers):
        return self._request("POST", f"/plant/production-batches/{batch_id}/complete", {}, headers)

    def hold_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/plant/production-batches/{batch_id}/hold", payload, headers)

    def resume_batch(self, batch_id, headers):
        return self._request("POST", f"/plant/production-batches/{batch_id}/resume", {}, headers)

    def rework_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/plant/production-batches/{batch_id}/rework", payload, headers)

    def cancel_batch(self, batch_id, headers):
        return self._request("POST", f"/plant/production-batches/{batch_id}/cancel", {}, headers)

    # --- blast freezer cells ---
    def create_freezer_cell(self, payload, headers):
        return self._request("POST", "/plant/freezer-cells", payload, headers)

    def list_freezer_cells(self, headers, params=None):
        return self._request("GET", "/plant/freezer-cells", headers=headers, params=params)

    def get_freezer_cell(self, cell_id, headers):
        return self._request("GET", f"/plant/freezer-cells/{cell_id}", headers=headers)

    # --- freezing cycles ---
    def create_freezing_cycle(self, batch_id, payload, headers):
        return self._request("POST", f"/plant/production-batches/{batch_id}/freezing-cycles", payload, headers)

    def list_freezing_cycles(self, headers, params=None):
        return self._request("GET", "/plant/freezing-cycles", headers=headers, params=params)

    def get_freezing_cycle(self, cycle_id, headers):
        return self._request("GET", f"/plant/freezing-cycles/{cycle_id}", headers=headers)

    def start_freezing_cycle(self, cycle_id, headers):
        return self._request("POST", f"/plant/freezing-cycles/{cycle_id}/start", {}, headers)

    def complete_freezing_cycle(self, cycle_id, payload, headers):
        return self._request("POST", f"/plant/freezing-cycles/{cycle_id}/complete", payload, headers)

    def void_freezing_cycle(self, cycle_id, headers):
        return self._request("POST", f"/plant/freezing-cycles/{cycle_id}/void", {}, headers)

    # --- packaging lines ---
    def create_packaging_line(self, payload, headers):
        return self._request("POST", "/plant/packaging-lines", payload, headers)

    def list_packaging_lines(self, headers, params=None):
        return self._request("GET", "/plant/packaging-lines", headers=headers, params=params)

    def get_packaging_line(self, line_id, headers):
        return self._request("GET", f"/plant/packaging-lines/{line_id}", headers=headers)

    # --- line runs ---
    def create_line_run(self, line_id, payload, headers):
        return self._request("POST", f"/plant/packaging-lines/{line_id}/runs", payload, headers)

    def list_line_runs(self, headers, params=None):
        return self._request("GET", "/plant/line-runs", headers=headers, params=params)

    def get_line_run(self, run_id, headers):
        return self._request("GET", f"/plant/line-runs/{run_id}", headers=headers)

    def start_line_run(self, run_id, headers):
        return self._request("POST", f"/plant/line-runs/{run_id}/start", {}, headers)

    def complete_line_run(self, run_id, payload, headers):
        return self._request("POST", f"/plant/line-runs/{run_id}/complete", payload, headers)

    def cancel_line_run(self, run_id, headers):
        return self._request("POST", f"/plant/line-runs/{run_id}/cancel", {}, headers)

    # --- film supply lots ---
    def create_film_lot(self, payload, headers):
        return self._request("POST", "/plant/film-lots", payload, headers)

    def list_film_lots(self, headers, params=None):
        return self._request("GET", "/plant/film-lots", headers=headers, params=params)

    def get_film_lot(self, lot_id, headers):
        return self._request("GET", f"/plant/film-lots/{lot_id}", headers=headers)

    def quarantine_film_lot(self, lot_id, headers):
        return self._request("POST", f"/plant/film-lots/{lot_id}/quarantine", {}, headers)

    def release_film_quarantine(self, lot_id, headers):
        return self._request("POST", f"/plant/film-lots/{lot_id}/release-quarantine", {}, headers)

    # --- CCP checks ---
    def create_ccp_check(self, batch_id, payload, headers):
        return self._request("POST", f"/plant/production-batches/{batch_id}/ccp-checks", payload, headers)

    def get_ccp_check(self, check_id, headers):
        return self._request("GET", f"/plant/ccp-checks/{check_id}", headers=headers)

    def list_ccp_checks(self, headers, params=None):
        return self._request("GET", "/plant/ccp-checks", headers=headers, params=params)

    def list_batch_ccp_checks(self, batch_id, headers, params=None):
        return self._request("GET", f"/plant/production-batches/{batch_id}/ccp-checks", headers=headers, params=params)

    # --- storage slots ---
    def create_storage_slot(self, payload, headers):
        return self._request("POST", "/plant/storage-slots", payload, headers)

    def list_storage_slots(self, headers, params=None):
        return self._request("GET", "/plant/storage-slots", headers=headers, params=params)

    def get_storage_slot(self, slot_id, headers):
        return self._request("GET", f"/plant/storage-slots/{slot_id}", headers=headers)

    # --- finished goods lots ---
    def list_lots(self, headers, params=None):
        return self._request("GET", "/plant/lots", headers=headers, params=params)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/plant/lots/{lot_id}", headers=headers)

    def put_away_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/plant/lots/{lot_id}/put-away", payload, headers)

    def withdraw_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/plant/lots/{lot_id}/withdraw", payload, headers)

    def quarantine_lot(self, lot_id, headers):
        return self._request("POST", f"/plant/lots/{lot_id}/quarantine", {}, headers)

    def release_lot(self, lot_id, headers):
        return self._request("POST", f"/plant/lots/{lot_id}/release", {}, headers)

    def reject_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/plant/lots/{lot_id}/reject", payload, headers)

    def rework_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/plant/lots/{lot_id}/rework", payload, headers)

    def recall_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/plant/lots/{lot_id}/recall", payload, headers)

    # --- complaints ---
    def create_complaint(self, payload, headers):
        return self._request("POST", "/plant/complaints", payload, headers)

    def list_complaints(self, headers, params=None):
        return self._request("GET", "/plant/complaints", headers=headers, params=params)

    def get_complaint(self, complaint_id, headers):
        return self._request("GET", f"/plant/complaints/{complaint_id}", headers=headers)

    def list_lot_complaints(self, lot_id, headers, params=None):
        return self._request("GET", f"/plant/lots/{lot_id}/complaints", headers=headers, params=params)

    def investigate_complaint(self, complaint_id, headers):
        return self._request("POST", f"/plant/complaints/{complaint_id}/investigate", {}, headers)

    def resolve_complaint(self, complaint_id, payload, headers):
        return self._request("POST", f"/plant/complaints/{complaint_id}/resolve", payload, headers)


api_client = ApiClient()
