"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/signal-ops"


class ApiClient(GenericApiClient):
    # ---------------- Logical clock ----------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def set_clock_raw(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---------------- Intersections ----------------
    def create_intersection(self, payload, headers):
        return self._request("POST", f"{PREFIX}/intersections", payload, headers)

    def list_intersections(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/intersections", headers=headers, params=params)

    def get_intersection(self, intersection_id, headers):
        return self._request(
            "GET", f"{PREFIX}/intersections/{intersection_id}", headers=headers
        )

    def update_intersection(self, intersection_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/intersections/{intersection_id}", payload, headers
        )

    def list_intersection_corridor_memberships(self, intersection_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/intersections/{intersection_id}/corridor-memberships",
            headers=headers,
            params=params,
        )

    def list_intersection_timing_plans(self, intersection_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/intersections/{intersection_id}/timing-plans",
            headers=headers,
            params=params,
        )

    def list_intersection_priority_configs(self, intersection_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/intersections/{intersection_id}/priority-configs",
            headers=headers,
            params=params,
        )

    def list_intersection_field_observations(self, intersection_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/intersections/{intersection_id}/field-observations",
            headers=headers,
            params=params,
        )

    def list_intersection_turning_movement_counts(self, intersection_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/intersections/{intersection_id}/turning-movement-counts",
            headers=headers,
            params=params,
        )

    def create_turning_movement_count(self, intersection_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/intersections/{intersection_id}/turning-movement-counts",
            payload,
            headers,
        )

    # ---------------- Corridors ----------------
    def create_corridor(self, payload, headers):
        return self._request("POST", f"{PREFIX}/corridors", payload, headers)

    def list_corridors(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/corridors", headers=headers, params=params)

    def get_corridor(self, corridor_id, headers):
        return self._request("GET", f"{PREFIX}/corridors/{corridor_id}", headers=headers)

    def create_corridor_member(self, corridor_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/corridors/{corridor_id}/members", payload, headers
        )

    def list_corridor_members(self, corridor_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/corridors/{corridor_id}/members", headers=headers, params=params
        )

    def list_corridor_retiming_projects(self, corridor_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/corridors/{corridor_id}/retiming-projects",
            headers=headers,
            params=params,
        )

    def list_corridor_complaints(self, corridor_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/corridors/{corridor_id}/complaints",
            headers=headers,
            params=params,
        )

    def screen_corridor(self, corridor_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/corridors/{corridor_id}/screen", payload or {}, headers
        )

    def corridor_selection_decision(self, corridor_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/corridors/{corridor_id}/selection-decision", payload, headers
        )

    # ---------------- Requesters & complaints ----------------
    def create_requester(self, payload, headers):
        return self._request("POST", f"{PREFIX}/requesters", payload, headers)

    def get_requester(self, requester_id, headers):
        return self._request("GET", f"{PREFIX}/requesters/{requester_id}", headers=headers)

    def list_requester_complaints(self, requester_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/requesters/{requester_id}/complaints",
            headers=headers,
            params=params,
        )

    def create_complaint(self, payload, headers):
        return self._request("POST", f"{PREFIX}/complaints", payload, headers)

    def triage_complaint(self, complaint_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/complaints/{complaint_id}/triage", payload, headers
        )

    def link_complaint(self, complaint_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/complaints/{complaint_id}/link", payload, headers
        )

    def resolve_complaint(self, complaint_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/complaints/{complaint_id}/resolve", payload or {}, headers
        )

    def reopen_complaint(self, complaint_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/complaints/{complaint_id}/reopen", payload or {}, headers
        )

    # ---------------- Retiming projects ----------------
    def create_retiming_project(self, payload, headers):
        return self._request("POST", f"{PREFIX}/retiming-projects", payload, headers)

    def get_retiming_project(self, project_id, headers):
        return self._request(
            "GET", f"{PREFIX}/retiming-projects/{project_id}", headers=headers
        )

    def list_project_turning_movement_counts(self, project_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/retiming-projects/{project_id}/turning-movement-counts",
            headers=headers,
            params=params,
        )

    def create_travel_time_run(self, project_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/retiming-projects/{project_id}/travel-time-runs", payload, headers
        )

    def list_project_travel_time_runs(self, project_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/retiming-projects/{project_id}/travel-time-runs",
            headers=headers,
            params=params,
        )

    def list_project_timing_plans(self, project_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/retiming-projects/{project_id}/timing-plans",
            headers=headers,
            params=params,
        )

    def list_project_field_observations(self, project_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/retiming-projects/{project_id}/field-observations",
            headers=headers,
            params=params,
        )

    def list_project_complaints(self, project_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/retiming-projects/{project_id}/complaints",
            headers=headers,
            params=params,
        )

    def list_project_performance_evaluations(self, project_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/retiming-projects/{project_id}/performance-evaluations",
            headers=headers,
            params=params,
        )

    def create_performance_evaluation(self, project_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/retiming-projects/{project_id}/performance-evaluations",
            payload,
            headers,
        )

    def advance_project(self, project_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/retiming-projects/{project_id}/advance", payload or {}, headers
        )

    def coordinate_project(self, project_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/retiming-projects/{project_id}/coordinate", payload or {}, headers
        )

    def implement_project(self, project_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/retiming-projects/{project_id}/implement", payload or {}, headers
        )

    def project_field_tuning(self, project_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/retiming-projects/{project_id}/field-tuning", payload, headers
        )

    def close_project(self, project_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/retiming-projects/{project_id}/close", payload, headers
        )

    # ---------------- Timing plans, splits, ped checks ----------------
    def create_timing_plan(self, payload, headers):
        return self._request("POST", f"{PREFIX}/timing-plans", payload, headers)

    def get_timing_plan(self, plan_id, headers):
        return self._request("GET", f"{PREFIX}/timing-plans/{plan_id}", headers=headers)

    def create_phase_split(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/timing-plans/{plan_id}/phase-splits", payload, headers
        )

    def list_phase_splits(self, plan_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/timing-plans/{plan_id}/phase-splits", headers=headers, params=params
        )

    def update_phase_split(self, phase_split_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/phase-splits/{phase_split_id}", payload, headers
        )

    def list_pedestrian_checks(self, plan_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/timing-plans/{plan_id}/pedestrian-checks",
            headers=headers,
            params=params,
        )

    def submit_timing_plan(self, plan_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/timing-plans/{plan_id}/submit", payload or {}, headers
        )

    def certify_timing_plan(self, plan_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/timing-plans/{plan_id}/certify", payload or {}, headers
        )

    def return_timing_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/timing-plans/{plan_id}/return", payload, headers
        )

    def waive_pedestrian_check(self, check_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/pedestrian-checks/{check_id}/waive", payload, headers
        )

    # ---------------- Priority configurations ----------------
    def create_priority_config(self, payload, headers):
        return self._request("POST", f"{PREFIX}/priority-configs", payload, headers)

    def approve_priority_config(self, config_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/priority-configs/{config_id}/approve", payload, headers
        )

    def deploy_priority_config(self, config_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/priority-configs/{config_id}/deploy", payload or {}, headers
        )

    def suspend_priority_config(self, config_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/priority-configs/{config_id}/suspend", payload or {}, headers
        )

    # ---------------- Field observations ----------------
    def create_field_observation(self, payload, headers):
        return self._request("POST", f"{PREFIX}/field-observations", payload, headers)

    def update_field_observation(self, observation_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/field-observations/{observation_id}", payload, headers
        )

    # ---------------- Performance evaluations ----------------
    def certify_performance_evaluation(self, evaluation_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/performance-evaluations/{evaluation_id}/certify",
            payload or {},
            headers,
        )


api_client = ApiClient()
