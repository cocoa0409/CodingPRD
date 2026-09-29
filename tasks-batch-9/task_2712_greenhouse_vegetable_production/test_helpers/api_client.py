"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------- zones ----------------
    def create_zone(self, payload, headers):
        return self._request("POST", "/zones", payload, headers)

    def list_zones(self, headers, params=None):
        return self._request("GET", "/zones", headers=headers, params=params)

    def get_zone(self, zone_id, headers):
        return self._request("GET", f"/zones/{zone_id}", headers=headers)

    def create_posture_override(self, zone_id, payload, headers):
        return self._request(
            "POST", f"/zones/{zone_id}/posture-overrides", payload, headers
        )

    # ---------------- varieties ----------------
    def create_variety(self, payload, headers):
        return self._request("POST", "/varieties", payload, headers)

    def list_varieties(self, headers, params=None):
        return self._request("GET", "/varieties", headers=headers, params=params)

    def get_variety(self, variety_id, headers):
        return self._request("GET", f"/varieties/{variety_id}", headers=headers)

    # ---------------- crop cycles ----------------
    def create_crop_cycle(self, payload, headers):
        return self._request("POST", "/crop-cycles", payload, headers)

    def list_crop_cycles(self, headers, params=None):
        return self._request("GET", "/crop-cycles", headers=headers, params=params)

    def get_crop_cycle(self, cycle_id, headers):
        return self._request("GET", f"/crop-cycles/{cycle_id}", headers=headers)

    def transition_crop_cycle(self, cycle_id, payload, headers):
        return self._request(
            "POST", f"/crop-cycles/{cycle_id}/transitions", payload, headers
        )

    def create_hive_placement(self, cycle_id, payload, headers):
        return self._request(
            "POST", f"/crop-cycles/{cycle_id}/hive-placements", payload, headers
        )

    def create_pollination_check(self, cycle_id, payload, headers):
        return self._request(
            "POST", f"/crop-cycles/{cycle_id}/pollination-checks", payload, headers
        )

    # ---------------- climate strategies ----------------
    def create_climate_strategy(self, payload, headers):
        return self._request("POST", "/climate-strategies", payload, headers)

    def list_climate_strategies(self, headers, params=None):
        return self._request(
            "GET", "/climate-strategies", headers=headers, params=params
        )

    def get_climate_strategy(self, strategy_id, headers):
        return self._request(
            "GET", f"/climate-strategies/{strategy_id}", headers=headers
        )

    def record_climate_actuals(self, strategy_id, payload, headers):
        return self._request(
            "POST", f"/climate-strategies/{strategy_id}/actuals", payload, headers
        )

    def transition_climate_strategy(self, strategy_id, payload, headers):
        return self._request(
            "POST", f"/climate-strategies/{strategy_id}/transitions", payload, headers
        )

    # ---------------- fertigation batches ----------------
    def create_fertigation_batch(self, payload, headers):
        return self._request("POST", "/fertigation-batches", payload, headers)

    def list_fertigation_batches(self, headers, params=None):
        return self._request(
            "GET", "/fertigation-batches", headers=headers, params=params
        )

    def get_fertigation_batch(self, batch_id, headers):
        return self._request("GET", f"/fertigation-batches/{batch_id}", headers=headers)

    def transition_fertigation_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/fertigation-batches/{batch_id}/transitions", payload, headers
        )

    def create_drainage_reading(self, batch_id, payload, headers):
        return self._request(
            "POST",
            f"/fertigation-batches/{batch_id}/drainage-readings",
            payload,
            headers,
        )

    # ---------------- scouting observations ----------------
    def create_scouting_observation(self, payload, headers):
        return self._request("POST", "/scouting-observations", payload, headers)

    def list_scouting_observations(self, headers, params=None):
        return self._request(
            "GET", "/scouting-observations", headers=headers, params=params
        )

    def get_scouting_observation(self, observation_id, headers):
        return self._request(
            "GET", f"/scouting-observations/{observation_id}", headers=headers
        )

    # ---------------- bio control releases ----------------
    def create_bio_control_release(self, payload, headers):
        return self._request("POST", "/bio-control-releases", payload, headers)

    def list_bio_control_releases(self, headers, params=None):
        return self._request(
            "GET", "/bio-control-releases", headers=headers, params=params
        )

    def get_bio_control_release(self, release_id, headers):
        return self._request("GET", f"/bio-control-releases/{release_id}", headers=headers)

    def approve_bio_control_release(self, release_id, payload, headers):
        return self._request(
            "POST", f"/bio-control-releases/{release_id}/approve", payload, headers
        )

    def transition_bio_control_release(self, release_id, payload, headers):
        return self._request(
            "POST", f"/bio-control-releases/{release_id}/transitions", payload, headers
        )

    def execute_bio_control_release(self, release_id, payload, headers):
        return self._request(
            "POST", f"/bio-control-releases/{release_id}/execute", payload, headers
        )

    # ---------------- workers ----------------
    def create_worker(self, payload, headers):
        return self._request("POST", "/workers", payload, headers)

    def list_workers(self, headers, params=None):
        return self._request("GET", "/workers", headers=headers, params=params)

    def get_worker(self, worker_id, headers):
        return self._request("GET", f"/workers/{worker_id}", headers=headers)

    # ---------------- labor tasks ----------------
    def create_labor_task(self, payload, headers):
        return self._request("POST", "/labor-tasks", payload, headers)

    def list_labor_tasks(self, headers, params=None):
        return self._request("GET", "/labor-tasks", headers=headers, params=params)

    def get_labor_task(self, task_id, headers):
        return self._request("GET", f"/labor-tasks/{task_id}", headers=headers)

    def transition_labor_task(self, task_id, payload, headers):
        return self._request(
            "POST", f"/labor-tasks/{task_id}/transitions", payload, headers
        )

    # ---------------- harvest lots ----------------
    def create_harvest_lot(self, payload, headers):
        return self._request("POST", "/harvest-lots", payload, headers)

    def list_harvest_lots(self, headers, params=None):
        return self._request("GET", "/harvest-lots", headers=headers, params=params)

    def get_harvest_lot(self, lot_id, headers):
        return self._request("GET", f"/harvest-lots/{lot_id}", headers=headers)

    def grade_harvest_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/harvest-lots/{lot_id}/grade", payload, headers)

    def regrade_harvest_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/harvest-lots/{lot_id}/regrade", payload, headers)

    def create_cold_chain_event(self, lot_id, payload, headers):
        return self._request(
            "POST", f"/harvest-lots/{lot_id}/cold-chain-events", payload, headers
        )

    # ---------------- retail programs ----------------
    def create_retail_program(self, payload, headers):
        return self._request("POST", "/retail-programs", payload, headers)

    def list_retail_programs(self, headers, params=None):
        return self._request("GET", "/retail-programs", headers=headers, params=params)

    def get_retail_program(self, program_id, headers):
        return self._request("GET", f"/retail-programs/{program_id}", headers=headers)

    # ---------------- commitment weeks ----------------
    def create_commitment_week(self, payload, headers):
        return self._request("POST", "/commitment-weeks", payload, headers)

    def list_commitment_weeks(self, headers, params=None):
        return self._request("GET", "/commitment-weeks", headers=headers, params=params)

    def get_commitment_week(self, week_id, headers):
        return self._request("GET", f"/commitment-weeks/{week_id}", headers=headers)

    def transition_commitment_week(self, week_id, payload, headers):
        return self._request(
            "POST", f"/commitment-weeks/{week_id}/transitions", payload, headers
        )

    # ---------------- lot allocations ----------------
    def list_lot_allocations(self, headers, params=None):
        return self._request("GET", "/lot-allocations", headers=headers, params=params)

    def get_lot_allocation(self, allocation_id, headers):
        return self._request("GET", f"/lot-allocations/{allocation_id}", headers=headers)

    def transition_lot_allocation(self, allocation_id, payload, headers):
        return self._request(
            "POST", f"/lot-allocations/{allocation_id}/transitions", payload, headers
        )

    # ---------------- allocation runs ----------------
    def create_allocation_run(self, payload, headers):
        return self._request("POST", "/allocation-runs", payload, headers)

    # ---------------- logical clock ----------------
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
