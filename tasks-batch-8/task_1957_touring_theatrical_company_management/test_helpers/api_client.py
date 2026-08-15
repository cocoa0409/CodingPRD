"""API client: one method per endpoint defined in the PRD (§4 endpoint table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Tours ---
    def create_tour(self, payload, headers):
        return self._request("POST", "/tours", payload, headers)

    def get_tour(self, tour_id, headers):
        return self._request("GET", f"/tours/{tour_id}", headers=headers)

    def patch_tour(self, tour_id, payload, headers):
        return self._request("PATCH", f"/tours/{tour_id}", payload, headers)

    # --- Venues ---
    def create_venue(self, payload, headers):
        return self._request("POST", "/venues", payload, headers)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/venues/{venue_id}", headers=headers)

    # --- Stops ---
    def create_stop(self, tour_id, payload, headers):
        return self._request("POST", f"/tours/{tour_id}/stops", payload, headers)

    def list_stops(self, headers, params=None):
        return self._request("GET", "/stops", headers=headers, params=params)

    def get_stop(self, stop_id, headers):
        return self._request("GET", f"/stops/{stop_id}", headers=headers)

    def put_stop(self, stop_id, payload, headers):
        return self._request("PUT", f"/stops/{stop_id}", payload, headers)

    def amend_stop(self, stop_id, payload, headers):
        return self._request("POST", f"/stops/{stop_id}/amend", payload, headers)

    # --- Tech rider checks ---
    def create_tech_check(self, stop_id, payload, headers):
        return self._request("POST", f"/stops/{stop_id}/tech-checks", payload, headers)

    def list_tech_checks(self, stop_id, headers):
        return self._request("GET", f"/stops/{stop_id}/tech-checks", headers=headers)

    def put_tech_check(self, check_id, payload, headers):
        return self._request("PUT", f"/tech-checks/{check_id}", payload, headers)

    # --- Performances ---
    def create_performance(self, stop_id, payload, headers):
        return self._request("POST", f"/stops/{stop_id}/performances", payload, headers)

    def list_performances(self, stop_id, headers, params=None):
        return self._request("GET", f"/stops/{stop_id}/performances", headers=headers, params=params)

    def put_performance(self, perf_id, payload, headers):
        return self._request("PUT", f"/performances/{perf_id}", payload, headers)

    # --- Settlement ---
    def get_stop_settlement(self, stop_id, headers):
        return self._request("GET", f"/stops/{stop_id}/settlement", headers=headers)

    def put_settlement(self, settlement_id, payload, headers):
        return self._request("PUT", f"/settlements/{settlement_id}", payload, headers)

    # --- Cast members ---
    def create_cast_member(self, tour_id, payload, headers):
        return self._request("POST", f"/tours/{tour_id}/cast", payload, headers)

    def list_cast(self, tour_id, headers, params=None):
        return self._request("GET", f"/tours/{tour_id}/cast", headers=headers, params=params)

    def get_cast_member(self, cast_id, headers):
        return self._request("GET", f"/cast/{cast_id}", headers=headers)

    def put_cast(self, cast_id, payload, headers):
        return self._request("PUT", f"/cast/{cast_id}", payload, headers)

    # --- Character tracks ---
    def create_track(self, tour_id, payload, headers):
        return self._request("POST", f"/tours/{tour_id}/tracks", payload, headers)

    def list_tour_tracks(self, tour_id, headers):
        return self._request("GET", f"/tours/{tour_id}/tracks", headers=headers)

    def list_tracks(self, headers, params=None):
        return self._request("GET", "/tracks", headers=headers, params=params)

    def get_track(self, track_id, headers):
        return self._request("GET", f"/tracks/{track_id}", headers=headers)

    def patch_track(self, track_id, payload, headers):
        return self._request("PATCH", f"/tracks/{track_id}", payload, headers)

    # --- Coverage assignments ---
    def create_coverage(self, track_id, payload, headers):
        return self._request("POST", f"/tracks/{track_id}/coverages", payload, headers)

    def list_track_coverages(self, track_id, headers, params=None):
        return self._request("GET", f"/tracks/{track_id}/coverages", headers=headers, params=params)

    def list_cast_coverages(self, cast_id, headers, params=None):
        return self._request("GET", f"/cast/{cast_id}/coverages", headers=headers, params=params)

    def put_coverage(self, coverage_id, payload, headers):
        return self._request("PUT", f"/coverages/{coverage_id}", payload, headers)

    # --- Injury events ---
    def create_injury(self, cast_id, payload, headers):
        return self._request("POST", f"/cast/{cast_id}/injuries", payload, headers)

    def list_injuries(self, cast_id, headers):
        return self._request("GET", f"/cast/{cast_id}/injuries", headers=headers)

    def put_injury(self, injury_id, payload, headers):
        return self._request("PUT", f"/injuries/{injury_id}", payload, headers)

    # --- Per-diem statements ---
    def create_per_diem(self, stop_id, payload, headers):
        return self._request("POST", f"/stops/{stop_id}/per-diems", payload, headers)

    def list_stop_per_diems(self, stop_id, headers):
        return self._request("GET", f"/stops/{stop_id}/per-diems", headers=headers)

    def list_cast_per_diems(self, cast_id, headers):
        return self._request("GET", f"/cast/{cast_id}/per-diems", headers=headers)

    def put_per_diem(self, pd_id, payload, headers):
        return self._request("PUT", f"/per-diems/{pd_id}", payload, headers)

    # --- Crew calls ---
    def create_crew_call(self, stop_id, payload, headers):
        return self._request("POST", f"/stops/{stop_id}/crew-calls", payload, headers)

    def list_crew_calls(self, stop_id, headers):
        return self._request("GET", f"/stops/{stop_id}/crew-calls", headers=headers)

    def put_crew_call(self, cc_id, payload, headers):
        return self._request("PUT", f"/crew-calls/{cc_id}", payload, headers)

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
