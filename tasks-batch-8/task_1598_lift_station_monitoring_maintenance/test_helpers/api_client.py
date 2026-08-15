"""API client: one method per endpoint defined in PRD §4."""
from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/lift-station-ops"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # logical clock (test-driving endpoints, PRD §2.9)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601: str, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    def tick(self, headers: Dict):
        return self._request("POST", f"{PREFIX}/_clock/tick", {}, headers)

    # ------------------------------------------------------------------
    # stations
    # ------------------------------------------------------------------
    def create_station(self, payload: Dict, headers: Dict):
        return self._request("POST", f"{PREFIX}/stations", payload, headers)

    def list_stations(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/stations", headers=headers, params=params)

    def get_station(self, station_id: str, headers: Dict):
        return self._request("GET", f"{PREFIX}/stations/{station_id}", headers=headers)

    def freeze_station(self, station_id: str, headers: Dict):
        return self._request("POST", f"{PREFIX}/stations/{station_id}/freeze", {}, headers)

    def unfreeze_station(self, station_id: str, headers: Dict):
        return self._request("POST", f"{PREFIX}/stations/{station_id}/unfreeze", {}, headers)

    def get_station_summary(self, station_id: str, headers: Dict):
        return self._request("GET", f"{PREFIX}/stations/{station_id}/summary", headers=headers)

    # ------------------------------------------------------------------
    # pumps
    # ------------------------------------------------------------------
    def create_pump(self, payload: Dict, headers: Dict):
        return self._request("POST", f"{PREFIX}/pumps", payload, headers)

    def list_pumps(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/pumps", headers=headers, params=params)

    def list_station_pumps(self, station_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/stations/{station_id}/pumps", headers=headers, params=params,
        )

    def get_pump(self, pump_id: str, headers: Dict):
        return self._request("GET", f"{PREFIX}/pumps/{pump_id}", headers=headers)

    def standby_pump(self, pump_id: str, headers: Dict):
        return self._request("POST", f"{PREFIX}/pumps/{pump_id}/standby", {}, headers)

    def activate_pump(self, pump_id: str, headers: Dict):
        return self._request("POST", f"{PREFIX}/pumps/{pump_id}/activate", {}, headers)

    def mark_pump_out_of_service(self, pump_id: str, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/pumps/{pump_id}/mark-out-of-service", {}, headers,
        )

    def alternate_pumps(self, station_id: str, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/pumps/alternate", {"station_id": station_id}, headers,
        )

    # ------------------------------------------------------------------
    # runtime readings
    # ------------------------------------------------------------------
    def create_runtime_reading(self, pump_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/pumps/{pump_id}/runtime-readings", payload, headers,
        )

    def list_runtime_readings(self, pump_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/pumps/{pump_id}/runtime-readings", headers=headers, params=params,
        )

    # ------------------------------------------------------------------
    # operators
    # ------------------------------------------------------------------
    def create_operator(self, payload: Dict, headers: Dict):
        return self._request("POST", f"{PREFIX}/operators", payload, headers)

    def list_operators(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/operators", headers=headers, params=params)

    def get_operator(self, operator_id: str, headers: Dict):
        return self._request("GET", f"{PREFIX}/operators/{operator_id}", headers=headers)

    # ------------------------------------------------------------------
    # alarm tickets
    # ------------------------------------------------------------------
    def create_alarm_ticket(self, station_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/stations/{station_id}/alarm-tickets", payload, headers,
        )

    def list_station_alarm_tickets(self, station_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/stations/{station_id}/alarm-tickets", headers=headers, params=params,
        )

    def list_alarm_tickets(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/alarm-tickets", headers=headers, params=params)

    def get_alarm_ticket(self, ticket_id: str, headers: Dict):
        return self._request("GET", f"{PREFIX}/alarm-tickets/{ticket_id}", headers=headers)

    def ack_alarm_ticket(self, ticket_id: str, headers: Dict):
        return self._request("POST", f"{PREFIX}/alarm-tickets/{ticket_id}/ack", {}, headers)

    def dispatch_alarm_ticket(self, ticket_id: str, expected_ticket_version: int, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/alarm-tickets/{ticket_id}/dispatch",
            {"expected_ticket_version": expected_ticket_version}, headers,
        )

    def arrive_alarm_ticket(self, ticket_id: str, headers: Dict):
        return self._request("POST", f"{PREFIX}/alarm-tickets/{ticket_id}/arrive", {}, headers)

    def clear_alarm_ticket(self, ticket_id: str, headers: Dict):
        return self._request("POST", f"{PREFIX}/alarm-tickets/{ticket_id}/clear", {}, headers)

    def cancel_alarm_ticket(self, ticket_id: str, headers: Dict):
        return self._request("POST", f"{PREFIX}/alarm-tickets/{ticket_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # pump rebuilds
    # ------------------------------------------------------------------
    def create_pump_rebuild(self, payload: Dict, headers: Dict):
        return self._request("POST", f"{PREFIX}/pump-rebuilds", payload, headers)

    def list_pump_rebuilds(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/pump-rebuilds", headers=headers, params=params)

    def list_pump_rebuilds_for_pump(self, pump_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/pumps/{pump_id}/rebuilds", headers=headers, params=params,
        )

    def get_pump_rebuild(self, rebuild_id: str, headers: Dict):
        return self._request("GET", f"{PREFIX}/pump-rebuilds/{rebuild_id}", headers=headers)

    def start_pump_rebuild(self, rebuild_id: str, headers: Dict):
        return self._request("POST", f"{PREFIX}/pump-rebuilds/{rebuild_id}/start", {}, headers)

    def complete_pump_rebuild(self, rebuild_id: str, headers: Dict):
        return self._request("POST", f"{PREFIX}/pump-rebuilds/{rebuild_id}/complete", {}, headers)

    def cancel_pump_rebuild(self, rebuild_id: str, headers: Dict):
        return self._request("POST", f"{PREFIX}/pump-rebuilds/{rebuild_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # wet-well cleanings
    # ------------------------------------------------------------------
    def create_wet_well_cleaning(self, station_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/stations/{station_id}/wet-well-cleanings", payload, headers,
        )

    def list_station_cleanings(self, station_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/stations/{station_id}/wet-well-cleanings",
            headers=headers, params=params,
        )

    def list_cleanings(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/wet-well-cleanings", headers=headers, params=params,
        )

    def get_cleaning(self, cleaning_id: str, headers: Dict):
        return self._request("GET", f"{PREFIX}/wet-well-cleanings/{cleaning_id}", headers=headers)

    def start_cleaning(self, cleaning_id: str, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/wet-well-cleanings/{cleaning_id}/start", {}, headers,
        )

    def complete_cleaning(self, cleaning_id: str, grease_depth_inches_post, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/wet-well-cleanings/{cleaning_id}/complete",
            {"grease_depth_inches_post": grease_depth_inches_post}, headers,
        )

    def cancel_cleaning(self, cleaning_id: str, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/wet-well-cleanings/{cleaning_id}/cancel", {}, headers,
        )

    # ------------------------------------------------------------------
    # generator tests
    # ------------------------------------------------------------------
    def create_generator_test(self, station_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/stations/{station_id}/generator-tests", payload, headers,
        )

    def list_station_generator_tests(self, station_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/stations/{station_id}/generator-tests",
            headers=headers, params=params,
        )

    def list_generator_tests(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/generator-tests", headers=headers, params=params)

    def get_generator_test(self, test_id: str, headers: Dict):
        return self._request("GET", f"{PREFIX}/generator-tests/{test_id}", headers=headers)

    def start_generator_test(self, test_id: str, headers: Dict):
        return self._request("POST", f"{PREFIX}/generator-tests/{test_id}/start", {}, headers)

    def finish_generator_test(self, test_id: str, duration_minutes, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/generator-tests/{test_id}/finish",
            {"duration_minutes": duration_minutes}, headers,
        )

    def fail_generator_test(self, test_id: str, headers: Dict):
        return self._request("POST", f"{PREFIX}/generator-tests/{test_id}/fail", {}, headers)

    def abort_generator_test(self, test_id: str, headers: Dict):
        return self._request("POST", f"{PREFIX}/generator-tests/{test_id}/abort", {}, headers)

    def cancel_generator_test(self, test_id: str, headers: Dict):
        return self._request("POST", f"{PREFIX}/generator-tests/{test_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # SSO events
    # ------------------------------------------------------------------
    def create_sso_event(self, station_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/stations/{station_id}/sso-events", payload, headers,
        )

    def list_station_sso_events(self, station_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/stations/{station_id}/sso-events", headers=headers, params=params,
        )

    def list_sso_events(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/sso-events", headers=headers, params=params)

    def get_sso_event(self, sso_id: str, headers: Dict):
        return self._request("GET", f"{PREFIX}/sso-events/{sso_id}", headers=headers)

    def contain_sso_event(self, sso_id: str, headers: Dict):
        return self._request("POST", f"{PREFIX}/sso-events/{sso_id}/contain", {}, headers)

    def draft_sso_report(self, sso_id: str, headers: Dict):
        return self._request("POST", f"{PREFIX}/sso-events/{sso_id}/draft-report", {}, headers)

    def submit_sso_report(self, sso_id: str, headers: Dict, override_note: Optional[str] = None):
        payload: Dict = {}
        if override_note is not None:
            payload["override_note"] = override_note
        return self._request(
            "POST", f"{PREFIX}/sso-events/{sso_id}/submit-report", payload, headers,
        )

    def accept_sso_report(self, sso_id: str, headers: Dict):
        return self._request("POST", f"{PREFIX}/sso-events/{sso_id}/accept-report", {}, headers)

    def reject_sso_report(self, sso_id: str, headers: Dict):
        return self._request("POST", f"{PREFIX}/sso-events/{sso_id}/reject-report", {}, headers)

    def close_sso_event(self, sso_id: str, headers: Dict):
        return self._request("POST", f"{PREFIX}/sso-events/{sso_id}/close", {}, headers)

    # ------------------------------------------------------------------
    # confined-space permits
    # ------------------------------------------------------------------
    def create_confined_space_permit(self, station_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/stations/{station_id}/confined-space-permits", payload, headers,
        )

    def list_station_permits(self, station_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/stations/{station_id}/confined-space-permits",
            headers=headers, params=params,
        )

    def list_permits(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/confined-space-permits", headers=headers, params=params,
        )

    def get_permit(self, permit_id: str, headers: Dict):
        return self._request(
            "GET", f"{PREFIX}/confined-space-permits/{permit_id}", headers=headers,
        )

    def issue_permit(self, permit_id: str, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/confined-space-permits/{permit_id}/issue", {}, headers,
        )

    def activate_permit(self, permit_id: str, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/confined-space-permits/{permit_id}/activate", {}, headers,
        )

    def suspend_permit(self, permit_id: str, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/confined-space-permits/{permit_id}/suspend", {}, headers,
        )

    def close_permit(self, permit_id: str, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/confined-space-permits/{permit_id}/close", {}, headers,
        )

    def cancel_permit(self, permit_id: str, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/confined-space-permits/{permit_id}/cancel", {}, headers,
        )

    # ------------------------------------------------------------------
    # capital plans
    # ------------------------------------------------------------------
    def create_capital_plan(self, payload: Dict, headers: Dict):
        return self._request("POST", f"{PREFIX}/capital-plans", payload, headers)

    def list_capital_plans(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/capital-plans", headers=headers, params=params)

    def get_capital_plan(self, plan_id: str, headers: Dict):
        return self._request("GET", f"{PREFIX}/capital-plans/{plan_id}", headers=headers)

    def rank_capital_plan(self, plan_id: str, headers: Dict):
        return self._request("POST", f"{PREFIX}/capital-plans/{plan_id}/rank", {}, headers)

    def approve_capital_plan(self, plan_id: str, expected_plan_version: int, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/capital-plans/{plan_id}/approve",
            {"expected_plan_version": expected_plan_version}, headers,
        )

    def lock_capital_plan(self, plan_id: str, headers: Dict):
        return self._request("POST", f"{PREFIX}/capital-plans/{plan_id}/lock", {}, headers)

    def unrank_capital_plan(self, plan_id: str, headers: Dict):
        return self._request("POST", f"{PREFIX}/capital-plans/{plan_id}/unrank", {}, headers)

    # ------------------------------------------------------------------
    # capital projects
    # ------------------------------------------------------------------
    def create_capital_project(self, payload: Dict, headers: Dict):
        return self._request("POST", f"{PREFIX}/capital-projects", payload, headers)

    def list_plan_projects(self, plan_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/capital-plans/{plan_id}/capital-projects",
            headers=headers, params=params,
        )

    def list_capital_projects(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/capital-projects", headers=headers, params=params)

    def get_capital_project(self, project_id: str, headers: Dict):
        return self._request("GET", f"{PREFIX}/capital-projects/{project_id}", headers=headers)

    def reject_capital_project(self, project_id: str, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/capital-projects/{project_id}/reject", {}, headers,
        )

    def cancel_capital_project(self, project_id: str, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/capital-projects/{project_id}/cancel", {}, headers,
        )

    def resubmit_capital_project(self, project_id: str, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/capital-projects/{project_id}/resubmit", {}, headers,
        )

    # ------------------------------------------------------------------
    # spare pumps
    # ------------------------------------------------------------------
    def create_spare_pump(self, payload: Dict, headers: Dict):
        return self._request("POST", f"{PREFIX}/spare-pumps", payload, headers)

    def list_spare_pumps(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/spare-pumps", headers=headers, params=params)

    def get_spare_pump(self, spare_id: str, headers: Dict):
        return self._request("GET", f"{PREFIX}/spare-pumps/{spare_id}", headers=headers)

    def reserve_spare_pump(self, spare_id: str, station_id: str, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/spare-pumps/{spare_id}/reserve",
            {"station_id": station_id}, headers,
        )

    def deploy_spare_pump(self, spare_id: str, headers: Dict):
        return self._request("POST", f"{PREFIX}/spare-pumps/{spare_id}/deploy", {}, headers)

    def return_spare_pump(self, spare_id: str, headers: Dict):
        return self._request("POST", f"{PREFIX}/spare-pumps/{spare_id}/return", {}, headers)

    def release_spare_pump(self, spare_id: str, headers: Dict):
        return self._request("POST", f"{PREFIX}/spare-pumps/{spare_id}/release", {}, headers)

    def send_spare_pump_to_rebuild(self, spare_id: str, headers: Dict):
        return self._request(
            "POST", f"{PREFIX}/spare-pumps/{spare_id}/send-to-rebuild", {}, headers,
        )

    def retire_spare_pump(self, spare_id: str, headers: Dict):
        return self._request("POST", f"{PREFIX}/spare-pumps/{spare_id}/retire", {}, headers)


api_client = ApiClient()
