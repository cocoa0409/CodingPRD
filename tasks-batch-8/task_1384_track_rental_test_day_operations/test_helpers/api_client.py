"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Test-driving capabilities ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def simulate_payment(self, payload, headers):
        return self._request("POST", "/_payments/simulate", payload, headers)

    # --- Track ---
    def create_track(self, payload, headers):
        return self._request("POST", "/tracks", payload, headers)

    def get_track(self, tid, headers):
        return self._request("GET", f"/tracks/{tid}", headers=headers)

    # --- Coach ---
    def create_coach(self, tid, payload, headers):
        return self._request("POST", f"/tracks/{tid}/coaches", payload, headers)

    def get_coach(self, tid, cid, headers):
        return self._request("GET", f"/tracks/{tid}/coaches/{cid}", headers=headers)

    def list_coaches(self, tid, headers, params=None):
        return self._request("GET", f"/tracks/{tid}/coaches", headers=headers, params=params)

    # --- TrackDay ---
    def create_track_day(self, tid, payload, headers):
        return self._request("POST", f"/tracks/{tid}/track-days", payload, headers)

    def get_track_day(self, tid, tdid, headers):
        return self._request("GET", f"/tracks/{tid}/track-days/{tdid}", headers=headers)

    def list_track_days(self, tid, headers, params=None):
        return self._request("GET", f"/tracks/{tid}/track-days", headers=headers, params=params)

    def open_track_day(self, tid, tdid, headers):
        return self._request("POST", f"/tracks/{tid}/track-days/{tdid}/open", {}, headers)

    def weather_hold(self, tid, tdid, headers):
        return self._request("POST", f"/tracks/{tid}/track-days/{tdid}/weather_hold", {}, headers)

    def weather_clear(self, tid, tdid, headers):
        return self._request("POST", f"/tracks/{tid}/track-days/{tdid}/weather_clear", {}, headers)

    def resume_track_day(self, tid, tdid, payload, headers):
        return self._request("POST", f"/tracks/{tid}/track-days/{tdid}/resume", payload, headers)

    def cancel_track_day(self, tid, tdid, payload, headers):
        return self._request("POST", f"/tracks/{tid}/track-days/{tdid}/cancel", payload, headers)

    def close_track_day(self, tid, tdid, headers):
        return self._request("POST", f"/tracks/{tid}/track-days/{tdid}/close", {}, headers)

    def run_ops(self, tid, tdid, headers):
        return self._request("POST", f"/tracks/{tid}/track-days/{tdid}/run_ops", {}, headers)

    # --- RentalBlock ---
    def create_rental_block(self, tid, tdid, payload, headers):
        return self._request("POST", f"/tracks/{tid}/track-days/{tdid}/rental-blocks", payload, headers)

    def get_rental_block(self, tid, tdid, rbid, headers):
        return self._request("GET", f"/tracks/{tid}/track-days/{tdid}/rental-blocks/{rbid}", headers=headers)

    def list_rental_blocks(self, tid, tdid, headers, params=None):
        return self._request("GET", f"/tracks/{tid}/track-days/{tdid}/rental-blocks", headers=headers, params=params)

    def close_block(self, tid, tdid, rbid, headers):
        return self._request("POST", f"/tracks/{tid}/track-days/{tdid}/rental-blocks/{rbid}/close_block", {}, headers)

    # --- Booking ---
    def create_booking(self, tid, tdid, rbid, payload, headers):
        return self._request("POST", f"/tracks/{tid}/track-days/{tdid}/rental-blocks/{rbid}/bookings", payload, headers)

    def get_booking(self, tid, tdid, rbid, bid, headers):
        return self._request("GET", f"/tracks/{tid}/track-days/{tdid}/rental-blocks/{rbid}/bookings/{bid}", headers=headers)

    def list_bookings(self, tid, tdid, rbid, headers, params=None):
        return self._request("GET", f"/tracks/{tid}/track-days/{tdid}/rental-blocks/{rbid}/bookings", headers=headers, params=params)

    def approve_booking(self, tid, tdid, rbid, bid, payload, headers):
        return self._request("POST", f"/tracks/{tid}/track-days/{tdid}/rental-blocks/{rbid}/bookings/{bid}/approve", payload, headers)

    def reject_booking(self, tid, tdid, rbid, bid, headers):
        return self._request("POST", f"/tracks/{tid}/track-days/{tdid}/rental-blocks/{rbid}/bookings/{bid}/reject", {}, headers)

    def cancel_booking(self, tid, tdid, rbid, bid, payload, headers):
        return self._request("POST", f"/tracks/{tid}/track-days/{tdid}/rental-blocks/{rbid}/bookings/{bid}/cancel", payload, headers)

    def assign_coach(self, tid, tdid, rbid, bid, payload, headers):
        return self._request("POST", f"/tracks/{tid}/track-days/{tdid}/rental-blocks/{rbid}/bookings/{bid}/assign_coach", payload, headers)

    # --- Driver ---
    def create_driver(self, tid, tdid, rbid, bid, payload, headers):
        return self._request("POST", f"/tracks/{tid}/track-days/{tdid}/rental-blocks/{rbid}/bookings/{bid}/drivers", payload, headers)

    def get_driver(self, tid, tdid, rbid, bid, did, headers):
        return self._request("GET", f"/tracks/{tid}/track-days/{tdid}/rental-blocks/{rbid}/bookings/{bid}/drivers/{did}", headers=headers)

    def list_drivers(self, tid, tdid, rbid, bid, headers, params=None):
        return self._request("GET", f"/tracks/{tid}/track-days/{tdid}/rental-blocks/{rbid}/bookings/{bid}/drivers", headers=headers, params=params)

    def submit_waiver(self, tid, tdid, rbid, bid, did, payload, headers):
        return self._request("POST", f"/tracks/{tid}/track-days/{tdid}/rental-blocks/{rbid}/bookings/{bid}/drivers/{did}/waiver", payload, headers)

    def list_waivers(self, tid, tdid, rbid, bid, did, headers):
        return self._request("GET", f"/tracks/{tid}/track-days/{tdid}/rental-blocks/{rbid}/bookings/{bid}/drivers/{did}/waivers", headers=headers)

    def inspect_driver(self, tid, tdid, rbid, bid, did, payload, headers):
        return self._request("POST", f"/tracks/{tid}/track-days/{tdid}/rental-blocks/{rbid}/bookings/{bid}/drivers/{did}/inspect", payload, headers)

    def list_inspections(self, tid, tdid, rbid, bid, did, headers):
        return self._request("GET", f"/tracks/{tid}/track-days/{tdid}/rental-blocks/{rbid}/bookings/{bid}/drivers/{did}/inspections", headers=headers)

    # --- Session ---
    def create_session(self, tid, tdid, payload, headers):
        return self._request("POST", f"/tracks/{tid}/track-days/{tdid}/sessions", payload, headers)

    def get_session(self, tid, tdid, sid, headers):
        return self._request("GET", f"/tracks/{tid}/track-days/{tdid}/sessions/{sid}", headers=headers)

    def list_sessions(self, tid, tdid, headers, params=None):
        return self._request("GET", f"/tracks/{tid}/track-days/{tdid}/sessions", headers=headers, params=params)

    def checkered(self, tid, tdid, sid, headers):
        return self._request("POST", f"/tracks/{tid}/track-days/{tdid}/sessions/{sid}/checkered", {}, headers)

    def lap_event(self, tid, tdid, sid, headers):
        return self._request("POST", f"/tracks/{tid}/track-days/{tdid}/sessions/{sid}/lap_event", {}, headers)

    # --- Incident ---
    def report_incident(self, tid, tdid, payload, headers):
        return self._request("POST", f"/tracks/{tid}/track-days/{tdid}/incidents", payload, headers)

    def get_incident(self, tid, tdid, iid, headers):
        return self._request("GET", f"/tracks/{tid}/track-days/{tdid}/incidents/{iid}", headers=headers)

    def list_incidents(self, tid, tdid, headers, params=None):
        return self._request("GET", f"/tracks/{tid}/track-days/{tdid}/incidents", headers=headers, params=params)

    def investigate_incident(self, tid, tdid, iid, headers):
        return self._request("POST", f"/tracks/{tid}/track-days/{tdid}/incidents/{iid}/investigate", {}, headers)

    def clear_incident(self, tid, tdid, iid, payload, headers):
        return self._request("POST", f"/tracks/{tid}/track-days/{tdid}/incidents/{iid}/clear", payload, headers)

    # --- NoiseReading ---
    def create_noise_reading(self, tid, tdid, payload, headers):
        return self._request("POST", f"/tracks/{tid}/track-days/{tdid}/noise-readings", payload, headers)

    def list_noise_readings(self, tid, tdid, headers, params=None):
        return self._request("GET", f"/tracks/{tid}/track-days/{tdid}/noise-readings", headers=headers, params=params)

    # --- GarageAssignment ---
    def create_garage_assignment(self, tid, tdid, payload, headers):
        return self._request("POST", f"/tracks/{tid}/track-days/{tdid}/garage-assignments", payload, headers)

    def get_garage_assignment(self, tid, tdid, gid, headers):
        return self._request("GET", f"/tracks/{tid}/track-days/{tdid}/garage-assignments/{gid}", headers=headers)

    def list_garage_assignments(self, tid, tdid, headers, params=None):
        return self._request("GET", f"/tracks/{tid}/track-days/{tdid}/garage-assignments", headers=headers, params=params)

    def release_garage_assignment(self, tid, tdid, gid, headers):
        return self._request("POST", f"/tracks/{tid}/track-days/{tdid}/garage-assignments/{gid}/release", {}, headers)

    # --- PaddockAssignment ---
    def create_paddock_assignment(self, tid, tdid, payload, headers):
        return self._request("POST", f"/tracks/{tid}/track-days/{tdid}/paddock-assignments", payload, headers)

    def get_paddock_assignment(self, tid, tdid, pid, headers):
        return self._request("GET", f"/tracks/{tid}/track-days/{tdid}/paddock-assignments/{pid}", headers=headers)

    def list_paddock_assignments(self, tid, tdid, headers, params=None):
        return self._request("GET", f"/tracks/{tid}/track-days/{tdid}/paddock-assignments", headers=headers, params=params)

    def release_paddock_assignment(self, tid, tdid, pid, headers):
        return self._request("POST", f"/tracks/{tid}/track-days/{tdid}/paddock-assignments/{pid}/release", {}, headers)

    # --- Flat canonical lookup + filtered-list aliases ---
    def get_coach_flat(self, cid, headers):
        return self._request("GET", f"/tracks/coaches/{cid}", headers=headers)

    def list_coaches_flat(self, headers, params=None):
        return self._request("GET", "/tracks/coaches", headers=headers, params=params)

    def get_track_day_flat(self, tdid, headers):
        return self._request("GET", f"/tracks/track-days/{tdid}", headers=headers)

    def list_track_days_flat(self, headers, params=None):
        return self._request("GET", "/tracks/track-days", headers=headers, params=params)

    def get_rental_block_flat(self, rbid, headers):
        return self._request("GET", f"/tracks/rental-blocks/{rbid}", headers=headers)

    def list_rental_blocks_flat(self, headers, params=None):
        return self._request("GET", "/tracks/rental-blocks", headers=headers, params=params)

    def get_booking_flat(self, bid, headers):
        return self._request("GET", f"/tracks/bookings/{bid}", headers=headers)

    def list_bookings_flat(self, headers, params=None):
        return self._request("GET", "/tracks/bookings", headers=headers, params=params)

    def get_driver_flat(self, did, headers):
        return self._request("GET", f"/tracks/drivers/{did}", headers=headers)

    def list_drivers_flat(self, headers, params=None):
        return self._request("GET", "/tracks/drivers", headers=headers, params=params)

    def get_waiver_flat(self, wid, headers):
        return self._request("GET", f"/tracks/waivers/{wid}", headers=headers)

    def list_waivers_flat(self, headers, params=None):
        return self._request("GET", "/tracks/waivers", headers=headers, params=params)

    def get_inspection_flat(self, siid, headers):
        return self._request("GET", f"/tracks/safety-inspections/{siid}", headers=headers)

    def list_inspections_flat(self, headers, params=None):
        return self._request("GET", "/tracks/safety-inspections", headers=headers, params=params)

    def get_session_flat(self, sid, headers):
        return self._request("GET", f"/tracks/sessions/{sid}", headers=headers)

    def list_sessions_flat(self, headers, params=None):
        return self._request("GET", "/tracks/sessions", headers=headers, params=params)

    def get_incident_flat(self, iid, headers):
        return self._request("GET", f"/tracks/incidents/{iid}", headers=headers)

    def list_incidents_flat(self, headers, params=None):
        return self._request("GET", "/tracks/incidents", headers=headers, params=params)

    def get_noise_reading_flat(self, nrid, headers):
        return self._request("GET", f"/tracks/noise-readings/{nrid}", headers=headers)

    def list_noise_readings_flat(self, headers, params=None):
        return self._request("GET", "/tracks/noise-readings", headers=headers, params=params)

    def get_garage_assignment_flat(self, gid, headers):
        return self._request("GET", f"/tracks/garage-assignments/{gid}", headers=headers)

    def list_garage_assignments_flat(self, headers, params=None):
        return self._request("GET", "/tracks/garage-assignments", headers=headers, params=params)

    def get_paddock_assignment_flat(self, pid, headers):
        return self._request("GET", f"/tracks/paddock-assignments/{pid}", headers=headers)

    def list_paddock_assignments_flat(self, headers, params=None):
        return self._request("GET", "/tracks/paddock-assignments", headers=headers, params=params)


api_client = ApiClient()
