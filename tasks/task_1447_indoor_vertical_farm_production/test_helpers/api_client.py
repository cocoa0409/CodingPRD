"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Logical farm clock (PRD §2.4) ──────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/farm/_clock/set_current_utc", payload, headers)

    # ── Crops ──────────────────────────────────────────────────────────────
    def create_crop(self, payload, headers):
        return self._request("POST", "/farm/crops", payload, headers)

    def list_crops(self, headers, params=None):
        return self._request("GET", "/farm/crops", headers=headers, params=params)

    def get_crop(self, crop_id, headers):
        return self._request("GET", f"/farm/crops/{crop_id}", headers=headers)

    def retire_crop(self, crop_id, headers):
        return self._request("POST", f"/farm/crops/{crop_id}/retire", headers=headers)

    # ── Grow recipes ───────────────────────────────────────────────────────
    def create_recipe(self, payload, headers):
        return self._request("POST", "/farm/recipes", payload, headers)

    def list_recipes(self, headers, params=None):
        return self._request("GET", "/farm/recipes", headers=headers, params=params)

    def get_recipe(self, recipe_id, headers):
        return self._request("GET", f"/farm/recipes/{recipe_id}", headers=headers)

    def activate_recipe(self, recipe_id, payload, headers):
        return self._request("POST", f"/farm/recipes/{recipe_id}/activate", payload, headers)

    def retire_recipe(self, recipe_id, headers):
        return self._request("POST", f"/farm/recipes/{recipe_id}/retire", headers=headers)

    # ── Water loops ────────────────────────────────────────────────────────
    def create_water_loop(self, payload, headers):
        return self._request("POST", "/farm/water-loops", payload, headers)

    def list_water_loops(self, headers, params=None):
        return self._request("GET", "/farm/water-loops", headers=headers, params=params)

    def get_water_loop(self, loop_id, headers):
        return self._request("GET", f"/farm/water-loops/{loop_id}", headers=headers)

    def list_loop_sanitation_cycles(self, loop_id, headers, params=None):
        return self._request("GET", f"/farm/water-loops/{loop_id}/sanitation-cycles", headers=headers, params=params)

    # ── Racks ──────────────────────────────────────────────────────────────
    def create_rack(self, payload, headers):
        return self._request("POST", "/farm/racks", payload, headers)

    def list_racks(self, headers, params=None):
        return self._request("GET", "/farm/racks", headers=headers, params=params)

    def get_rack(self, rack_id, headers):
        return self._request("GET", f"/farm/racks/{rack_id}", headers=headers)

    def list_rack_towers(self, rack_id, headers, params=None):
        return self._request("GET", f"/farm/racks/{rack_id}/towers", headers=headers, params=params)

    def set_rack_out_of_service(self, rack_id, headers):
        return self._request("POST", f"/farm/racks/{rack_id}/set-out-of-service", headers=headers)

    def return_rack_to_service(self, rack_id, headers):
        return self._request("POST", f"/farm/racks/{rack_id}/return-to-service", headers=headers)

    # ── Towers ─────────────────────────────────────────────────────────────
    def list_towers(self, headers, params=None):
        return self._request("GET", "/farm/towers", headers=headers, params=params)

    def get_tower(self, tower_id, headers):
        return self._request("GET", f"/farm/towers/{tower_id}", headers=headers)

    def list_tower_allocations(self, tower_id, headers, params=None):
        return self._request("GET", f"/farm/towers/{tower_id}/allocations", headers=headers, params=params)

    # ── Grow batches ───────────────────────────────────────────────────────
    def create_batch(self, payload, headers):
        return self._request("POST", "/farm/batches", payload, headers)

    def list_batches(self, headers, params=None):
        return self._request("GET", "/farm/batches", headers=headers, params=params)

    def get_batch(self, batch_id, headers):
        return self._request("GET", f"/farm/batches/{batch_id}", headers=headers)

    def list_batch_allocations(self, batch_id, headers, params=None):
        return self._request("GET", f"/farm/batches/{batch_id}/allocations", headers=headers, params=params)

    def list_batch_failure_reports(self, batch_id, headers, params=None):
        return self._request("GET", f"/farm/batches/{batch_id}/failure-reports", headers=headers, params=params)

    def list_batch_shipment_lines(self, batch_id, headers, params=None):
        return self._request("GET", f"/farm/batches/{batch_id}/shipment-lines", headers=headers, params=params)

    def get_batch_cost_summary(self, batch_id, headers):
        return self._request("GET", f"/farm/batches/{batch_id}/cost-summary", headers=headers)

    def seed_batch(self, batch_id, headers):
        return self._request("POST", f"/farm/batches/{batch_id}/seed", headers=headers)

    def germination_check_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/farm/batches/{batch_id}/germination-check", payload, headers)

    def report_stress_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/farm/batches/{batch_id}/report-stress", payload, headers)

    def recover_batch(self, batch_id, headers):
        return self._request("POST", f"/farm/batches/{batch_id}/recover", headers=headers)

    def mark_harvest_ready_batch(self, batch_id, headers):
        return self._request("POST", f"/farm/batches/{batch_id}/mark-harvest-ready", headers=headers)

    def harvest_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/farm/batches/{batch_id}/harvest", payload, headers)

    def fail_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/farm/batches/{batch_id}/fail", payload, headers)

    def cull_batch(self, batch_id, headers):
        return self._request("POST", f"/farm/batches/{batch_id}/cull", headers=headers)

    def safety_release_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/farm/batches/{batch_id}/safety-release", payload, headers)

    def pack_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/farm/batches/{batch_id}/pack", payload, headers)

    # ── Sanitation cycles ──────────────────────────────────────────────────
    def create_sanitation_cycle(self, payload, headers):
        return self._request("POST", "/farm/sanitation-cycles", payload, headers)

    def list_sanitation_cycles(self, headers, params=None):
        return self._request("GET", "/farm/sanitation-cycles", headers=headers, params=params)

    def get_sanitation_cycle(self, cycle_id, headers):
        return self._request("GET", f"/farm/sanitation-cycles/{cycle_id}", headers=headers)

    def start_sanitation_cycle(self, cycle_id, headers):
        return self._request("POST", f"/farm/sanitation-cycles/{cycle_id}/start", headers=headers)

    def record_sanitation_result(self, cycle_id, payload, headers):
        return self._request("POST", f"/farm/sanitation-cycles/{cycle_id}/record-result", payload, headers)

    def cancel_sanitation_cycle(self, cycle_id, headers):
        return self._request("POST", f"/farm/sanitation-cycles/{cycle_id}/cancel", headers=headers)

    # ── Retail contracts ───────────────────────────────────────────────────
    def create_contract(self, payload, headers):
        return self._request("POST", "/farm/contracts", payload, headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/farm/contracts", headers=headers, params=params)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/farm/contracts/{contract_id}", headers=headers)

    def list_contract_shipments(self, contract_id, headers, params=None):
        return self._request("GET", f"/farm/contracts/{contract_id}/shipments", headers=headers, params=params)

    def get_contract_week_summary(self, contract_id, headers, params=None):
        return self._request("GET", f"/farm/contracts/{contract_id}/week-summary", headers=headers, params=params)

    def suspend_contract(self, contract_id, headers):
        return self._request("POST", f"/farm/contracts/{contract_id}/suspend", headers=headers)

    def reinstate_contract(self, contract_id, headers):
        return self._request("POST", f"/farm/contracts/{contract_id}/reinstate", headers=headers)

    def terminate_contract(self, contract_id, headers):
        return self._request("POST", f"/farm/contracts/{contract_id}/terminate", headers=headers)

    def settle_contract_week(self, contract_id, payload, headers):
        return self._request("POST", f"/farm/contracts/{contract_id}/settle-week", payload, headers)

    # ── Shipments ──────────────────────────────────────────────────────────
    def create_shipment(self, payload, headers):
        return self._request("POST", "/farm/shipments", payload, headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/farm/shipments", headers=headers, params=params)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/farm/shipments/{shipment_id}", headers=headers)

    def list_shipment_lines(self, shipment_id, headers, params=None):
        return self._request("GET", f"/farm/shipments/{shipment_id}/lines", headers=headers, params=params)

    def confirm_pack_shipment(self, shipment_id, payload, headers):
        return self._request("POST", f"/farm/shipments/{shipment_id}/confirm-pack", payload, headers)

    def ship_shipment(self, shipment_id, headers):
        return self._request("POST", f"/farm/shipments/{shipment_id}/ship", headers=headers)

    def cancel_shipment(self, shipment_id, headers):
        return self._request("POST", f"/farm/shipments/{shipment_id}/cancel", headers=headers)

    # ── Workers ────────────────────────────────────────────────────────────
    def create_worker(self, payload, headers):
        return self._request("POST", "/farm/workers", payload, headers)

    def list_workers(self, headers, params=None):
        return self._request("GET", "/farm/workers", headers=headers, params=params)

    def get_worker(self, worker_id, headers):
        return self._request("GET", f"/farm/workers/{worker_id}", headers=headers)

    def list_worker_assignments(self, worker_id, headers, params=None):
        return self._request("GET", f"/farm/workers/{worker_id}/assignments", headers=headers, params=params)

    # ── Labor shifts and assignments ───────────────────────────────────────
    def create_labor_shift(self, payload, headers):
        return self._request("POST", "/farm/labor-shifts", payload, headers)

    def list_labor_shifts(self, headers, params=None):
        return self._request("GET", "/farm/labor-shifts", headers=headers, params=params)

    def get_labor_shift(self, shift_id, headers):
        return self._request("GET", f"/farm/labor-shifts/{shift_id}", headers=headers)

    def list_shift_assignments(self, shift_id, headers, params=None):
        return self._request("GET", f"/farm/labor-shifts/{shift_id}/assignments", headers=headers, params=params)

    def publish_labor_shift(self, shift_id, headers):
        return self._request("POST", f"/farm/labor-shifts/{shift_id}/publish", headers=headers)

    def create_shift_assignment(self, shift_id, payload, headers):
        return self._request("POST", f"/farm/labor-shifts/{shift_id}/assignments", payload, headers)

    def release_shift_assignment(self, shift_id, assignment_id, headers):
        return self._request("POST", f"/farm/labor-shifts/{shift_id}/assignments/{assignment_id}/release", headers=headers)

    def confirm_shift_assignment(self, shift_id, assignment_id, headers):
        return self._request("POST", f"/farm/labor-shifts/{shift_id}/assignments/{assignment_id}/confirm", headers=headers)

    def complete_labor_shift(self, shift_id, headers):
        return self._request("POST", f"/farm/labor-shifts/{shift_id}/complete", headers=headers)

    def cancel_labor_shift(self, shift_id, headers):
        return self._request("POST", f"/farm/labor-shifts/{shift_id}/cancel", headers=headers)

    # ── Energy meter readings ──────────────────────────────────────────────
    def create_energy_reading(self, payload, headers):
        return self._request("POST", "/farm/energy-readings", payload, headers)

    def list_energy_readings(self, headers, params=None):
        return self._request("GET", "/farm/energy-readings", headers=headers, params=params)

    def get_energy_reading(self, reading_id, headers):
        return self._request("GET", f"/farm/energy-readings/{reading_id}", headers=headers)

    # ── Failure reports ────────────────────────────────────────────────────
    def list_failure_reports(self, headers, params=None):
        return self._request("GET", "/farm/failure-reports", headers=headers, params=params)

    def get_failure_report(self, report_id, headers):
        return self._request("GET", f"/farm/failure-reports/{report_id}", headers=headers)

    def triage_failure_report(self, report_id, payload, headers):
        return self._request("POST", f"/farm/failure-reports/{report_id}/triage", payload, headers)

    def request_replant(self, report_id, headers):
        return self._request("POST", f"/farm/failure-reports/{report_id}/request-replant", headers=headers)

    def close_failure_report(self, report_id, headers):
        return self._request("POST", f"/farm/failure-reports/{report_id}/close", headers=headers)

    def list_failure_replant_requests(self, report_id, headers, params=None):
        return self._request("GET", f"/farm/failure-reports/{report_id}/replant-requests", headers=headers, params=params)

    # ── Replant requests ───────────────────────────────────────────────────
    def list_replant_requests(self, headers, params=None):
        return self._request("GET", "/farm/replant-requests", headers=headers, params=params)

    def get_replant_request(self, request_id, headers):
        return self._request("GET", f"/farm/replant-requests/{request_id}", headers=headers)

    def approve_replant_request(self, request_id, headers):
        return self._request("POST", f"/farm/replant-requests/{request_id}/approve", headers=headers)

    def drop_replant_request(self, request_id, headers):
        return self._request("POST", f"/farm/replant-requests/{request_id}/drop", headers=headers)

    def list_replant_batches(self, request_id, headers, params=None):
        return self._request("GET", f"/farm/replant-requests/{request_id}/batches", headers=headers, params=params)


api_client = ApiClient()
