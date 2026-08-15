"""API client: one method per endpoint defined in the PRD (§4 routing table).

All paths are under the /race-timing mount point. The base `_request()` method
is inherited from the framework's GenericApiClient.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint, PRD §2.4)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/race-timing/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Races
    # ------------------------------------------------------------------
    def create_race(self, payload, headers):
        return self._request("POST", "/race-timing/races", payload, headers)

    def get_race(self, race_id, headers):
        return self._request("GET", f"/race-timing/races/{race_id}", headers=headers)

    def list_race_waves(self, race_id, headers, params=None):
        return self._request("GET", f"/race-timing/races/{race_id}/waves",
                             headers=headers, params=params)

    def list_race_timing_points(self, race_id, headers, params=None):
        return self._request("GET", f"/race-timing/races/{race_id}/timing-points",
                             headers=headers, params=params)

    def list_race_certifications(self, race_id, headers, params=None):
        return self._request("GET", f"/race-timing/races/{race_id}/certifications",
                             headers=headers, params=params)

    def list_race_awards(self, race_id, headers, params=None):
        return self._request("GET", f"/race-timing/races/{race_id}/awards",
                             headers=headers, params=params)

    def open_registration(self, race_id, headers):
        return self._request("POST", f"/race-timing/races/{race_id}/open-registration",
                             {}, headers)

    def lock_timing(self, race_id, headers):
        return self._request("POST", f"/race-timing/races/{race_id}/lock-timing",
                             {}, headers)

    def publish_results(self, race_id, expected_race_version, headers):
        return self._request("POST", f"/race-timing/races/{race_id}/publish-results",
                             {"expected_race_version": expected_race_version}, headers)

    def finalize_results(self, race_id, headers):
        return self._request("POST", f"/race-timing/races/{race_id}/finalize-results",
                             {}, headers)

    def certify_race(self, race_id, headers):
        return self._request("POST", f"/race-timing/races/{race_id}/certify",
                             {}, headers)

    def get_live_board(self, race_id, headers, params=None):
        return self._request("GET", f"/race-timing/races/{race_id}/live-board",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Waves
    # ------------------------------------------------------------------
    def create_wave(self, payload, headers):
        return self._request("POST", "/race-timing/waves", payload, headers)

    def start_wave(self, wave_id, headers):
        return self._request("POST", f"/race-timing/waves/{wave_id}/start", {}, headers)

    # ------------------------------------------------------------------
    # Timing points
    # ------------------------------------------------------------------
    def create_timing_point(self, payload, headers):
        return self._request("POST", "/race-timing/timing-points", payload, headers)

    def deploy_timing_point(self, point_id, headers):
        return self._request("POST", f"/race-timing/timing-points/{point_id}/deploy",
                             {}, headers)

    def delete_timing_point(self, point_id, headers):
        return self._request("DELETE", f"/race-timing/timing-points/{point_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Registrations
    # ------------------------------------------------------------------
    def create_registration(self, payload, headers):
        return self._request("POST", "/race-timing/registrations", payload, headers)

    def get_registration(self, reg_id, headers):
        return self._request("GET", f"/race-timing/registrations/{reg_id}",
                             headers=headers)

    def list_registrations(self, headers, params=None):
        return self._request("GET", "/race-timing/registrations",
                             headers=headers, params=params)

    def pay_registration(self, reg_id, headers):
        return self._request("POST", f"/race-timing/registrations/{reg_id}/pay",
                             {}, headers)

    def confirm_registration(self, reg_id, headers):
        return self._request("POST", f"/race-timing/registrations/{reg_id}/confirm",
                             {}, headers)

    def assign_chip(self, reg_id, chip_id, headers):
        return self._request("POST", f"/race-timing/registrations/{reg_id}/assign-chip",
                             {"chip_id": chip_id}, headers)

    def withdraw_registration(self, reg_id, headers):
        return self._request("POST", f"/race-timing/registrations/{reg_id}/withdraw",
                             {}, headers)

    def list_registration_awards(self, reg_id, headers, params=None):
        return self._request("GET", f"/race-timing/registrations/{reg_id}/awards",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Chips
    # ------------------------------------------------------------------
    def create_chip(self, payload, headers):
        return self._request("POST", "/race-timing/chips", payload, headers)

    def get_chip(self, chip_id, headers):
        return self._request("GET", f"/race-timing/chips/{chip_id}", headers=headers)

    def list_chips(self, headers, params=None):
        return self._request("GET", "/race-timing/chips", headers=headers, params=params)

    def deassign_chip(self, chip_id, disposition, headers):
        return self._request("POST", f"/race-timing/chips/{chip_id}/deassign",
                             {"disposition": disposition}, headers)

    # ------------------------------------------------------------------
    # Timing reads (append-only log)
    # ------------------------------------------------------------------
    def create_timing_read(self, payload, headers):
        return self._request("POST", "/race-timing/timing-reads", payload, headers)

    def get_timing_read(self, read_id, headers):
        return self._request("GET", f"/race-timing/timing-reads/{read_id}",
                             headers=headers)

    def list_timing_reads(self, headers, params=None):
        return self._request("GET", "/race-timing/timing-reads",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Results
    # ------------------------------------------------------------------
    def get_result(self, result_id, headers):
        return self._request("GET", f"/race-timing/results/{result_id}", headers=headers)

    def list_results(self, headers, params=None):
        return self._request("GET", "/race-timing/results", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Result flags
    # ------------------------------------------------------------------
    def create_result_flag(self, payload, headers):
        return self._request("POST", "/race-timing/result-flags", payload, headers)

    def get_result_flag(self, flag_id, headers):
        return self._request("GET", f"/race-timing/result-flags/{flag_id}",
                             headers=headers)

    def list_result_flags(self, headers, params=None):
        return self._request("GET", "/race-timing/result-flags",
                             headers=headers, params=params)

    def resolve_result_flag(self, flag_id, outcome, headers):
        return self._request("POST", f"/race-timing/result-flags/{flag_id}/resolve",
                             {"outcome": outcome}, headers)

    # ------------------------------------------------------------------
    # Protests
    # ------------------------------------------------------------------
    def create_protest(self, payload, headers):
        return self._request("POST", "/race-timing/protests", payload, headers)

    def get_protest(self, protest_id, headers):
        return self._request("GET", f"/race-timing/protests/{protest_id}",
                             headers=headers)

    def list_protests(self, headers, params=None):
        return self._request("GET", "/race-timing/protests", headers=headers,
                             params=params)

    def resolve_protest(self, protest_id, outcome, headers):
        return self._request("POST", f"/race-timing/protests/{protest_id}/resolve",
                             {"outcome": outcome}, headers)

    # ------------------------------------------------------------------
    # Corrections
    # ------------------------------------------------------------------
    def create_correction(self, payload, headers):
        return self._request("POST", "/race-timing/corrections", payload, headers)

    def get_correction(self, correction_id, headers):
        return self._request("GET", f"/race-timing/corrections/{correction_id}",
                             headers=headers)

    def list_corrections(self, headers, params=None):
        return self._request("GET", "/race-timing/corrections", headers=headers,
                             params=params)

    def adjudicate_correction(self, correction_id, decision, expected_race_version, headers):
        return self._request(
            "POST", f"/race-timing/corrections/{correction_id}/adjudicate",
            {"decision": decision, "expected_race_version": expected_race_version},
            headers)


api_client = ApiClient()
