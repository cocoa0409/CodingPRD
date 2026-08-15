"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Test-driving: logical clock and operations sweep
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/api/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def run_sweep(self, headers):
        return self._request("POST", "/api/_ops/run_sweep", {}, headers)

    # ------------------------------------------------------------------
    # Sites
    # ------------------------------------------------------------------
    def create_site(self, payload, headers):
        return self._request("POST", "/api/sites", payload, headers)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/api/sites/{site_id}", headers=headers)

    def list_sites(self, headers, params=None):
        return self._request("GET", "/api/sites", headers=headers, params=params)

    # ------------------------------------------------------------------
    # ShowEvents
    # ------------------------------------------------------------------
    def create_show_event(self, payload, headers):
        return self._request("POST", "/api/show-events", payload, headers)

    def get_show_event(self, show_id, headers):
        return self._request("GET", f"/api/show-events/{show_id}", headers=headers)

    def list_show_events(self, headers, params=None):
        return self._request("GET", "/api/show-events", headers=headers, params=params)

    def authorize_show(self, show_id, payload, headers):
        return self._request("POST", f"/api/show-events/{show_id}/authorize",
                             payload, headers)

    def certify_go(self, show_id, payload, headers):
        return self._request("POST", f"/api/show-events/{show_id}/certify-go",
                             payload, headers)

    def execute_show(self, show_id, headers):
        return self._request("POST", f"/api/show-events/{show_id}/execute",
                             {}, headers)

    def postpone_show(self, show_id, headers, payload=None):
        return self._request("POST", f"/api/show-events/{show_id}/postpone",
                             payload or {}, headers)

    def reschedule_show(self, show_id, payload, headers):
        return self._request("POST", f"/api/show-events/{show_id}/reschedule",
                             payload, headers)

    def activate_backup(self, show_id, headers):
        return self._request("POST", f"/api/show-events/{show_id}/activate-backup",
                             {}, headers)

    def cancel_show(self, show_id, headers, payload=None):
        return self._request("POST", f"/api/show-events/{show_id}/cancel",
                             payload or {}, headers)

    def settle_cancellation(self, show_id, headers):
        return self._request("POST",
                             f"/api/show-events/{show_id}/settle-cancellation",
                             {}, headers)

    def void_cancellation(self, show_id, headers):
        return self._request("POST",
                             f"/api/show-events/{show_id}/void-cancellation",
                             {}, headers)

    def record_payment(self, show_id, payload, headers):
        return self._request("POST",
                             f"/api/show-events/{show_id}/record-payment",
                             payload, headers)

    def get_readiness(self, show_id, headers):
        return self._request("GET", f"/api/show-events/{show_id}/readiness",
                             headers=headers)

    def get_perimeter_assessment(self, show_id, headers, params=None):
        return self._request("GET",
                             f"/api/show-events/{show_id}/perimeter-assessment",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # AirspaceAuthorizations
    # ------------------------------------------------------------------
    def create_authorization(self, payload, headers):
        return self._request("POST", "/api/airspace-authorizations", payload, headers)

    def get_authorization(self, authorization_id, headers):
        return self._request("GET",
                             f"/api/airspace-authorizations/{authorization_id}",
                             headers=headers)

    def list_authorizations(self, headers, params=None):
        return self._request("GET", "/api/airspace-authorizations",
                             headers=headers, params=params)

    def submit_authorization(self, authorization_id, headers):
        return self._request("POST",
                             f"/api/airspace-authorizations/{authorization_id}/submit",
                             {}, headers)

    def request_info(self, authorization_id, headers, payload=None):
        return self._request("POST",
                             f"/api/airspace-authorizations/{authorization_id}/request-info",
                             payload or {}, headers)

    def resubmit_authorization(self, authorization_id, headers, payload=None):
        return self._request("POST",
                             f"/api/airspace-authorizations/{authorization_id}/resubmit",
                             payload or {}, headers)

    def decide_authorization(self, authorization_id, payload, headers):
        return self._request("POST",
                             f"/api/airspace-authorizations/{authorization_id}/decide",
                             payload, headers)

    def revise_authorization(self, authorization_id, headers, payload=None):
        return self._request("POST",
                             f"/api/airspace-authorizations/{authorization_id}/revise",
                             payload or {}, headers)

    def revoke_authorization(self, authorization_id, headers, payload=None):
        return self._request("POST",
                             f"/api/airspace-authorizations/{authorization_id}/revoke",
                             payload or {}, headers)

    def withdraw_authorization(self, authorization_id, headers):
        return self._request("POST",
                             f"/api/airspace-authorizations/{authorization_id}/withdraw",
                             {}, headers)

    # ------------------------------------------------------------------
    # ShowDesigns
    # ------------------------------------------------------------------
    def create_show_design(self, payload, headers):
        return self._request("POST", "/api/show-designs", payload, headers)

    def get_show_design(self, design_id, headers):
        return self._request("GET", f"/api/show-designs/{design_id}", headers=headers)

    def list_show_designs(self, headers, params=None):
        return self._request("GET", "/api/show-designs", headers=headers,
                             params=params)

    def revise_design(self, design_id, headers):
        return self._request("POST", f"/api/show-designs/{design_id}/revise",
                             {}, headers)

    def lock_design(self, design_id, payload, headers):
        return self._request("POST", f"/api/show-designs/{design_id}/lock",
                             payload, headers)

    # ------------------------------------------------------------------
    # SimulationRuns
    # ------------------------------------------------------------------
    def create_simulation_run(self, payload, headers):
        return self._request("POST", "/api/simulation-runs", payload, headers)

    def get_simulation_run(self, simulation_run_id, headers):
        return self._request("GET", f"/api/simulation-runs/{simulation_run_id}",
                             headers=headers)

    def list_simulation_runs(self, headers, params=None):
        return self._request("GET", "/api/simulation-runs", headers=headers,
                             params=params)

    # ------------------------------------------------------------------
    # SafetyConfigurations
    # ------------------------------------------------------------------
    def create_safety_configuration(self, payload, headers):
        return self._request("POST", "/api/safety-configurations", payload, headers)

    def get_safety_configuration(self, config_id, headers):
        return self._request("GET", f"/api/safety-configurations/{config_id}",
                             headers=headers)

    def list_safety_configurations(self, headers, params=None):
        return self._request("GET", "/api/safety-configurations", headers=headers,
                             params=params)

    def approve_safety_configuration(self, config_id, headers):
        return self._request("POST",
                             f"/api/safety-configurations/{config_id}/approve",
                             {}, headers)

    # ------------------------------------------------------------------
    # Drones
    # ------------------------------------------------------------------
    def create_drone(self, payload, headers):
        return self._request("POST", "/api/drones", payload, headers)

    def get_drone(self, drone_id, headers):
        return self._request("GET", f"/api/drones/{drone_id}", headers=headers)

    def list_drones(self, headers, params=None):
        return self._request("GET", "/api/drones", headers=headers, params=params)

    def ground_drone(self, drone_id, headers):
        return self._request("POST", f"/api/drones/{drone_id}/ground", {}, headers)

    def release_drone(self, drone_id, headers):
        return self._request("POST", f"/api/drones/{drone_id}/release", {}, headers)

    def maintain_drone(self, drone_id, headers):
        return self._request("POST", f"/api/drones/{drone_id}/maintain", {}, headers)

    def retire_drone(self, drone_id, headers):
        return self._request("POST", f"/api/drones/{drone_id}/retire", {}, headers)

    # ------------------------------------------------------------------
    # ChargeBays
    # ------------------------------------------------------------------
    def create_charge_bay(self, payload, headers):
        return self._request("POST", "/api/charge-bays", payload, headers)

    def get_charge_bay(self, charge_bay_id, headers):
        return self._request("GET", f"/api/charge-bays/{charge_bay_id}",
                             headers=headers)

    def list_charge_bays(self, headers, params=None):
        return self._request("GET", "/api/charge-bays", headers=headers,
                             params=params)

    # ------------------------------------------------------------------
    # ChargeSessions
    # ------------------------------------------------------------------
    def create_charge_session(self, payload, headers):
        return self._request("POST", "/api/charge-sessions", payload, headers)

    def get_charge_session(self, charge_session_id, headers):
        return self._request("GET", f"/api/charge-sessions/{charge_session_id}",
                             headers=headers)

    def list_charge_sessions(self, headers, params=None):
        return self._request("GET", "/api/charge-sessions", headers=headers,
                             params=params)

    def complete_charge_session(self, charge_session_id, payload, headers):
        return self._request("POST",
                             f"/api/charge-sessions/{charge_session_id}/complete",
                             payload, headers)

    def interrupt_charge_session(self, charge_session_id, payload, headers):
        return self._request("POST",
                             f"/api/charge-sessions/{charge_session_id}/interrupt",
                             payload, headers)

    # ------------------------------------------------------------------
    # LaunchGridAssignments
    # ------------------------------------------------------------------
    def create_launch_grid_assignment(self, payload, headers):
        return self._request("POST", "/api/launch-grid-assignments", payload, headers)

    def get_launch_grid_assignment(self, assignment_id, headers):
        return self._request("GET",
                             f"/api/launch-grid-assignments/{assignment_id}",
                             headers=headers)

    def list_launch_grid_assignments(self, headers, params=None):
        return self._request("GET", "/api/launch-grid-assignments",
                             headers=headers, params=params)

    def void_launch_grid_assignment(self, assignment_id, headers):
        return self._request("POST",
                             f"/api/launch-grid-assignments/{assignment_id}/void",
                             {}, headers)

    # ------------------------------------------------------------------
    # WeatherReadings
    # ------------------------------------------------------------------
    def create_weather_reading(self, payload, headers):
        return self._request("POST", "/api/weather-readings", payload, headers)

    def get_weather_reading(self, weather_reading_id, headers):
        return self._request("GET", f"/api/weather-readings/{weather_reading_id}",
                             headers=headers)

    def list_weather_readings(self, headers, params=None):
        return self._request("GET", "/api/weather-readings", headers=headers,
                             params=params)

    # ------------------------------------------------------------------
    # GoNoGoEvaluations
    # ------------------------------------------------------------------
    def create_go_no_go_evaluation(self, payload, headers):
        return self._request("POST", "/api/go-no-go-evaluations", payload, headers)

    def get_go_no_go_evaluation(self, evaluation_id, headers):
        return self._request("GET", f"/api/go-no-go-evaluations/{evaluation_id}",
                             headers=headers)

    def list_go_no_go_evaluations(self, headers, params=None):
        return self._request("GET", "/api/go-no-go-evaluations", headers=headers,
                             params=params)

    def certify_go_no_go_evaluation(self, evaluation_id, headers):
        return self._request("POST",
                             f"/api/go-no-go-evaluations/{evaluation_id}/certify",
                             {}, headers)

    # ------------------------------------------------------------------
    # IncidentReports
    # ------------------------------------------------------------------
    def create_incident_report(self, payload, headers):
        return self._request("POST", "/api/incident-reports", payload, headers)

    def get_incident_report(self, incident_id, headers):
        return self._request("GET", f"/api/incident-reports/{incident_id}",
                             headers=headers)

    def list_incident_reports(self, headers, params=None):
        return self._request("GET", "/api/incident-reports", headers=headers,
                             params=params)

    def investigate_incident(self, incident_id, headers):
        return self._request("POST",
                             f"/api/incident-reports/{incident_id}/investigate",
                             {}, headers)

    def close_incident(self, incident_id, payload, headers):
        return self._request("POST", f"/api/incident-reports/{incident_id}/close",
                             payload, headers)

    # ------------------------------------------------------------------
    # FlightLogs
    # ------------------------------------------------------------------
    def create_flight_log(self, payload, headers):
        return self._request("POST", "/api/flight-logs", payload, headers)

    def get_flight_log(self, flight_log_id, headers):
        return self._request("GET", f"/api/flight-logs/{flight_log_id}",
                             headers=headers)

    def list_flight_logs(self, headers, params=None):
        return self._request("GET", "/api/flight-logs", headers=headers,
                             params=params)


api_client = ApiClient()
