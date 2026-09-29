"""One method per route the PRD publishes under the /water-treatment prefix."""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX


class ApiClient(GenericApiClient):
    """Thin, typed wrapper over the routes in the PRD endpoint table."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------

    def set_clock(self, now: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/_clock/set_current_utc", {"now": now}, headers
        )

    # ------------------------------------------------------------------
    # Catalogs
    # ------------------------------------------------------------------

    def create_process_technology(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/process-technologies", payload, headers
        )

    def list_process_technologies(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/process-technologies", params, headers
        )

    def get_process_technology(
        self, technology_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/process-technologies/{technology_id}", None, headers
        )

    def create_material_spec(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/material-specs", payload, headers)

    def list_material_specs(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/material-specs", params, headers)

    def get_material_spec(
        self, material_spec_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/material-specs/{material_spec_id}", None, headers
        )

    def create_test_bay(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/test-bays", payload, headers)

    def list_test_bays(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/test-bays", params, headers)

    def get_test_bay(self, bay_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/test-bays/{bay_id}", None, headers)

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------

    def create_project(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/projects", payload, headers)

    def list_projects(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/projects", params, headers)

    def get_project(self, project_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/projects/{project_id}", None, headers)

    # ------------------------------------------------------------------
    # Influent profiles
    # ------------------------------------------------------------------

    def create_influent_profile(
        self, project_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/projects/{project_id}/influent-profiles",
            payload,
            headers,
        )

    def list_project_influent_profiles(
        self,
        project_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/projects/{project_id}/influent-profiles",
            params,
            headers,
        )

    def list_influent_profiles(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/influent-profiles", params, headers)

    def get_influent_profile(
        self, profile_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/influent-profiles/{profile_id}", None, headers
        )

    def decide_influent_profile_qa(
        self, profile_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/influent-profiles/{profile_id}/qa-decision",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Treatment objectives and process selection
    # ------------------------------------------------------------------

    def create_treatment_objective(
        self, project_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/projects/{project_id}/treatment-objectives",
            payload,
            headers,
        )

    def list_project_treatment_objectives(
        self,
        project_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/projects/{project_id}/treatment-objectives",
            params,
            headers,
        )

    def list_treatment_objectives(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/treatment-objectives", params, headers
        )

    def get_treatment_objective(
        self, objective_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/treatment-objectives/{objective_id}", None, headers
        )

    def run_process_selection(
        self, project_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/projects/{project_id}/process-selection", {}, headers
        )

    # ------------------------------------------------------------------
    # Treatment stages
    # ------------------------------------------------------------------

    def list_treatment_stages(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/treatment-stages", params, headers)

    def get_treatment_stage(
        self, stage_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/treatment-stages/{stage_id}", None, headers
        )

    # ------------------------------------------------------------------
    # Equipment packages
    # ------------------------------------------------------------------

    def create_equipment_package(
        self, stage_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/treatment-stages/{stage_id}/equipment-packages",
            payload,
            headers,
        )

    def update_equipment_package(
        self, package_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "PATCH", f"{API_PREFIX}/equipment-packages/{package_id}", payload, headers
        )

    def list_equipment_packages(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/equipment-packages", params, headers)

    def get_equipment_package(
        self, package_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/equipment-packages/{package_id}", None, headers
        )

    def submit_package_for_review(
        self,
        package_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/equipment-packages/{package_id}/submit-for-review",
            payload or {},
            headers,
        )

    def decide_package_review(
        self, package_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/equipment-packages/{package_id}/review-decision",
            payload,
            headers,
        )

    def release_package_for_fabrication(
        self,
        package_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/equipment-packages/{package_id}/release-for-fabrication",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # Skids and FAT runs
    # ------------------------------------------------------------------

    def list_skids(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/skids", params, headers)

    def get_skid(self, skid_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/skids/{skid_id}", None, headers)

    def record_skid_milestone(
        self, skid_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/skids/{skid_id}/milestones", payload, headers
        )

    def create_fat_run(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/fat-runs", payload, headers)

    def list_fat_runs(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/fat-runs", params, headers)

    def get_fat_run(self, run_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/fat-runs/{run_id}", None, headers)

    def witness_fat_run(
        self, run_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/fat-runs/{run_id}/witness-result", payload, headers
        )

    def cancel_fat_run(
        self,
        run_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/fat-runs/{run_id}/cancel", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Or-Equal submittals and spec deviations
    # ------------------------------------------------------------------

    def create_or_equal_submittal(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/or-equal-submittals", payload, headers
        )

    def list_or_equal_submittals(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/or-equal-submittals", params, headers
        )

    def get_or_equal_submittal(
        self, submittal_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/or-equal-submittals/{submittal_id}", None, headers
        )

    def create_spec_deviation(
        self, submittal_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/or-equal-submittals/{submittal_id}/spec-deviations",
            payload,
            headers,
        )

    def list_submittal_spec_deviations(
        self,
        submittal_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/or-equal-submittals/{submittal_id}/spec-deviations",
            params,
            headers,
        )

    def list_spec_deviations(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/spec-deviations", params, headers)

    def get_spec_deviation(
        self, deviation_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/spec-deviations/{deviation_id}", None, headers
        )

    def disposition_spec_deviation(
        self, deviation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/spec-deviations/{deviation_id}/disposition",
            payload,
            headers,
        )

    def submit_or_equal_submittal(
        self,
        submittal_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/or-equal-submittals/{submittal_id}/submit",
            payload or {},
            headers,
        )

    def decide_or_equal_submittal(
        self, submittal_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/or-equal-submittals/{submittal_id}/engineer-decision",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Bidding and award
    # ------------------------------------------------------------------

    def submit_bid(
        self, project_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/projects/{project_id}/bid", payload, headers
        )

    def decide_award(
        self, project_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/projects/{project_id}/award", payload, headers
        )

    # ------------------------------------------------------------------
    # Commissioning
    # ------------------------------------------------------------------

    def create_performance_demo(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/performance-demos", payload, headers
        )

    def list_performance_demos(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/performance-demos", params, headers)

    def get_performance_demo(
        self, demo_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/performance-demos/{demo_id}", None, headers
        )

    def certify_performance_demo(
        self, demo_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/performance-demos/{demo_id}/certify",
            payload,
            headers,
        )

    def accept_deliverable(
        self, project_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/projects/{project_id}/deliverable-acceptance",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Service agreements and consumable draws
    # ------------------------------------------------------------------

    def create_service_agreement(
        self, project_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/projects/{project_id}/service-agreements",
            payload,
            headers,
        )

    def list_project_service_agreements(
        self,
        project_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/projects/{project_id}/service-agreements",
            params,
            headers,
        )

    def list_service_agreements(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/service-agreements", params, headers)

    def get_service_agreement(
        self, agreement_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/service-agreements/{agreement_id}", None, headers
        )

    def create_consumable_draw(
        self, agreement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/service-agreements/{agreement_id}/consumable-draws",
            payload,
            headers,
        )

    def list_consumable_draws(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/consumable-draws", params, headers)

    def get_consumable_draw(
        self, draw_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/consumable-draws/{draw_id}", None, headers
        )

    def reverse_consumable_draw(
        self,
        draw_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/consumable-draws/{draw_id}/reversal",
            payload or {},
            headers,
        )


api_client = ApiClient()
