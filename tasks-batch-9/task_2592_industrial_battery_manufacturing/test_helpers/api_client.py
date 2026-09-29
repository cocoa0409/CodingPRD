"""HTTP client with one method per endpoint of the battery manufacturing API."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class BatteryApiClient(GenericApiClient):
    """One method per endpoint; every method returns the raw response."""

    # --- Logical clock -----------------------------------------------------
    def set_clock(self, current_utc: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # --- Plants ------------------------------------------------------------
    def create_plant(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/plants", payload, headers)

    def list_plants(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/plants", params, headers)

    def get_plant(self, plant_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/plants/{plant_id}", None, headers)

    def update_plant(
        self, plant_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("PATCH", f"/plants/{plant_id}", payload, headers)

    def set_plant_permit(
        self, plant_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("PATCH", f"/plants/{plant_id}/permit", payload, headers)

    def get_emission_ledger(self, plant_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/plants/{plant_id}/emission-ledger", None, headers
        )

    def get_lead_mass_balance(self, plant_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/plants/{plant_id}/lead-mass-balance", None, headers
        )

    def get_fleet_analysis(self, plant_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/plants/{plant_id}/fleet-analysis", None, headers)

    # --- Workers -----------------------------------------------------------
    def create_worker(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/workers", payload, headers)

    def list_workers(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/workers", params, headers)

    def get_worker(self, worker_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/workers/{worker_id}", None, headers)

    def create_exposure_sample(
        self, worker_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/workers/{worker_id}/exposure-samples", payload, headers
        )

    def list_exposure_samples(
        self, worker_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/workers/{worker_id}/exposure-samples", params, headers
        )

    def get_exposure_index(self, worker_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/workers/{worker_id}/exposure-index", None, headers
        )

    def grant_medical_clearance(
        self, worker_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/workers/{worker_id}/medical-clearance", payload, headers
        )

    # --- Cell designs ------------------------------------------------------
    def create_cell_design(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/cell-designs", payload, headers)

    def list_cell_designs(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/cell-designs", params, headers)

    def get_cell_design(self, design_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/cell-designs/{design_id}", None, headers)

    def update_cell_design(
        self, design_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("PATCH", f"/cell-designs/{design_id}", payload, headers)

    def review_cell_design(
        self, design_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/cell-designs/{design_id}/review-actions", payload, headers
        )

    # --- Formation bays ----------------------------------------------------
    def create_formation_bay(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/formation-bays", payload, headers)

    def list_formation_bays(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/formation-bays", params, headers)

    def get_formation_bay(self, bay_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/formation-bays/{bay_id}", None, headers)

    def update_formation_bay(
        self, bay_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("PATCH", f"/formation-bays/{bay_id}", payload, headers)

    # --- Test chambers -----------------------------------------------------
    def create_test_chamber(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/test-chambers", payload, headers)

    def list_test_chambers(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/test-chambers", params, headers)

    def get_test_chamber(self, chamber_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/test-chambers/{chamber_id}", None, headers)

    def update_test_chamber(
        self, chamber_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("PATCH", f"/test-chambers/{chamber_id}", payload, headers)

    # --- Production lots ---------------------------------------------------
    def create_production_lot(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/production-lots", payload, headers)

    def list_production_lots(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/production-lots", params, headers)

    def get_production_lot(self, lot_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/production-lots/{lot_id}", None, headers)

    def advance_lot(
        self, lot_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/production-lots/{lot_id}/advance", payload, headers
        )

    def draw_sampling_plan(
        self, lot_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/production-lots/{lot_id}/sampling-plans", payload, headers
        )

    def disposition_lot(
        self, lot_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/production-lots/{lot_id}/disposition", payload, headers
        )

    def env_hold_lot(
        self, lot_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/production-lots/{lot_id}/env-hold", payload, headers
        )

    def get_quality_summary(self, lot_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/production-lots/{lot_id}/quality-summary", None, headers
        )

    # --- Battery assemblies ------------------------------------------------
    def create_battery_assembly(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/battery-assemblies", payload, headers)

    def list_battery_assemblies(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/battery-assemblies", params, headers)

    def get_battery_assembly(self, assembly_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/battery-assemblies/{assembly_id}", None, headers)

    def record_verification(
        self, assembly_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/battery-assemblies/{assembly_id}/verifications", payload, headers
        )

    def rework_assembly(
        self, assembly_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/battery-assemblies/{assembly_id}/rework", payload, headers
        )

    # --- Formation runs ----------------------------------------------------
    def create_formation_run(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/formation-runs", payload, headers)

    def list_formation_runs(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/formation-runs", params, headers)

    def get_formation_run(self, run_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/formation-runs/{run_id}", None, headers)

    def start_formation_run(
        self, run_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/formation-runs/{run_id}/start", payload or {}, headers
        )

    def complete_formation_run(
        self, run_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/formation-runs/{run_id}/complete", payload, headers
        )

    def abort_formation_run(
        self, run_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/formation-runs/{run_id}/abort", payload, headers)

    # --- Capacity tests ----------------------------------------------------
    def create_capacity_test(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/capacity-tests", payload, headers)

    def list_capacity_tests(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/capacity-tests", params, headers)

    def get_capacity_test(self, test_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/capacity-tests/{test_id}", None, headers)

    def record_test_result(
        self, test_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/capacity-tests/{test_id}/record-result", payload, headers
        )

    # --- Chargers ----------------------------------------------------------
    def create_charger(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/chargers", payload, headers)

    def list_chargers(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/chargers", params, headers)

    def get_charger(self, charger_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/chargers/{charger_id}", None, headers)

    def update_charger(
        self, charger_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("PATCH", f"/chargers/{charger_id}", payload, headers)

    # --- Fleet sizing ------------------------------------------------------
    def create_sizing_request(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/fleet-sizing-requests", payload, headers)

    def list_sizing_requests(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/fleet-sizing-requests", params, headers)

    def get_sizing_request(self, request_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/fleet-sizing-requests/{request_id}", None, headers)

    def decide_sizing_request(
        self, request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/fleet-sizing-requests/{request_id}/decision", payload, headers
        )

    # --- Battery units -----------------------------------------------------
    def create_battery_unit(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/battery-units", payload, headers)

    def list_battery_units(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/battery-units", params, headers)

    def get_battery_unit(self, unit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/battery-units/{unit_id}", None, headers)

    def create_maintenance_log(
        self, unit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/battery-units/{unit_id}/maintenance-logs", payload, headers
        )

    def list_maintenance_logs(
        self, unit_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/battery-units/{unit_id}/maintenance-logs", params, headers
        )

    def get_warranty_evaluation(self, unit_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/battery-units/{unit_id}/warranty-evaluation", None, headers
        )

    def open_warranty_claim(
        self, unit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/battery-units/{unit_id}/warranty-claims", payload, headers
        )

    def adjudicate_warranty(
        self, unit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/battery-units/{unit_id}/warranty-adjudication", payload, headers
        )

    def open_core_return(
        self, unit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/battery-units/{unit_id}/core-return", payload, headers
        )

    def transition_core_return(
        self, unit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/battery-units/{unit_id}/core-return/transitions", payload, headers
        )
