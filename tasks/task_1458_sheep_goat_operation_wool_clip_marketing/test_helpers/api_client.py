"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Flocks ----
    def create_flock(self, payload, headers):
        return self._request("POST", "/api/flocks", payload, headers)

    def list_flocks(self, headers, params=None):
        return self._request("GET", "/api/flocks", headers=headers, params=params)

    def get_flock(self, flock_id, headers):
        return self._request("GET", f"/api/flocks/{flock_id}", headers=headers)

    def retire_flock(self, flock_id, headers):
        return self._request("POST", f"/api/flocks/{flock_id}/retire", {}, headers)

    # ---- Breeding seasons ----
    def create_breeding_season(self, payload, headers):
        return self._request("POST", "/api/breeding-seasons", payload, headers)

    def list_breeding_seasons(self, headers, params=None):
        return self._request("GET", "/api/breeding-seasons", headers=headers, params=params)

    def get_breeding_season(self, season_id, headers):
        return self._request("GET", f"/api/breeding-seasons/{season_id}", headers=headers)

    def transition_breeding_season(self, season_id, payload, headers):
        return self._request("POST", f"/api/breeding-seasons/{season_id}/transitions", payload, headers)

    # ---- Birth records ----
    def create_birth_record(self, payload, headers):
        return self._request("POST", "/api/birth-records", payload, headers)

    def list_birth_records(self, headers, params=None):
        return self._request("GET", "/api/birth-records", headers=headers, params=params)

    def get_birth_record(self, record_id, headers):
        return self._request("GET", f"/api/birth-records/{record_id}", headers=headers)

    # ---- Pastures ----
    def create_pasture(self, payload, headers):
        return self._request("POST", "/api/pastures", payload, headers)

    def get_pasture(self, pasture_id, headers):
        return self._request("GET", f"/api/pastures/{pasture_id}", headers=headers)

    # ---- Grazing moves ----
    def create_grazing_move(self, payload, headers):
        return self._request("POST", "/api/grazing-moves", payload, headers)

    def list_grazing_moves(self, headers, params=None):
        return self._request("GET", "/api/grazing-moves", headers=headers, params=params)

    def get_grazing_move(self, move_id, headers):
        return self._request("GET", f"/api/grazing-moves/{move_id}", headers=headers)

    def transition_grazing_move(self, move_id, payload, headers):
        return self._request("POST", f"/api/grazing-moves/{move_id}/transitions", payload, headers)

    # ---- Parasite treatments ----
    def create_parasite_treatment(self, payload, headers):
        return self._request("POST", "/api/parasite-treatments", payload, headers)

    def list_parasite_treatments(self, headers, params=None):
        return self._request("GET", "/api/parasite-treatments", headers=headers, params=params)

    def get_parasite_treatment(self, treatment_id, headers):
        return self._request("GET", f"/api/parasite-treatments/{treatment_id}", headers=headers)

    def post_treatment_follow_up(self, treatment_id, payload, headers):
        return self._request("POST", f"/api/parasite-treatments/{treatment_id}/follow-up", payload, headers)

    # ---- Shearing crews ----
    def create_shearing_crew(self, payload, headers):
        return self._request("POST", "/api/shearing-crews", payload, headers)

    def get_shearing_crew(self, crew_id, headers):
        return self._request("GET", f"/api/shearing-crews/{crew_id}", headers=headers)

    def deactivate_shearing_crew(self, crew_id, headers):
        return self._request("POST", f"/api/shearing-crews/{crew_id}/deactivate", {}, headers)

    # ---- Shearing events ----
    def create_shearing_event(self, payload, headers):
        return self._request("POST", "/api/shearing-events", payload, headers)

    def list_shearing_events(self, headers, params=None):
        return self._request("GET", "/api/shearing-events", headers=headers, params=params)

    def get_shearing_event(self, event_id, headers):
        return self._request("GET", f"/api/shearing-events/{event_id}", headers=headers)

    def transition_shearing_event(self, event_id, payload, headers):
        return self._request("POST", f"/api/shearing-events/{event_id}/transitions", payload, headers)

    def complete_shearing_event(self, event_id, payload, headers):
        return self._request("POST", f"/api/shearing-events/{event_id}/complete", payload, headers)

    # ---- Wool clips ----
    def list_wool_clips(self, headers, params=None):
        return self._request("GET", "/api/wool-clips", headers=headers, params=params)

    def get_wool_clip(self, clip_id, headers):
        return self._request("GET", f"/api/wool-clips/{clip_id}", headers=headers)

    # ---- Wool lots ----
    def create_wool_lot(self, payload, headers):
        return self._request("POST", "/api/wool-lots", payload, headers)

    def list_wool_lots(self, headers, params=None):
        return self._request("GET", "/api/wool-lots", headers=headers, params=params)

    def get_wool_lot(self, lot_id, headers):
        return self._request("GET", f"/api/wool-lots/{lot_id}", headers=headers)

    def grade_wool_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/api/wool-lots/{lot_id}/grade", payload, headers)

    def transition_wool_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/api/wool-lots/{lot_id}/transitions", payload, headers)

    def regrade_wool_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/api/wool-lots/{lot_id}/regrade", payload, headers)

    def delete_wool_lot(self, lot_id, headers):
        return self._request("DELETE", f"/api/wool-lots/{lot_id}", headers=headers)

    # ---- Core tests ----
    def create_core_test(self, payload, headers):
        return self._request("POST", "/api/core-tests", payload, headers)

    def list_core_tests(self, headers, params=None):
        return self._request("GET", "/api/core-tests", headers=headers, params=params)

    def get_core_test(self, test_id, headers):
        return self._request("GET", f"/api/core-tests/{test_id}", headers=headers)

    def post_core_test_results(self, test_id, payload, headers):
        return self._request("POST", f"/api/core-tests/{test_id}/results", payload, headers)

    def transition_core_test(self, test_id, payload, headers):
        return self._request("POST", f"/api/core-tests/{test_id}/transitions", payload, headers)

    # ---- Consignments / pool statements ----
    def create_consignment(self, payload, headers):
        return self._request("POST", "/api/consignments", payload, headers)

    def list_consignments(self, headers, params=None):
        return self._request("GET", "/api/consignments", headers=headers, params=params)

    def get_consignment(self, consignment_id, headers):
        return self._request("GET", f"/api/consignments/{consignment_id}", headers=headers)

    def transition_consignment(self, consignment_id, payload, headers):
        return self._request("POST", f"/api/consignments/{consignment_id}/transitions", payload, headers)

    def sell_consignment(self, consignment_id, payload, headers):
        return self._request("POST", f"/api/consignments/{consignment_id}/sell", payload, headers)

    def get_pool_statement(self, pool_ref, headers):
        return self._request("GET", f"/api/pool-statements/{pool_ref}", headers=headers)

    # ---- Holiday windows ----
    def create_holiday_window(self, payload, headers):
        return self._request("POST", "/api/holiday-windows", payload, headers)

    # ---- Livestock sales ----
    def create_livestock_sale(self, payload, headers):
        return self._request("POST", "/api/livestock-sales", payload, headers)

    def list_livestock_sales(self, headers, params=None):
        return self._request("GET", "/api/livestock-sales", headers=headers, params=params)

    def get_livestock_sale(self, sale_id, headers):
        return self._request("GET", f"/api/livestock-sales/{sale_id}", headers=headers)

    def record_sale_payment(self, sale_id, payload, headers):
        return self._request("POST", f"/api/livestock-sales/{sale_id}/record-payment", payload, headers)

    def load_sale(self, sale_id, headers):
        return self._request("POST", f"/api/livestock-sales/{sale_id}/load", {}, headers)

    def deliver_sale(self, sale_id, payload, headers):
        return self._request("POST", f"/api/livestock-sales/{sale_id}/deliver", payload, headers)

    def cancel_sale(self, sale_id, headers):
        return self._request("POST", f"/api/livestock-sales/{sale_id}/cancel", {}, headers)

    # ---- Loss reports ----
    def create_loss_report(self, payload, headers):
        return self._request("POST", "/api/loss-reports", payload, headers)

    def list_loss_reports(self, headers, params=None):
        return self._request("GET", "/api/loss-reports", headers=headers, params=params)

    def get_loss_report(self, report_id, headers):
        return self._request("GET", f"/api/loss-reports/{report_id}", headers=headers)

    def transition_loss_report(self, report_id, payload, headers):
        return self._request("POST", f"/api/loss-reports/{report_id}/transitions", payload, headers)

    # ---- Grazing contracts ----
    def create_grazing_contract(self, payload, headers):
        return self._request("POST", "/api/grazing-contracts", payload, headers)

    def list_grazing_contracts(self, headers, params=None):
        return self._request("GET", "/api/grazing-contracts", headers=headers, params=params)

    def get_grazing_contract(self, contract_id, headers):
        return self._request("GET", f"/api/grazing-contracts/{contract_id}", headers=headers)

    def transition_grazing_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/api/grazing-contracts/{contract_id}/transitions", payload, headers)

    def counter_grazing_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/api/grazing-contracts/{contract_id}/counter", payload, headers)

    def complete_grazing_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/api/grazing-contracts/{contract_id}/complete", payload, headers)

    # ---- Logical clock (PlatformAdmin) ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/api/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
