"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint, PRD §2.4)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/api/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Episode lifecycle
    # ------------------------------------------------------------------
    def create_episode(self, payload, headers):
        return self._request("POST", "/api/episodes", payload, headers)

    def get_episode(self, episode_id, headers):
        return self._request("GET", f"/api/episodes/{episode_id}", headers=headers)

    def post_weather_reading(self, episode_id, payload, headers):
        return self._request("POST", f"/api/episodes/{episode_id}/weather-readings",
                             payload, headers)

    def list_weather_readings(self, episode_id, headers, params=None):
        return self._request("GET", f"/api/episodes/{episode_id}/weather-readings",
                             headers=headers, params=params)

    def evaluate_episode(self, episode_id, headers):
        return self._request("POST", f"/api/episodes/{episode_id}/evaluate", {}, headers)

    def activate_episode(self, episode_id, headers):
        return self._request("POST", f"/api/episodes/{episode_id}/activate", {}, headers)

    def extend_episode(self, episode_id, payload, headers):
        return self._request("POST", f"/api/episodes/{episode_id}/extensions",
                             payload, headers)

    def deactivate_episode(self, episode_id, headers):
        return self._request("POST", f"/api/episodes/{episode_id}/deactivate", {}, headers)

    def run_ops(self, episode_id, headers):
        return self._request("POST", f"/api/episodes/{episode_id}/run-ops", {}, headers)

    # ------------------------------------------------------------------
    # Site registry
    # ------------------------------------------------------------------
    def create_site(self, payload, headers):
        return self._request("POST", "/api/sites", payload, headers)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/api/sites/{site_id}", headers=headers)

    def patch_site(self, site_id, payload, headers):
        return self._request("PATCH", f"/api/sites/{site_id}", payload, headers)

    # ------------------------------------------------------------------
    # Site activations
    # ------------------------------------------------------------------
    def create_site_activation(self, episode_id, payload, headers):
        return self._request("POST", f"/api/episodes/{episode_id}/site-activations",
                             payload, headers)

    def list_site_activations(self, headers, params=None):
        return self._request("GET", "/api/site-activations", headers=headers, params=params)

    def get_site_activation(self, site_activation_id, headers):
        return self._request("GET", f"/api/site-activations/{site_activation_id}",
                             headers=headers)

    def open_site_activation(self, site_activation_id, headers):
        return self._request("POST", f"/api/site-activations/{site_activation_id}/open",
                             {}, headers)

    def close_site_activation(self, site_activation_id, headers):
        return self._request("POST", f"/api/site-activations/{site_activation_id}/close",
                             {}, headers)

    # ------------------------------------------------------------------
    # Staff roster and shifts
    # ------------------------------------------------------------------
    def create_staff_member(self, payload, headers):
        return self._request("POST", "/api/staff-members", payload, headers)

    def list_staff_members(self, headers, params=None):
        return self._request("GET", "/api/staff-members", headers=headers, params=params)

    def create_shift(self, site_activation_id, payload, headers):
        return self._request("POST", f"/api/site-activations/{site_activation_id}/shifts",
                             payload, headers)

    def list_shifts(self, headers, params=None):
        return self._request("GET", "/api/shifts", headers=headers, params=params)

    def get_shift(self, shift_id, headers):
        return self._request("GET", f"/api/shifts/{shift_id}", headers=headers)

    def confirm_shift(self, shift_id, headers):
        return self._request("POST", f"/api/shifts/{shift_id}/confirm", {}, headers)

    def cancel_shift(self, shift_id, headers):
        return self._request("POST", f"/api/shifts/{shift_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Guests and stays
    # ------------------------------------------------------------------
    def create_guest(self, payload, headers):
        return self._request("POST", "/api/guests", payload, headers)

    def get_guest(self, guest_id, headers):
        return self._request("GET", f"/api/guests/{guest_id}", headers=headers)

    def create_stay(self, site_activation_id, payload, headers):
        return self._request("POST", f"/api/site-activations/{site_activation_id}/stays",
                             payload, headers)

    def list_stays(self, headers, params=None):
        return self._request("GET", "/api/stays", headers=headers, params=params)

    def get_stay(self, stay_id, headers):
        return self._request("GET", f"/api/stays/{stay_id}", headers=headers)

    def check_in_stay(self, stay_id, headers):
        return self._request("POST", f"/api/stays/{stay_id}/check-in", {}, headers)

    def check_out_stay(self, stay_id, headers):
        return self._request("POST", f"/api/stays/{stay_id}/check-out", {}, headers)

    def transfer_stay(self, stay_id, payload, headers):
        return self._request("POST", f"/api/stays/{stay_id}/transfer", payload, headers)

    # ------------------------------------------------------------------
    # Vehicles and transport dispatches
    # ------------------------------------------------------------------
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/api/vehicles", payload, headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/api/vehicles", headers=headers, params=params)

    def create_transport_dispatch(self, payload, headers):
        return self._request("POST", "/api/transport-dispatches", payload, headers)

    def list_transport_dispatches(self, headers, params=None):
        return self._request("GET", "/api/transport-dispatches",
                             headers=headers, params=params)

    def get_transport_dispatch(self, dispatch_id, headers):
        return self._request("GET", f"/api/transport-dispatches/{dispatch_id}",
                             headers=headers)

    def assign_transport_dispatch(self, dispatch_id, payload, headers):
        return self._request("POST", f"/api/transport-dispatches/{dispatch_id}/assign",
                             payload, headers)

    def arrive_transport_dispatch(self, dispatch_id, headers):
        return self._request("POST", f"/api/transport-dispatches/{dispatch_id}/arrive",
                             {}, headers)

    def cancel_transport_dispatch(self, dispatch_id, headers):
        return self._request("POST", f"/api/transport-dispatches/{dispatch_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Donations and meal services
    # ------------------------------------------------------------------
    def create_donation(self, site_activation_id, payload, headers):
        return self._request("POST", f"/api/site-activations/{site_activation_id}/donations",
                             payload, headers)

    def list_donations(self, site_activation_id, headers, params=None):
        return self._request("GET", f"/api/site-activations/{site_activation_id}/donations",
                             headers=headers, params=params)

    def receive_donation(self, donation_id, headers):
        return self._request("POST", f"/api/donations/{donation_id}/receive", {}, headers)

    def create_meal_service(self, site_activation_id, payload, headers):
        return self._request("POST",
                             f"/api/site-activations/{site_activation_id}/meal-services",
                             payload, headers)

    def list_meal_services(self, site_activation_id, headers, params=None):
        return self._request("GET",
                             f"/api/site-activations/{site_activation_id}/meal-services",
                             headers=headers, params=params)

    def serve_meal_service(self, meal_service_id, payload, headers):
        return self._request("POST", f"/api/meal-services/{meal_service_id}/serve",
                             payload, headers)

    # ------------------------------------------------------------------
    # Incidents
    # ------------------------------------------------------------------
    def create_incident(self, payload, headers):
        return self._request("POST", "/api/incidents", payload, headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", "/api/incidents", headers=headers, params=params)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/api/incidents/{incident_id}", headers=headers)

    def escalate_incident(self, incident_id, headers):
        return self._request("POST", f"/api/incidents/{incident_id}/escalate", {}, headers)

    def resolve_incident(self, incident_id, payload, headers):
        return self._request("POST", f"/api/incidents/{incident_id}/resolve",
                             payload, headers)

    # ------------------------------------------------------------------
    # After-action reports
    # ------------------------------------------------------------------
    def create_after_action_report(self, episode_id, headers):
        return self._request("POST", f"/api/episodes/{episode_id}/after-action-reports",
                             {}, headers)

    def list_after_action_reports(self, episode_id, headers, params=None):
        return self._request("GET", f"/api/episodes/{episode_id}/after-action-reports",
                             headers=headers, params=params)

    def submit_after_action_report(self, aar_id, headers):
        return self._request("POST", f"/api/after-action-reports/{aar_id}/submit",
                             {}, headers)

    def approve_after_action_report(self, aar_id, headers):
        return self._request("POST", f"/api/after-action-reports/{aar_id}/approve",
                             {}, headers)


api_client = ApiClient()
