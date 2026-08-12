"""API client: one method per endpoint defined in the PRD (§4 routing table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Customer ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/ecoat/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/ecoat/customers/{customer_id}", headers=headers)

    # --- CoatingSpec ---
    def create_coating_spec(self, payload, headers):
        return self._request("POST", "/ecoat/coating-specs", payload, headers)

    def get_coating_spec(self, spec_id, headers):
        return self._request("GET", f"/ecoat/coating-specs/{spec_id}", headers=headers)

    def list_coating_specs(self, headers, params=None):
        return self._request("GET", "/ecoat/coating-specs", headers=headers, params=params)

    # --- PaintLine ---
    def create_paint_line(self, payload, headers):
        return self._request("POST", "/ecoat/paint-lines", payload, headers)

    def get_paint_line(self, line_id, headers):
        return self._request("GET", f"/ecoat/paint-lines/{line_id}", headers=headers)

    def set_line_speed(self, line_id, payload, headers):
        return self._request("POST", f"/ecoat/paint-lines/{line_id}/set-line-speed", payload, headers)

    def list_pretreatment_stages_of_line(self, line_id, headers):
        return self._request("GET", f"/ecoat/paint-lines/{line_id}/pretreatment-stages", headers=headers)

    # --- CureOven ---
    def create_cure_oven(self, payload, headers):
        return self._request("POST", "/ecoat/cure-ovens", payload, headers)

    def get_cure_oven(self, oven_id, headers):
        return self._request("GET", f"/ecoat/cure-ovens/{oven_id}", headers=headers)

    # --- PretreatmentStage / titration ---
    def create_pretreatment_stage(self, payload, headers):
        return self._request("POST", "/ecoat/pretreatment-stages", payload, headers)

    def get_pretreatment_stage(self, stage_id, headers):
        return self._request("GET", f"/ecoat/pretreatment-stages/{stage_id}", headers=headers)

    def record_adjustment(self, stage_id, payload, headers):
        return self._request("POST", f"/ecoat/pretreatment-stages/{stage_id}/adjustments", payload, headers)

    def record_titration_reading(self, payload, headers):
        return self._request("POST", "/ecoat/titration-readings", payload, headers)

    def list_titration_readings(self, stage_id, headers):
        return self._request("GET", f"/ecoat/pretreatment-stages/{stage_id}/titration-readings", headers=headers)

    # --- Lot ---
    def create_lot(self, payload, headers):
        return self._request("POST", "/ecoat/lots", payload, headers)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/ecoat/lots/{lot_id}", headers=headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", "/ecoat/lots", headers=headers, params=params)

    def accept_lot(self, lot_id, headers):
        return self._request("POST", f"/ecoat/lots/{lot_id}/accept", {}, headers)

    def cancel_lot(self, lot_id, headers):
        return self._request("POST", f"/ecoat/lots/{lot_id}/cancel", {}, headers)

    def release_lot(self, lot_id, headers):
        return self._request("POST", f"/ecoat/lots/{lot_id}/release", {}, headers)

    # --- RunSlot ---
    def create_run_slot(self, payload, headers):
        return self._request("POST", "/ecoat/run-slots", payload, headers)

    def get_run_slot(self, slot_id, headers):
        return self._request("GET", f"/ecoat/run-slots/{slot_id}", headers=headers)

    def list_run_slots(self, headers, params=None):
        return self._request("GET", "/ecoat/run-slots", headers=headers, params=params)

    def start_run_slot(self, slot_id, headers):
        return self._request("POST", f"/ecoat/run-slots/{slot_id}/start", {}, headers)

    def complete_run_slot(self, slot_id, payload, headers):
        return self._request("POST", f"/ecoat/run-slots/{slot_id}/complete", payload, headers)

    def cancel_run_slot(self, slot_id, headers):
        return self._request("POST", f"/ecoat/run-slots/{slot_id}/cancel", {}, headers)

    # --- OvenCycle ---
    def create_oven_cycle(self, payload, headers):
        return self._request("POST", "/ecoat/oven-cycles", payload, headers)

    def get_oven_cycle(self, cycle_id, headers):
        return self._request("GET", f"/ecoat/oven-cycles/{cycle_id}", headers=headers)

    def list_oven_cycles(self, headers, params=None):
        return self._request("GET", "/ecoat/oven-cycles", headers=headers, params=params)

    # --- QualityTest ---
    def create_quality_test(self, payload, headers):
        return self._request("POST", "/ecoat/quality-tests", payload, headers)

    def list_quality_tests_of_lot(self, lot_id, headers):
        return self._request("GET", f"/ecoat/lots/{lot_id}/quality-tests", headers=headers)

    # --- ReworkOrder ---
    def get_rework_order(self, order_id, headers):
        return self._request("GET", f"/ecoat/rework-orders/{order_id}", headers=headers)

    def list_rework_orders_of_lot(self, lot_id, headers):
        return self._request("GET", f"/ecoat/lots/{lot_id}/rework-orders", headers=headers)

    def approve_rework_order(self, order_id, headers):
        return self._request("POST", f"/ecoat/rework-orders/{order_id}/approve", {}, headers)

    def complete_strip(self, order_id, payload, headers):
        return self._request("POST", f"/ecoat/rework-orders/{order_id}/complete-strip", payload, headers)

    # --- ColorChange ---
    def create_color_change(self, payload, headers):
        return self._request("POST", "/ecoat/color-changes", payload, headers)

    def get_color_change(self, change_id, headers):
        return self._request("GET", f"/ecoat/color-changes/{change_id}", headers=headers)

    def list_color_changes(self, headers, params=None):
        return self._request("GET", "/ecoat/color-changes", headers=headers, params=params)

    # --- VocPermit / EmissionEntry ---
    def create_voc_permit(self, payload, headers):
        return self._request("POST", "/ecoat/voc-permits", payload, headers)

    def get_voc_permit(self, permit_id, headers):
        return self._request("GET", f"/ecoat/voc-permits/{permit_id}", headers=headers)

    def close_voc_permit(self, permit_id, headers):
        return self._request("POST", f"/ecoat/voc-permits/{permit_id}/close", {}, headers)

    def list_emission_entries_of_permit(self, permit_id, headers):
        return self._request("GET", f"/ecoat/voc-permits/{permit_id}/emission-entries", headers=headers)

    def list_emission_entries(self, headers, params=None):
        return self._request("GET", "/ecoat/emission-entries", headers=headers, params=params)

    def get_emission_entry(self, entry_id, headers):
        return self._request("GET", f"/ecoat/emission-entries/{entry_id}", headers=headers)

    # --- Test-driving clock ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/ecoat/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
