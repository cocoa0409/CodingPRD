"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Depot ---
    def create_depot(self, payload, headers):
        return self._request("POST", "/depots", payload, headers)

    def get_depot(self, depot_id, headers):
        return self._request("GET", f"/depots/{depot_id}", headers=headers)

    # --- Vehicle ---
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/vehicles/{vehicle_id}", headers=headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/vehicles", headers=headers, params=params)

    # --- Operator ---
    def create_operator(self, payload, headers):
        return self._request("POST", "/operators", payload, headers)

    def get_operator(self, operator_id, headers):
        return self._request("GET", f"/operators/{operator_id}", headers=headers)

    # --- Route ---
    def create_route(self, payload, headers):
        return self._request("POST", "/routes", payload, headers)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/routes/{route_id}", headers=headers)

    # --- StormEvent ---
    def create_storm_event(self, payload, headers):
        return self._request("POST", "/storm-events", payload, headers)

    def get_storm_event(self, storm_id, headers):
        return self._request("GET", f"/storm-events/{storm_id}", headers=headers)

    def activate_storm_event(self, storm_id, headers):
        return self._request("POST", f"/storm-events/{storm_id}/activate", {}, headers)

    def close_storm_event(self, storm_id, headers):
        return self._request("POST", f"/storm-events/{storm_id}/close", {}, headers)

    def finalize_billing(self, storm_id, headers):
        return self._request("POST", f"/storm-events/{storm_id}/finalize-billing", {}, headers)

    # --- RouteAssignment ---
    def create_assignment(self, storm_id, payload, headers):
        return self._request("POST", f"/storm-events/{storm_id}/assignments", payload, headers)

    def list_storm_assignments(self, storm_id, headers, params=None):
        return self._request("GET", f"/storm-events/{storm_id}/assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}", headers=headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/assignments", headers=headers, params=params)

    def start_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/start", {}, headers)

    def complete_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/complete", {}, headers)

    def cancel_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/cancel", {}, headers)

    def avl_ping(self, assignment_id, payload, headers):
        return self._request("POST", f"/assignments/{assignment_id}/avl-ping", payload, headers)

    # --- MaterialApplication ---
    def create_application(self, assignment_id, payload, headers):
        return self._request("POST", f"/assignments/{assignment_id}/applications", payload, headers)

    def list_assignment_applications(self, assignment_id, headers, params=None):
        return self._request("GET", f"/assignments/{assignment_id}/applications", headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/material-applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/material-applications", headers=headers, params=params)

    def void_application(self, application_id, headers):
        return self._request("POST", f"/material-applications/{application_id}/void", {}, headers)

    # --- Callout ---
    def create_callout(self, storm_id, payload, headers):
        return self._request("POST", f"/storm-events/{storm_id}/callouts", payload, headers)

    def list_storm_callouts(self, storm_id, headers, params=None):
        return self._request("GET", f"/storm-events/{storm_id}/callouts", headers=headers, params=params)

    def get_callout(self, callout_id, headers):
        return self._request("GET", f"/callouts/{callout_id}", headers=headers)

    def list_callouts(self, headers, params=None):
        return self._request("GET", "/callouts", headers=headers, params=params)

    def complete_callout(self, callout_id, payload, headers):
        return self._request("POST", f"/callouts/{callout_id}/complete", payload, headers)

    def cancel_callout(self, callout_id, headers):
        return self._request("POST", f"/callouts/{callout_id}/cancel", {}, headers)

    # --- Complaint ---
    def create_complaint(self, payload, headers):
        return self._request("POST", "/complaints", payload, headers)

    def get_complaint(self, complaint_id, headers):
        return self._request("GET", f"/complaints/{complaint_id}", headers=headers)

    def list_complaints(self, headers, params=None):
        return self._request("GET", "/complaints", headers=headers, params=params)

    def investigate_complaint(self, complaint_id, payload, headers):
        return self._request("POST", f"/complaints/{complaint_id}/investigate", payload, headers)

    def resolve_complaint(self, complaint_id, headers):
        return self._request("POST", f"/complaints/{complaint_id}/resolve", {}, headers)

    def reopen_complaint(self, complaint_id, headers):
        return self._request("POST", f"/complaints/{complaint_id}/reopen", {}, headers)

    # --- CostReport ---
    def create_cost_report(self, storm_id, payload, headers):
        return self._request("POST", f"/storm-events/{storm_id}/cost-reports", payload, headers)

    def list_cost_reports(self, storm_id, headers, params=None):
        return self._request("GET", f"/storm-events/{storm_id}/cost-reports", headers=headers, params=params)

    # --- Test-driving: logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
