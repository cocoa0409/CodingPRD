"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- test-driving clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/sugarhouse/_clock/set_current_utc", payload, headers)

    # --- Season ---
    def create_season(self, payload, headers):
        return self._request("POST", "/sugarhouse/seasons", payload, headers)

    def get_season(self, season_id, headers):
        return self._request("GET", f"/sugarhouse/seasons/{season_id}", headers=headers)

    def open_season(self, season_id, headers):
        return self._request("POST", f"/sugarhouse/seasons/{season_id}/open", headers=headers)

    def suspend_season(self, season_id, headers):
        return self._request("POST", f"/sugarhouse/seasons/{season_id}/suspend", headers=headers)

    def resume_season(self, season_id, headers):
        return self._request("POST", f"/sugarhouse/seasons/{season_id}/resume", headers=headers)

    def close_season(self, season_id, headers):
        return self._request("POST", f"/sugarhouse/seasons/{season_id}/close", headers=headers)

    def reconcile_season(self, season_id, headers):
        return self._request("POST", f"/sugarhouse/seasons/{season_id}/reconcile", headers=headers)

    def run_sweep(self, season_id, headers):
        return self._request("POST", f"/sugarhouse/seasons/{season_id}/run-sweep", headers=headers)

    # --- Sugarbush ---
    def create_sugarbush(self, payload, headers):
        return self._request("POST", "/sugarhouse/sugarbushes", payload, headers)

    def get_sugarbush(self, bush_id, headers):
        return self._request("GET", f"/sugarhouse/sugarbushes/{bush_id}", headers=headers)

    def list_sugarbushes(self, headers, params=None):
        return self._request("GET", "/sugarhouse/sugarbushes", headers=headers, params=params)

    def begin_tapping(self, bush_id, headers):
        return self._request("POST", f"/sugarhouse/sugarbushes/{bush_id}/begin-tapping", headers=headers)

    def go_live(self, bush_id, headers):
        return self._request("POST", f"/sugarhouse/sugarbushes/{bush_id}/go-live", headers=headers)

    def shutdown_sugarbush(self, bush_id, headers):
        return self._request("POST", f"/sugarhouse/sugarbushes/{bush_id}/shutdown", headers=headers)

    # --- Lease ---
    def create_lease(self, payload, headers):
        return self._request("POST", "/sugarhouse/leases", payload, headers)

    def get_lease(self, lease_id, headers):
        return self._request("GET", f"/sugarhouse/leases/{lease_id}", headers=headers)

    def list_leases(self, headers, params=None):
        return self._request("GET", "/sugarhouse/leases", headers=headers, params=params)

    def patch_lease(self, lease_id, payload, headers):
        return self._request("PATCH", f"/sugarhouse/leases/{lease_id}", payload, headers)

    def submit_lease_audit(self, lease_id, headers):
        return self._request("POST", f"/sugarhouse/leases/{lease_id}/submit-audit", headers=headers)

    def activate_lease(self, lease_id, headers):
        return self._request("POST", f"/sugarhouse/leases/{lease_id}/activate", headers=headers)

    def terminate_lease(self, lease_id, headers):
        return self._request("POST", f"/sugarhouse/leases/{lease_id}/terminate", headers=headers)

    # --- TapLine ---
    def create_tap_line(self, payload, headers):
        return self._request("POST", "/sugarhouse/tap-lines", payload, headers)

    def get_tap_line(self, line_id, headers):
        return self._request("GET", f"/sugarhouse/tap-lines/{line_id}", headers=headers)

    def list_tap_lines(self, headers, params=None):
        return self._request("GET", "/sugarhouse/tap-lines", headers=headers, params=params)

    def activate_tap_line(self, line_id, headers):
        return self._request("POST", f"/sugarhouse/tap-lines/{line_id}/activate", headers=headers)

    def repair_tap_line(self, line_id, headers):
        return self._request("POST", f"/sugarhouse/tap-lines/{line_id}/repair", headers=headers)

    def pull_tap_line(self, line_id, headers):
        return self._request("POST", f"/sugarhouse/tap-lines/{line_id}/pull", headers=headers)

    # --- VacuumReading (sub-resource of TapLine) ---
    def create_vacuum_reading(self, line_id, payload, headers):
        return self._request("POST", f"/sugarhouse/tap-lines/{line_id}/vacuum-readings", payload, headers)

    def list_vacuum_readings(self, line_id, headers, params=None):
        return self._request("GET", f"/sugarhouse/tap-lines/{line_id}/vacuum-readings", headers=headers, params=params)

    # --- WeatherWindow ---
    def create_weather_window(self, payload, headers):
        return self._request("POST", "/sugarhouse/weather-windows", payload, headers)

    def get_weather_window(self, window_id, headers):
        return self._request("GET", f"/sugarhouse/weather-windows/{window_id}", headers=headers)

    def list_weather_windows(self, headers, params=None):
        return self._request("GET", "/sugarhouse/weather-windows", headers=headers, params=params)

    def open_weather_window(self, window_id, headers):
        return self._request("POST", f"/sugarhouse/weather-windows/{window_id}/open", headers=headers)

    # --- CrewMember ---
    def create_crew_member(self, payload, headers):
        return self._request("POST", "/sugarhouse/crew-members", payload, headers)

    def get_crew_member(self, crew_id, headers):
        return self._request("GET", f"/sugarhouse/crew-members/{crew_id}", headers=headers)

    def list_crew_members(self, headers, params=None):
        return self._request("GET", "/sugarhouse/crew-members", headers=headers, params=params)

    def activate_crew_member(self, crew_id, headers):
        return self._request("POST", f"/sugarhouse/crew-members/{crew_id}/activate", headers=headers)

    def release_crew_member(self, crew_id, headers):
        return self._request("POST", f"/sugarhouse/crew-members/{crew_id}/release", headers=headers)

    # --- SapRun ---
    def create_sap_run(self, payload, headers):
        return self._request("POST", "/sugarhouse/sap-runs", payload, headers)

    def get_sap_run(self, run_id, headers):
        return self._request("GET", f"/sugarhouse/sap-runs/{run_id}", headers=headers)

    def list_sap_runs(self, headers, params=None):
        return self._request("GET", "/sugarhouse/sap-runs", headers=headers, params=params)

    def confirm_sap_run(self, run_id, headers):
        return self._request("POST", f"/sugarhouse/sap-runs/{run_id}/confirm", headers=headers)

    def void_sap_run(self, run_id, headers):
        return self._request("POST", f"/sugarhouse/sap-runs/{run_id}/void", headers=headers)

    # --- EvaporatorBatch ---
    def create_batch(self, payload, headers):
        return self._request("POST", "/sugarhouse/batches", payload, headers)

    def get_batch(self, batch_id, headers):
        return self._request("GET", f"/sugarhouse/batches/{batch_id}", headers=headers)

    def list_batches(self, headers, params=None):
        return self._request("GET", "/sugarhouse/batches", headers=headers, params=params)

    def create_batch_intake(self, batch_id, payload, headers):
        return self._request("POST", f"/sugarhouse/batches/{batch_id}/intakes", payload, headers)

    def auto_fill_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/sugarhouse/batches/{batch_id}/auto-fill", payload, headers)

    def list_batch_intakes(self, batch_id, headers, params=None):
        return self._request("GET", f"/sugarhouse/batches/{batch_id}/intakes", headers=headers, params=params)

    def list_sap_run_intakes(self, run_id, headers, params=None):
        return self._request("GET", f"/sugarhouse/sap-runs/{run_id}/intakes", headers=headers, params=params)

    def start_boil(self, batch_id, headers):
        return self._request("POST", f"/sugarhouse/batches/{batch_id}/start-boil", headers=headers)

    def finish_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/sugarhouse/batches/{batch_id}/finish", payload, headers)

    def cancel_batch(self, batch_id, headers):
        return self._request("POST", f"/sugarhouse/batches/{batch_id}/cancel", headers=headers)

    # --- SyrupLot ---
    def get_syrup_lot(self, lot_id, headers):
        return self._request("GET", f"/sugarhouse/syrup-lots/{lot_id}", headers=headers)

    def list_syrup_lots(self, headers, params=None):
        return self._request("GET", "/sugarhouse/syrup-lots", headers=headers, params=params)

    def grade_syrup_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/sugarhouse/syrup-lots/{lot_id}/grade", payload, headers)

    def hold_syrup_lot(self, lot_id, headers):
        return self._request("POST", f"/sugarhouse/syrup-lots/{lot_id}/hold", headers=headers)

    def condemn_syrup_lot(self, lot_id, headers):
        return self._request("POST", f"/sugarhouse/syrup-lots/{lot_id}/condemn", headers=headers)

    # --- FlavorEvaluation (sub-resource of SyrupLot) ---
    def create_flavor_evaluation(self, lot_id, payload, headers):
        return self._request("POST", f"/sugarhouse/syrup-lots/{lot_id}/evaluations", payload, headers)

    def list_flavor_evaluations(self, lot_id, headers, params=None):
        return self._request("GET", f"/sugarhouse/syrup-lots/{lot_id}/evaluations", headers=headers, params=params)

    def list_crew_member_evaluations(self, crew_id, headers, params=None):
        return self._request("GET", f"/sugarhouse/crew-members/{crew_id}/evaluations", headers=headers, params=params)

    # --- PackagingRun ---
    def create_packaging_run(self, payload, headers):
        return self._request("POST", "/sugarhouse/packaging-runs", payload, headers)

    def get_packaging_run(self, run_id, headers):
        return self._request("GET", f"/sugarhouse/packaging-runs/{run_id}", headers=headers)

    def list_packaging_runs(self, headers, params=None):
        return self._request("GET", "/sugarhouse/packaging-runs", headers=headers, params=params)

    def fill_packaging_run(self, run_id, headers):
        return self._request("POST", f"/sugarhouse/packaging-runs/{run_id}/fill", headers=headers)

    def cancel_packaging_run(self, run_id, headers):
        return self._request("POST", f"/sugarhouse/packaging-runs/{run_id}/cancel", headers=headers)

    # --- CertAudit (sub-resource of Sugarbush) ---
    def create_cert_audit(self, bush_id, payload, headers):
        return self._request("POST", f"/sugarhouse/sugarbushes/{bush_id}/cert-audits", payload, headers)

    def list_cert_audits(self, bush_id, headers, params=None):
        return self._request("GET", f"/sugarhouse/sugarbushes/{bush_id}/cert-audits", headers=headers, params=params)

    def record_cert_audit_result(self, audit_id, payload, headers):
        return self._request("POST", f"/sugarhouse/cert-audits/{audit_id}/record-result", payload, headers)


api_client = ApiClient()
