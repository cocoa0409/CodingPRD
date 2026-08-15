"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Events ---
    def create_event(self, payload, headers):
        return self._request("POST", "/events", payload, headers)

    def list_events(self, headers, params=None):
        return self._request("GET", "/events", headers=headers, params=params)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/events/{event_id}", headers=headers)

    def update_event(self, event_id, payload, headers):
        return self._request("PATCH", f"/events/{event_id}", payload, headers)

    def publish_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/publish", {}, headers)

    def open_registration(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/open-registration", {}, headers)

    def lock_registration(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/lock-registration", {}, headers)

    def start_judging(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/start-judging", {}, headers)

    def weather_decision(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/weather-decision", payload, headers)

    def finalize_tabulations(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/tabulations/finalize", payload, headers)

    def close_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/close", {}, headers)

    def get_event_summary(self, event_id, headers):
        return self._request("GET", f"/events/{event_id}/summary", headers=headers)

    # --- Classes ---
    def create_class(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/classes", payload, headers)

    def list_classes(self, event_id, headers, params=None):
        return self._request("GET", f"/events/{event_id}/classes", headers=headers, params=params)

    # --- Zones ---
    def create_zone(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/zones", payload, headers)

    def list_zones(self, event_id, headers, params=None):
        return self._request("GET", f"/events/{event_id}/zones", headers=headers, params=params)

    # --- Judges ---
    def create_judge(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/judges", payload, headers)

    def list_judges(self, event_id, headers, params=None):
        return self._request("GET", f"/events/{event_id}/judges", headers=headers, params=params)

    # --- Sound slots ---
    def create_sound_slot(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/sound-slots", payload, headers)

    def list_sound_slots(self, event_id, headers, params=None):
        return self._request("GET", f"/events/{event_id}/sound-slots", headers=headers, params=params)

    def cancel_sound_slot(self, slot_id, headers):
        return self._request("POST", f"/sound-slots/{slot_id}/cancel", {}, headers)

    # --- Noise readings ---
    def create_noise_reading(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/noise-readings", payload, headers)

    def list_noise_readings(self, event_id, headers, params=None):
        return self._request("GET", f"/events/{event_id}/noise-readings", headers=headers, params=params)

    # --- Registrants / vehicles ---
    def create_registrant(self, payload, headers):
        return self._request("POST", "/registrants", payload, headers)

    def get_registrant(self, registrant_id, headers):
        return self._request("GET", f"/registrants/{registrant_id}", headers=headers)

    def create_vehicle(self, registrant_id, payload, headers):
        return self._request("POST", f"/registrants/{registrant_id}/vehicles", payload, headers)

    def list_vehicles(self, registrant_id, headers, params=None):
        return self._request("GET", f"/registrants/{registrant_id}/vehicles", headers=headers, params=params)

    # --- Waivers ---
    def create_waiver(self, payload, headers):
        return self._request("POST", "/waivers", payload, headers)

    def list_waivers(self, headers, params=None):
        return self._request("GET", "/waivers", headers=headers, params=params)

    def get_waiver(self, waiver_id, headers):
        return self._request("GET", f"/waivers/{waiver_id}", headers=headers)

    # --- Registrations ---
    def create_registration(self, payload, headers):
        return self._request("POST", "/registrations", payload, headers)

    def list_registrations(self, headers, params=None):
        return self._request("GET", "/registrations", headers=headers, params=params)

    def get_registration(self, registration_id, headers):
        return self._request("GET", f"/registrations/{registration_id}", headers=headers)

    def create_registration_payment(self, registration_id, payload, headers):
        return self._request("POST", f"/registrations/{registration_id}/payments", payload, headers)

    def list_registration_payments(self, registration_id, headers, params=None):
        return self._request("GET", f"/registrations/{registration_id}/payments", headers=headers, params=params)

    def check_in_registration(self, registration_id, payload, headers):
        return self._request("POST", f"/registrations/{registration_id}/check-in", payload, headers)

    def withdraw_registration(self, registration_id, payload, headers):
        return self._request("POST", f"/registrations/{registration_id}/withdraw", payload, headers)

    def refund_decision(self, registration_id, payload, headers):
        return self._request("POST", f"/registrations/{registration_id}/refund-decision", payload, headers)

    # --- Score sheets ---
    def create_score_sheet(self, payload, headers):
        return self._request("POST", "/score-sheets", payload, headers)

    def list_score_sheets(self, headers, params=None):
        return self._request("GET", "/score-sheets", headers=headers, params=params)

    def get_score_sheet(self, sheet_id, headers):
        return self._request("GET", f"/score-sheets/{sheet_id}", headers=headers)

    def submit_score_sheet(self, sheet_id, headers):
        return self._request("POST", f"/score-sheets/{sheet_id}/submit", {}, headers)

    def reopen_score_sheet(self, sheet_id, payload, headers):
        return self._request("POST", f"/score-sheets/{sheet_id}/reopen", payload, headers)

    # --- Ballots ---
    def create_ballot(self, payload, headers):
        return self._request("POST", "/ballots", payload, headers)

    def list_ballots(self, headers, params=None):
        return self._request("GET", "/ballots", headers=headers, params=params)

    def get_ballot(self, ballot_id, headers):
        return self._request("GET", f"/ballots/{ballot_id}", headers=headers)

    # --- Awards ---
    def list_awards(self, headers, params=None):
        return self._request("GET", "/awards", headers=headers, params=params)

    def get_award(self, award_id, headers):
        return self._request("GET", f"/awards/{award_id}", headers=headers)

    def override_winner(self, award_id, payload, headers):
        return self._request("POST", f"/awards/{award_id}/override-winner", payload, headers)

    def present_award(self, award_id, headers):
        return self._request("POST", f"/awards/{award_id}/present", {}, headers)

    # --- Booth applications ---
    def create_booth_application(self, payload, headers):
        return self._request("POST", "/booth-applications", payload, headers)

    def list_booth_applications(self, headers, params=None):
        return self._request("GET", "/booth-applications", headers=headers, params=params)

    def get_booth_application(self, app_id, headers):
        return self._request("GET", f"/booth-applications/{app_id}", headers=headers)

    def approve_booth_application(self, app_id, headers):
        return self._request("POST", f"/booth-applications/{app_id}/approve", {}, headers)

    def reject_booth_application(self, app_id, headers):
        return self._request("POST", f"/booth-applications/{app_id}/reject", {}, headers)

    def create_booth_payment(self, app_id, payload, headers):
        return self._request("POST", f"/booth-applications/{app_id}/payments", payload, headers)

    def list_booth_payments(self, app_id, headers, params=None):
        return self._request("GET", f"/booth-applications/{app_id}/payments", headers=headers, params=params)

    def assign_booth(self, app_id, payload, headers):
        return self._request("POST", f"/booth-applications/{app_id}/assign", payload, headers)

    def cancel_booth_application(self, app_id, payload, headers):
        return self._request("POST", f"/booth-applications/{app_id}/cancel", payload, headers)

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
