"""API client: one method per endpoint defined by the PRD."""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/redistricting"


class ApiClient(GenericApiClient):
    """Typed access to every endpoint in the PRD's endpoint table."""

    # ------------------------------------------------------------------
    # The logical clock
    # ------------------------------------------------------------------
    def set_current_utc(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # ------------------------------------------------------------------
    # Boundary studies
    # ------------------------------------------------------------------
    def create_study(self, payload, headers):
        return self._request("POST", f"{PREFIX}/studies", payload, headers)

    def get_study(self, study_id, headers):
        return self._request("GET", f"{PREFIX}/studies/{study_id}", headers=headers)

    def lock_study_data(self, study_id, headers):
        return self._request(
            "POST", f"{PREFIX}/studies/{study_id}/lock-data", headers=headers
        )

    def open_engagement(self, study_id, headers):
        return self._request(
            "POST", f"{PREFIX}/studies/{study_id}/open-engagement", headers=headers
        )

    # ------------------------------------------------------------------
    # Schools
    # ------------------------------------------------------------------
    def create_school(self, study_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/studies/{study_id}/schools", payload, headers
        )

    def list_study_schools(self, study_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/studies/{study_id}/schools", headers=headers, params=params
        )

    def get_school(self, school_id, headers):
        return self._request("GET", f"{PREFIX}/schools/{school_id}", headers=headers)

    def patch_school(self, school_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/schools/{school_id}", payload, headers)

    # ------------------------------------------------------------------
    # Planning areas and the adjacency graph
    # ------------------------------------------------------------------
    def create_planning_area(self, payload, headers):
        return self._request("POST", f"{PREFIX}/planning-areas", payload, headers)

    def list_planning_areas(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/planning-areas", headers=headers, params=params
        )

    def get_planning_area(self, area_id, headers):
        return self._request(
            "GET", f"{PREFIX}/planning-areas/{area_id}", headers=headers
        )

    def create_area_adjacency(self, payload, headers):
        return self._request("POST", f"{PREFIX}/area-adjacencies", payload, headers)

    def list_area_adjacencies(self, area_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/planning-areas/{area_id}/adjacencies",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Housing pipeline
    # ------------------------------------------------------------------
    def create_housing_development(self, area_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/planning-areas/{area_id}/housing-developments",
            payload,
            headers,
        )

    def list_housing_developments(self, area_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/planning-areas/{area_id}/housing-developments",
            headers=headers,
            params=params,
        )

    def get_housing_development(self, development_id, headers):
        return self._request(
            "GET", f"{PREFIX}/housing-developments/{development_id}", headers=headers
        )

    def advance_entitlement(self, development_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/housing-developments/{development_id}/entitlement-advance",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Projection runs
    # ------------------------------------------------------------------
    def create_projection_run(self, study_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/studies/{study_id}/projection-runs", payload, headers
        )

    def list_projection_runs(self, study_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/studies/{study_id}/projection-runs",
            headers=headers,
            params=params,
        )

    def get_projection_run(self, run_id, headers):
        return self._request(
            "GET", f"{PREFIX}/projection-runs/{run_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Scenarios
    # ------------------------------------------------------------------
    def create_scenario(self, payload, headers):
        return self._request("POST", f"{PREFIX}/scenarios", payload, headers)

    def list_scenarios(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/scenarios", headers=headers, params=params
        )

    def get_scenario(self, scenario_id, headers):
        return self._request("GET", f"{PREFIX}/scenarios/{scenario_id}", headers=headers)

    def get_impact_analysis(self, scenario_id, headers):
        return self._request(
            "GET", f"{PREFIX}/scenarios/{scenario_id}/impact-analysis", headers=headers
        )

    def replace_program_placements(self, scenario_id, payload, headers):
        return self._request(
            "PUT",
            f"{PREFIX}/scenarios/{scenario_id}/program-placements",
            payload,
            headers,
        )

    def submit_scenario_for_review(self, scenario_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/scenarios/{scenario_id}/submit-for-review",
            payload,
            headers,
        )

    def request_scenario_revision(self, scenario_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/scenarios/{scenario_id}/request-revision",
            payload,
            headers,
        )

    def advance_scenario_to_board(self, scenario_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/scenarios/{scenario_id}/advance-to-board", payload, headers
        )

    # ------------------------------------------------------------------
    # Area assignments
    # ------------------------------------------------------------------
    def create_assignment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/assignments", payload, headers)

    def list_assignments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/assignments", headers=headers, params=params
        )

    def get_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/assignments/{assignment_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Public comment
    # ------------------------------------------------------------------
    def create_comment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/comments", payload, headers)

    def list_comments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/comments", headers=headers, params=params)

    def get_comment(self, comment_id, headers):
        return self._request("GET", f"{PREFIX}/comments/{comment_id}", headers=headers)

    def triage_comment(self, comment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/comments/{comment_id}/triage", payload, headers
        )

    def dismiss_comment(self, comment_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/comments/{comment_id}/dismiss", payload, headers
        )

    # ------------------------------------------------------------------
    # Adoption records
    # ------------------------------------------------------------------
    def create_adoption(self, payload, headers):
        return self._request("POST", f"{PREFIX}/adoptions", payload, headers)

    def list_adoptions(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/adoptions", headers=headers, params=params
        )

    def get_adoption(self, adoption_id, headers):
        return self._request("GET", f"{PREFIX}/adoptions/{adoption_id}", headers=headers)

    def create_phase_in_rule(self, adoption_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/adoptions/{adoption_id}/phase-in-rules", payload, headers
        )

    def list_phase_in_rules(self, adoption_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/adoptions/{adoption_id}/phase-in-rules",
            headers=headers,
            params=params,
        )

    def activate_adoption(self, adoption_id, headers):
        return self._request(
            "POST", f"{PREFIX}/adoptions/{adoption_id}/activate", headers=headers
        )

    def rescind_adoption(self, adoption_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/adoptions/{adoption_id}/rescind", payload, headers
        )

    def close_transfer_window(self, adoption_id, headers):
        return self._request(
            "POST",
            f"{PREFIX}/adoptions/{adoption_id}/close-transfer-window",
            headers=headers,
        )

    def close_monitoring(self, adoption_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/adoptions/{adoption_id}/close-monitoring",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Transfer requests
    # ------------------------------------------------------------------
    def create_transfer_request(self, payload, headers):
        return self._request("POST", f"{PREFIX}/transfer-requests", payload, headers)

    def list_transfer_requests(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/transfer-requests", headers=headers, params=params
        )

    def get_transfer_request(self, request_id, headers):
        return self._request(
            "GET", f"{PREFIX}/transfer-requests/{request_id}", headers=headers
        )

    def decide_transfer_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/transfer-requests/{request_id}/decide", payload, headers
        )

    # ------------------------------------------------------------------
    # Variance monitoring
    # ------------------------------------------------------------------
    def create_variance_observation(self, adoption_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/adoptions/{adoption_id}/variance-observations",
            payload,
            headers,
        )

    def list_variance_observations(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/variance-observations", headers=headers, params=params
        )

    def get_variance_observation(self, observation_id, headers):
        return self._request(
            "GET", f"{PREFIX}/variance-observations/{observation_id}", headers=headers
        )


api_client = ApiClient()
