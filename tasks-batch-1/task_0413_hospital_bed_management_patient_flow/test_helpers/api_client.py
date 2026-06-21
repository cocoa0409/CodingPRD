"""API client: one method per endpoint defined in the PRD (Section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ── Units ───────────────────────────────────────────────────────────
    def create_unit(self, payload, headers):
        return self._request("POST", "/units", payload, headers)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/units/{unit_id}", headers=headers)

    def list_units(self, headers, params=None):
        return self._request("GET", "/units", headers=headers, params=params)

    # ── Beds (sub-resource of Unit) ─────────────────────────────────────
    def create_bed(self, unit_id, payload, headers):
        return self._request("POST", f"/units/{unit_id}/beds", payload, headers)

    def get_bed(self, unit_id, bed_id, headers):
        return self._request("GET", f"/units/{unit_id}/beds/{bed_id}", headers=headers)

    def list_beds(self, unit_id, headers, params=None):
        return self._request("GET", f"/units/{unit_id}/beds", headers=headers, params=params)

    def mark_clean_bed(self, unit_id, bed_id, headers):
        return self._request("POST", f"/units/{unit_id}/beds/{bed_id}/mark-clean", {}, headers)

    def block_bed(self, unit_id, bed_id, payload, headers):
        return self._request("POST", f"/units/{unit_id}/beds/{bed_id}/block", payload, headers)

    def unblock_bed(self, unit_id, bed_id, headers):
        return self._request("POST", f"/units/{unit_id}/beds/{bed_id}/unblock", {}, headers)

    def retire_bed(self, unit_id, bed_id, headers):
        return self._request("POST", f"/units/{unit_id}/beds/{bed_id}/retire", {}, headers)

    # ── Encounters & ADT ────────────────────────────────────────────────
    def create_encounter(self, payload, headers):
        return self._request("POST", "/encounters", payload, headers)

    def get_encounter(self, encounter_id, headers):
        return self._request("GET", f"/encounters/{encounter_id}", headers=headers)

    def list_encounters(self, headers, params=None):
        return self._request("GET", "/encounters", headers=headers, params=params)

    def admit_order(self, encounter_id, headers):
        return self._request("POST", f"/encounters/{encounter_id}/admit-order", {}, headers)

    def start_boarding(self, encounter_id, headers):
        return self._request("POST", f"/encounters/{encounter_id}/start-boarding", {}, headers)

    def transfer_encounter(self, encounter_id, payload, headers):
        return self._request("POST", f"/encounters/{encounter_id}/transfer", payload, headers)

    def discharge_order(self, encounter_id, headers):
        return self._request("POST", f"/encounters/{encounter_id}/discharge-order", {}, headers)

    def rescind_discharge(self, encounter_id, headers):
        return self._request("POST", f"/encounters/{encounter_id}/rescind-discharge", {}, headers)

    def discharge(self, encounter_id, headers):
        return self._request("POST", f"/encounters/{encounter_id}/discharge", {}, headers)

    def cancel_encounter(self, encounter_id, headers):
        return self._request("POST", f"/encounters/{encounter_id}/cancel", {}, headers)

    def list_adt_events(self, encounter_id, headers, params=None):
        return self._request("GET", f"/encounters/{encounter_id}/adt-events", headers=headers, params=params)

    # ── BedRequests (transfer-center placement) ─────────────────────────
    def create_bed_request(self, payload, headers):
        return self._request("POST", "/bed-requests", payload, headers)

    def get_bed_request(self, bed_request_id, headers):
        return self._request("GET", f"/bed-requests/{bed_request_id}", headers=headers)

    def list_bed_requests(self, headers, params=None):
        return self._request("GET", "/bed-requests", headers=headers, params=params)

    def auto_place(self, bed_request_id, headers):
        return self._request("POST", f"/bed-requests/{bed_request_id}/auto-place", {}, headers)

    def assign_bed_request(self, bed_request_id, payload, headers):
        return self._request("POST", f"/bed-requests/{bed_request_id}/assign", payload, headers)

    def confirm_bed_request(self, bed_request_id, payload, headers):
        return self._request("POST", f"/bed-requests/{bed_request_id}/confirm", payload, headers)

    def release_bed_request(self, bed_request_id, headers):
        return self._request("POST", f"/bed-requests/{bed_request_id}/release", {}, headers)

    def cancel_bed_request(self, bed_request_id, headers):
        return self._request("POST", f"/bed-requests/{bed_request_id}/cancel", {}, headers)

    # ── EVS turnover ────────────────────────────────────────────────────
    def create_evs_task(self, payload, headers):
        return self._request("POST", "/evs-tasks", payload, headers)

    def get_evs_task(self, evs_task_id, headers):
        return self._request("GET", f"/evs-tasks/{evs_task_id}", headers=headers)

    def list_evs_tasks(self, headers, params=None):
        return self._request("GET", "/evs-tasks", headers=headers, params=params)

    def assign_evs_task(self, evs_task_id, payload, headers):
        return self._request("POST", f"/evs-tasks/{evs_task_id}/assign", payload, headers)

    def start_evs_task(self, evs_task_id, headers):
        return self._request("POST", f"/evs-tasks/{evs_task_id}/start", {}, headers)

    def complete_evs_task(self, evs_task_id, headers):
        return self._request("POST", f"/evs-tasks/{evs_task_id}/complete", {}, headers)

    def cancel_evs_task(self, evs_task_id, headers):
        return self._request("POST", f"/evs-tasks/{evs_task_id}/cancel", {}, headers)

    # ── Discharge barriers ──────────────────────────────────────────────
    def create_discharge_barrier(self, payload, headers):
        return self._request("POST", "/discharge-barriers", payload, headers)

    def get_discharge_barrier(self, barrier_id, headers):
        return self._request("GET", f"/discharge-barriers/{barrier_id}", headers=headers)

    def list_discharge_barriers(self, headers, params=None):
        return self._request("GET", "/discharge-barriers", headers=headers, params=params)

    def resolve_discharge_barrier(self, barrier_id, headers):
        return self._request("POST", f"/discharge-barriers/{barrier_id}/resolve", {}, headers)

    # ── Surge ───────────────────────────────────────────────────────────
    def create_surge_event(self, payload, headers):
        return self._request("POST", "/surge-events", payload, headers)

    def get_surge_event(self, surge_event_id, headers):
        return self._request("GET", f"/surge-events/{surge_event_id}", headers=headers)

    def list_surge_events(self, headers, params=None):
        return self._request("GET", "/surge-events", headers=headers, params=params)

    def stand_down_surge(self, surge_event_id, headers):
        return self._request("POST", f"/surge-events/{surge_event_id}/stand-down", {}, headers)

    # ── Capacity huddles ────────────────────────────────────────────────
    def create_capacity_huddle(self, headers):
        return self._request("POST", "/capacity-huddles", {}, headers)

    def get_capacity_huddle(self, huddle_id, headers):
        return self._request("GET", f"/capacity-huddles/{huddle_id}", headers=headers)

    def list_capacity_huddles(self, headers, params=None):
        return self._request("GET", "/capacity-huddles", headers=headers, params=params)

    # ── Operations / clock (test-driving) ───────────────────────────────
    def ops_run(self, headers):
        return self._request("POST", "/ops/run", {}, headers)

    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
