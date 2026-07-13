"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── RiverTrip ──────────────────────────────────────────────────────────
    def create_trip(self, payload, headers):
        return self._request("POST", "/trips", payload, headers)

    def list_trips(self, headers, params=None):
        return self._request("GET", "/trips", headers=headers, params=params)

    def get_trip(self, trip_id, headers):
        return self._request("GET", f"/trips/{trip_id}", headers=headers)

    def open_trip(self, trip_id, headers):
        return self._request("POST", f"/trips/{trip_id}/open", {}, headers)

    def complete_trip(self, trip_id, headers):
        return self._request("POST", f"/trips/{trip_id}/complete", {}, headers)

    def cancel_trip(self, trip_id, headers):
        return self._request("POST", f"/trips/{trip_id}/cancel", {}, headers)

    # ── Guide ──────────────────────────────────────────────────────────────
    def create_guide(self, payload, headers):
        return self._request("POST", "/guides", payload, headers)

    def list_guides(self, headers, params=None):
        return self._request("GET", "/guides", headers=headers, params=params)

    def get_guide(self, guide_id, headers):
        return self._request("GET", f"/guides/{guide_id}", headers=headers)

    def deactivate_guide(self, guide_id, headers):
        return self._request("POST", f"/guides/{guide_id}/deactivate", {}, headers)

    # ── GuideAssignment ────────────────────────────────────────────────────
    def create_guide_assignment(self, payload, headers):
        return self._request("POST", "/guide-assignments", payload, headers)

    def list_guide_assignments(self, headers, params=None):
        return self._request("GET", "/guide-assignments", headers=headers, params=params)

    def get_guide_assignment(self, ga_id, headers):
        return self._request("GET", f"/guide-assignments/{ga_id}", headers=headers)

    def release_guide_assignment(self, ga_id, headers):
        return self._request("POST", f"/guide-assignments/{ga_id}/release", {}, headers)

    # ── Reservation ────────────────────────────────────────────────────────
    def create_reservation(self, payload, headers):
        return self._request("POST", "/reservations", payload, headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/reservations", headers=headers, params=params)

    def get_reservation(self, res_id, headers):
        return self._request("GET", f"/reservations/{res_id}", headers=headers)

    def confirm_reservation(self, res_id, headers):
        return self._request("POST", f"/reservations/{res_id}/confirm", {}, headers)

    def pay_deposit(self, res_id, headers):
        return self._request("POST", f"/reservations/{res_id}/pay-deposit", {}, headers)

    def check_in_reservation(self, res_id, headers):
        return self._request("POST", f"/reservations/{res_id}/check-in", {}, headers)

    def settle_reservation(self, res_id, headers, payload):
        return self._request("POST", f"/reservations/{res_id}/settle", payload, headers)

    def cancel_reservation(self, res_id, headers):
        return self._request("POST", f"/reservations/{res_id}/cancel", {}, headers)

    # ── Guest ──────────────────────────────────────────────────────────────
    def create_guest(self, payload, headers):
        return self._request("POST", "/guests", payload, headers)

    def list_guests(self, headers, params=None):
        return self._request("GET", "/guests", headers=headers, params=params)

    def get_guest(self, guest_id, headers):
        return self._request("GET", f"/guests/{guest_id}", headers=headers)

    def remove_guest(self, guest_id, headers):
        return self._request("POST", f"/guests/{guest_id}/remove", {}, headers)

    # ── Waiver ─────────────────────────────────────────────────────────────
    def list_waivers(self, headers, params=None):
        return self._request("GET", "/waivers", headers=headers, params=params)

    def get_waiver(self, waiver_id, headers):
        return self._request("GET", f"/waivers/{waiver_id}", headers=headers)

    def sign_waiver(self, waiver_id, headers, payload=None):
        return self._request("POST", f"/waivers/{waiver_id}/sign", payload or {}, headers)

    # ── GearItem ───────────────────────────────────────────────────────────
    def create_gear_item(self, payload, headers):
        return self._request("POST", "/gear-items", payload, headers)

    def list_gear_items(self, headers, params=None):
        return self._request("GET", "/gear-items", headers=headers, params=params)

    def get_gear_item(self, gear_id, headers):
        return self._request("GET", f"/gear-items/{gear_id}", headers=headers)

    def retire_gear_item(self, gear_id, headers):
        return self._request("POST", f"/gear-items/{gear_id}/retire", {}, headers)

    # ── GearAssignment ─────────────────────────────────────────────────────
    def create_gear_assignment(self, payload, headers):
        return self._request("POST", "/gear-assignments", payload, headers)

    def list_gear_assignments(self, headers, params=None):
        return self._request("GET", "/gear-assignments", headers=headers, params=params)

    def get_gear_assignment(self, gasg_id, headers):
        return self._request("GET", f"/gear-assignments/{gasg_id}", headers=headers)

    def release_gear_assignment(self, gasg_id, headers):
        return self._request("POST", f"/gear-assignments/{gasg_id}/release", {}, headers)

    # ── ShuttleVehicle ─────────────────────────────────────────────────────
    def create_shuttle_vehicle(self, payload, headers):
        return self._request("POST", "/shuttle-vehicles", payload, headers)

    def list_shuttle_vehicles(self, headers, params=None):
        return self._request("GET", "/shuttle-vehicles", headers=headers, params=params)

    def get_shuttle_vehicle(self, veh_id, headers):
        return self._request("GET", f"/shuttle-vehicles/{veh_id}", headers=headers)

    # ── ShuttleRun ─────────────────────────────────────────────────────────
    def create_shuttle_run(self, payload, headers):
        return self._request("POST", "/shuttle-runs", payload, headers)

    def list_shuttle_runs(self, headers, params=None):
        return self._request("GET", "/shuttle-runs", headers=headers, params=params)

    def get_shuttle_run(self, run_id, headers):
        return self._request("GET", f"/shuttle-runs/{run_id}", headers=headers)

    def cancel_shuttle_run(self, run_id, headers):
        return self._request("POST", f"/shuttle-runs/{run_id}/cancel", {}, headers)

    # ── RiverConditionReading ──────────────────────────────────────────────
    def create_condition_reading(self, payload, headers):
        return self._request("POST", "/condition-readings", payload, headers)

    def list_condition_readings(self, headers, params=None):
        return self._request("GET", "/condition-readings", headers=headers, params=params)

    def get_condition_reading(self, reading_id, headers):
        return self._request("GET", f"/condition-readings/{reading_id}", headers=headers)

    # ── Logical clock (test-driving) ───────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
