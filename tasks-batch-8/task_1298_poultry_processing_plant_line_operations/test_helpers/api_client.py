"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Processing lines ---
    def create_line(self, payload, headers):
        return self._request("POST", "/poultry/lines", payload, headers)

    def get_line(self, line_id, headers):
        return self._request("GET", f"/poultry/lines/{line_id}", headers=headers)

    def list_line_waivers(self, line_id, headers, params=None):
        return self._request("GET", f"/poultry/lines/{line_id}/waivers", headers=headers, params=params)

    def list_line_sanitation_runs(self, line_id, headers, params=None):
        return self._request("GET", f"/poultry/lines/{line_id}/sanitation-runs", headers=headers, params=params)

    def list_line_preop_inspections(self, line_id, headers, params=None):
        return self._request("GET", f"/poultry/lines/{line_id}/pre-op-inspections", headers=headers, params=params)

    def create_waiver(self, line_id, payload, headers):
        return self._request("POST", f"/poultry/lines/{line_id}/waivers", payload, headers)

    # --- Production shifts ---
    def create_shift(self, payload, headers):
        return self._request("POST", "/poultry/shifts", payload, headers)

    def get_shift(self, shift_id, headers):
        return self._request("GET", f"/poultry/shifts/{shift_id}", headers=headers)

    def set_shift_staffing(self, shift_id, payload, headers):
        return self._request("POST", f"/poultry/shifts/{shift_id}/staffing", payload, headers)

    def transition_shift(self, shift_id, payload, headers):
        return self._request("POST", f"/poultry/shifts/{shift_id}/transition", payload, headers)

    def list_shift_sanitation_runs(self, shift_id, headers, params=None):
        return self._request("GET", f"/poultry/shifts/{shift_id}/sanitation-runs", headers=headers, params=params)

    def list_shift_preop_inspections(self, shift_id, headers, params=None):
        return self._request("GET", f"/poultry/shifts/{shift_id}/pre-op-inspections", headers=headers, params=params)

    def list_shift_flock_lots(self, shift_id, headers, params=None):
        return self._request("GET", f"/poultry/shifts/{shift_id}/flock-lots", headers=headers, params=params)

    def list_shift_utility_readings(self, shift_id, headers, params=None):
        return self._request("GET", f"/poultry/shifts/{shift_id}/utility-readings", headers=headers, params=params)

    # --- Sanitation runs ---
    def create_sanitation_run(self, payload, headers):
        return self._request("POST", "/poultry/sanitation-runs", payload, headers)

    def get_sanitation_run(self, run_id, headers):
        return self._request("GET", f"/poultry/sanitation-runs/{run_id}", headers=headers)

    def advance_sanitation_run(self, run_id, payload, headers):
        return self._request("POST", f"/poultry/sanitation-runs/{run_id}/advance", payload, headers)

    # --- Pre-op inspections ---
    def create_preop_inspection(self, payload, headers):
        return self._request("POST", "/poultry/pre-op-inspections", payload, headers)

    def get_preop_inspection(self, inspection_id, headers):
        return self._request("GET", f"/poultry/pre-op-inspections/{inspection_id}", headers=headers)

    def advance_preop_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/poultry/pre-op-inspections/{inspection_id}/advance", payload, headers)

    # --- Line-speed waivers ---
    def get_waiver(self, waiver_id, headers):
        return self._request("GET", f"/poultry/waivers/{waiver_id}", headers=headers)

    def advance_waiver(self, waiver_id, payload, headers):
        return self._request("POST", f"/poultry/waivers/{waiver_id}/advance", payload, headers)

    # --- Flock lots ---
    def create_flock_lot(self, payload, headers):
        return self._request("POST", "/poultry/flock-lots", payload, headers)

    def get_flock_lot(self, lot_id, headers):
        return self._request("GET", f"/poultry/flock-lots/{lot_id}", headers=headers)

    def receive_flock_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/poultry/flock-lots/{lot_id}/receive", payload, headers)

    def advance_flock_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/poultry/flock-lots/{lot_id}/advance", payload, headers)

    # --- Line runs ---
    def create_line_run(self, payload, headers):
        return self._request("POST", "/poultry/line-runs", payload, headers)

    def list_line_runs(self, headers, params=None):
        return self._request("GET", "/poultry/line-runs", headers=headers, params=params)

    def get_line_run(self, run_id, headers):
        return self._request("GET", f"/poultry/line-runs/{run_id}", headers=headers)

    def set_line_run_speed(self, run_id, payload, headers):
        return self._request("POST", f"/poultry/line-runs/{run_id}/set-speed", payload, headers)

    def advance_line_run(self, run_id, payload, headers):
        return self._request("POST", f"/poultry/line-runs/{run_id}/advance", payload, headers)

    def list_run_condemnation_records(self, run_id, headers, params=None):
        return self._request("GET", f"/poultry/line-runs/{run_id}/condemnation-records", headers=headers, params=params)

    # --- Condemnation records ---
    def create_condemnation_record(self, payload, headers):
        return self._request("POST", "/poultry/condemnation-records", payload, headers)

    def get_condemnation_record(self, record_id, headers):
        return self._request("GET", f"/poultry/condemnation-records/{record_id}", headers=headers)

    def advance_condemnation_record(self, record_id, payload, headers):
        return self._request("POST", f"/poultry/condemnation-records/{record_id}/advance", payload, headers)

    # --- Utility readings ---
    def create_utility_reading(self, payload, headers):
        return self._request("POST", "/poultry/utility-readings", payload, headers)

    # --- Product orders ---
    def create_order(self, payload, headers):
        return self._request("POST", "/poultry/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/poultry/orders/{order_id}", headers=headers)

    def amend_order(self, order_id, payload, headers):
        return self._request("PUT", f"/poultry/orders/{order_id}", payload, headers)

    def cancel_order(self, order_id, payload, headers):
        return self._request("POST", f"/poultry/orders/{order_id}/cancel", payload, headers)

    # --- Deboning batches ---
    def create_deboning_batch(self, payload, headers):
        return self._request("POST", "/poultry/deboning-batches", payload, headers)

    def list_deboning_batches(self, headers, params=None):
        return self._request("GET", "/poultry/deboning-batches", headers=headers, params=params)

    def get_deboning_batch(self, batch_id, headers):
        return self._request("GET", f"/poultry/deboning-batches/{batch_id}", headers=headers)

    def advance_deboning_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/poultry/deboning-batches/{batch_id}/advance", payload, headers)

    # --- Finished lots ---
    def list_finished_lots(self, headers, params=None):
        return self._request("GET", "/poultry/finished-lots", headers=headers, params=params)

    def get_finished_lot(self, lot_id, headers):
        return self._request("GET", f"/poultry/finished-lots/{lot_id}", headers=headers)

    def trace_lock_finished_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/poultry/finished-lots/{lot_id}/trace-lock", payload, headers)

    def advance_finished_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/poultry/finished-lots/{lot_id}/advance", payload, headers)

    # --- Chill chain ---
    def create_chill_chain_log(self, payload, headers):
        return self._request("POST", "/poultry/chill-chain-logs", payload, headers)

    def list_finished_lot_chill_chain_logs(self, lot_id, headers, params=None):
        return self._request("GET", f"/poultry/finished-lots/{lot_id}/chill-chain-logs", headers=headers, params=params)

    # --- Logical clock (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
