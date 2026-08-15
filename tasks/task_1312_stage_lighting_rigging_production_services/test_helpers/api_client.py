"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Venues ---
    def create_venue(self, payload, headers):
        return self._request("POST", "/api/venues", payload, headers)

    def list_venues(self, headers, params=None):
        return self._request("GET", "/api/venues", headers=headers, params=params)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/api/venues/{venue_id}", headers=headers)

    def list_venue_productions(self, venue_id, headers, params=None):
        return self._request("GET", f"/api/venues/{venue_id}/productions", headers=headers, params=params)

    # --- Technicians ---
    def create_technician(self, payload, headers):
        return self._request("POST", "/api/technicians", payload, headers)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"/api/technicians/{technician_id}", headers=headers)

    def list_technician_assignments(self, technician_id, headers, params=None):
        return self._request("GET", f"/api/technicians/{technician_id}/crew-assignments", headers=headers, params=params)

    # --- Productions ---
    def create_production(self, payload, headers):
        return self._request("POST", "/api/productions", payload, headers)

    def list_productions(self, headers, params=None):
        return self._request("GET", "/api/productions", headers=headers, params=params)

    def get_production(self, production_id, headers):
        return self._request("GET", f"/api/productions/{production_id}", headers=headers)

    def transition_production(self, production_id, payload, headers):
        return self._request("POST", f"/api/productions/{production_id}/transition", payload, headers)

    # --- Lighting plots ---
    def create_plot(self, production_id, payload, headers):
        return self._request("POST", f"/api/productions/{production_id}/plots", payload, headers)

    def list_production_plots(self, production_id, headers, params=None):
        return self._request("GET", f"/api/productions/{production_id}/plots", headers=headers, params=params)

    def get_plot(self, plot_id, headers):
        return self._request("GET", f"/api/plots/{plot_id}", headers=headers)

    def transition_plot(self, plot_id, payload, headers):
        return self._request("POST", f"/api/plots/{plot_id}/transition", payload, headers)

    # --- Rigging points ---
    def create_rigging_point(self, plot_id, payload, headers):
        return self._request("POST", f"/api/plots/{plot_id}/rigging-points", payload, headers)

    def list_plot_rigging_points(self, plot_id, headers, params=None):
        return self._request("GET", f"/api/plots/{plot_id}/rigging-points", headers=headers, params=params)

    def get_rigging_point(self, point_id, headers):
        return self._request("GET", f"/api/rigging-points/{point_id}", headers=headers)

    def transition_rigging_point(self, point_id, payload, headers):
        return self._request("POST", f"/api/rigging-points/{point_id}/transition", payload, headers)

    # --- Equipment assets ---
    def create_asset(self, payload, headers):
        return self._request("POST", "/api/assets", payload, headers)

    def list_assets(self, headers, params=None):
        return self._request("GET", "/api/assets", headers=headers, params=params)

    def get_asset(self, asset_id, headers):
        return self._request("GET", f"/api/assets/{asset_id}", headers=headers)

    def list_asset_pull_list_entries(self, asset_id, headers, params=None):
        return self._request("GET", f"/api/assets/{asset_id}/pull-list-entries", headers=headers, params=params)

    def transition_asset(self, asset_id, payload, headers):
        return self._request("POST", f"/api/assets/{asset_id}/transition", payload, headers)

    # --- Pull list entries ---
    def create_pull_list_entry(self, production_id, payload, headers):
        return self._request("POST", f"/api/productions/{production_id}/pull-list-entries", payload, headers)

    def list_production_pull_list_entries(self, production_id, headers, params=None):
        return self._request("GET", f"/api/productions/{production_id}/pull-list-entries", headers=headers, params=params)

    def get_pull_list_entry(self, entry_id, headers):
        return self._request("GET", f"/api/pull-list-entries/{entry_id}", headers=headers)

    def list_entry_damage_reports(self, entry_id, headers, params=None):
        return self._request("GET", f"/api/pull-list-entries/{entry_id}/damage-reports", headers=headers, params=params)

    def transition_pull_list_entry(self, entry_id, payload, headers):
        return self._request("POST", f"/api/pull-list-entries/{entry_id}/transition", payload, headers)

    # --- Crew calls & assignments ---
    def create_crew_call(self, production_id, payload, headers):
        return self._request("POST", f"/api/productions/{production_id}/crew-calls", payload, headers)

    def list_production_crew_calls(self, production_id, headers, params=None):
        return self._request("GET", f"/api/productions/{production_id}/crew-calls", headers=headers, params=params)

    def get_crew_call(self, call_id, headers):
        return self._request("GET", f"/api/crew-calls/{call_id}", headers=headers)

    def transition_crew_call(self, call_id, payload, headers):
        return self._request("POST", f"/api/crew-calls/{call_id}/transition", payload, headers)

    def create_crew_assignment(self, call_id, payload, headers):
        return self._request("POST", f"/api/crew-calls/{call_id}/assignments", payload, headers)

    def list_call_assignments(self, call_id, headers, params=None):
        return self._request("GET", f"/api/crew-calls/{call_id}/assignments", headers=headers, params=params)

    def get_crew_assignment(self, assignment_id, headers):
        return self._request("GET", f"/api/crew-assignments/{assignment_id}", headers=headers)

    def transition_crew_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/api/crew-assignments/{assignment_id}/transition", payload, headers)

    # --- Power plans ---
    def create_power_plan(self, production_id, payload, headers):
        return self._request("POST", f"/api/productions/{production_id}/power-plans", payload, headers)

    def list_production_power_plans(self, production_id, headers, params=None):
        return self._request("GET", f"/api/productions/{production_id}/power-plans", headers=headers, params=params)

    def get_power_plan(self, plan_id, headers):
        return self._request("GET", f"/api/power-plans/{plan_id}", headers=headers)

    def transition_power_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/api/power-plans/{plan_id}/transition", payload, headers)

    # --- Trucks & load schedules ---
    def create_truck(self, payload, headers):
        return self._request("POST", "/api/trucks", payload, headers)

    def get_truck(self, truck_id, headers):
        return self._request("GET", f"/api/trucks/{truck_id}", headers=headers)

    def list_truck_load_schedules(self, truck_id, headers, params=None):
        return self._request("GET", f"/api/trucks/{truck_id}/load-schedules", headers=headers, params=params)

    def create_load_schedule(self, production_id, payload, headers):
        return self._request("POST", f"/api/productions/{production_id}/load-schedules", payload, headers)

    def list_production_load_schedules(self, production_id, headers, params=None):
        return self._request("GET", f"/api/productions/{production_id}/load-schedules", headers=headers, params=params)

    def get_load_schedule(self, schedule_id, headers):
        return self._request("GET", f"/api/load-schedules/{schedule_id}", headers=headers)

    def list_schedule_pull_list_entries(self, schedule_id, headers, params=None):
        return self._request("GET", f"/api/load-schedules/{schedule_id}/pull-list-entries", headers=headers, params=params)

    def transition_load_schedule(self, schedule_id, payload, headers):
        return self._request("POST", f"/api/load-schedules/{schedule_id}/transition", payload, headers)

    # --- Safety inspections ---
    def create_inspection(self, production_id, payload, headers):
        return self._request("POST", f"/api/productions/{production_id}/inspections", payload, headers)

    def list_production_inspections(self, production_id, headers, params=None):
        return self._request("GET", f"/api/productions/{production_id}/inspections", headers=headers, params=params)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/api/inspections/{inspection_id}", headers=headers)

    def transition_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/api/inspections/{inspection_id}/transition", payload, headers)

    # --- Damage reports ---
    def create_damage_report(self, production_id, payload, headers):
        return self._request("POST", f"/api/productions/{production_id}/damage-reports", payload, headers)

    def list_production_damage_reports(self, production_id, headers, params=None):
        return self._request("GET", f"/api/productions/{production_id}/damage-reports", headers=headers, params=params)

    def get_damage_report(self, report_id, headers):
        return self._request("GET", f"/api/damage-reports/{report_id}", headers=headers)

    def assess_damage_report(self, report_id, payload, headers):
        return self._request("POST", f"/api/damage-reports/{report_id}/assess", payload, headers)

    def transition_damage_report(self, report_id, payload, headers):
        return self._request("POST", f"/api/damage-reports/{report_id}/transition", payload, headers)

    # --- Settlement statements ---
    def create_settlement(self, production_id, headers):
        return self._request("POST", f"/api/productions/{production_id}/settlement", {}, headers)

    def get_production_settlement(self, production_id, headers):
        return self._request("GET", f"/api/productions/{production_id}/settlement", headers=headers)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/api/settlements/{settlement_id}", headers=headers)

    def transition_settlement(self, settlement_id, payload, headers):
        return self._request("POST", f"/api/settlements/{settlement_id}/transition", payload, headers)

    # --- Logical clock (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
