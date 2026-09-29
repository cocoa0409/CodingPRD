"""Typed client with one method per endpoint of the DR Failover Exercise API."""

from typing import Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """One method per endpoint; every method returns the raw response."""

    # --- Stakeholders --------------------------------------------------------

    def create_stakeholder(self, payload: dict, headers: dict) -> requests.Response:
        return self.post("/stakeholders", json=payload, headers=headers)

    def patch_stakeholder(
        self, stakeholder_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "PATCH", f"/stakeholders/{stakeholder_id}", payload=payload, headers=headers
        )

    def get_stakeholder(self, stakeholder_id: str, headers: dict) -> requests.Response:
        return self.get(f"/stakeholders/{stakeholder_id}", headers=headers)

    def list_stakeholders(
        self, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self.get("/stakeholders", headers=headers, params=params)

    # --- Sites ---------------------------------------------------------------

    def create_site(self, payload: dict, headers: dict) -> requests.Response:
        return self.post("/sites", json=payload, headers=headers)

    def get_site(self, site_id: str, headers: dict) -> requests.Response:
        return self.get(f"/sites/{site_id}", headers=headers)

    def list_sites(self, headers: dict, params: Optional[dict] = None) -> requests.Response:
        return self.get("/sites", headers=headers, params=params)

    # --- Applications --------------------------------------------------------

    def create_application(self, payload: dict, headers: dict) -> requests.Response:
        return self.post("/applications", json=payload, headers=headers)

    def get_application(self, application_id: str, headers: dict) -> requests.Response:
        return self.get(f"/applications/{application_id}", headers=headers)

    def list_applications(
        self, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self.get("/applications", headers=headers, params=params)

    def propose_application_tier(
        self, application_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self.post(
            f"/applications/{application_id}/tier-proposals", json=payload, headers=headers
        )

    def decide_application_tier(
        self, application_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self.post(
            f"/applications/{application_id}/tier-decisions", json=payload, headers=headers
        )

    def assign_application_to_group(
        self, application_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self.post(
            f"/applications/{application_id}/group-assignments", json=payload, headers=headers
        )

    # --- Assets --------------------------------------------------------------

    def create_asset(self, payload: dict, headers: dict) -> requests.Response:
        return self.post("/assets", json=payload, headers=headers)

    def get_asset(self, asset_id: str, headers: dict) -> requests.Response:
        return self.get(f"/assets/{asset_id}", headers=headers)

    def list_assets(self, headers: dict, params: Optional[dict] = None) -> requests.Response:
        return self.get("/assets", headers=headers, params=params)

    def assign_asset_to_group(
        self, asset_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self.post(
            f"/assets/{asset_id}/group-assignments", json=payload, headers=headers
        )

    def create_replication_observation(
        self, asset_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self.post(
            f"/assets/{asset_id}/replication-observations", json=payload, headers=headers
        )

    def list_replication_observations(
        self, asset_id: str, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self.get(
            f"/assets/{asset_id}/replication-observations", headers=headers, params=params
        )

    # --- Dependency edges ----------------------------------------------------

    def create_dependency_edge(self, payload: dict, headers: dict) -> requests.Response:
        return self.post("/dependency-edges", json=payload, headers=headers)

    def get_dependency_edge(self, edge_id: str, headers: dict) -> requests.Response:
        return self.get(f"/dependency-edges/{edge_id}", headers=headers)

    def list_dependency_edges(
        self, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self.get("/dependency-edges", headers=headers, params=params)

    # --- Recovery groups -----------------------------------------------------

    def create_recovery_group(self, payload: dict, headers: dict) -> requests.Response:
        return self.post("/recovery-groups", json=payload, headers=headers)

    def get_recovery_group(self, group_id: str, headers: dict) -> requests.Response:
        return self.get(f"/recovery-groups/{group_id}", headers=headers)

    def list_recovery_groups(
        self, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self.get("/recovery-groups", headers=headers, params=params)

    def set_change_freeze(
        self, group_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self.post(
            f"/recovery-groups/{group_id}/change-freeze", json=payload, headers=headers
        )

    def refresh_posture(
        self, group_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        return self.post(
            f"/recovery-groups/{group_id}/posture-refresh",
            json=payload if payload is not None else {},
            headers=headers,
        )

    # --- Runbooks ------------------------------------------------------------

    def create_runbook(self, payload: dict, headers: dict) -> requests.Response:
        return self.post("/runbooks", json=payload, headers=headers)

    def get_runbook(self, runbook_id: str, headers: dict) -> requests.Response:
        return self.get(f"/runbooks/{runbook_id}", headers=headers)

    def list_runbooks(self, headers: dict, params: Optional[dict] = None) -> requests.Response:
        return self.get("/runbooks", headers=headers, params=params)

    def transition_runbook(
        self, runbook_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self.post(f"/runbooks/{runbook_id}/transitions", json=payload, headers=headers)

    # --- Runbook steps -------------------------------------------------------

    def create_runbook_step(self, payload: dict, headers: dict) -> requests.Response:
        return self.post("/runbook-steps", json=payload, headers=headers)

    def get_runbook_step(self, step_id: str, headers: dict) -> requests.Response:
        return self.get(f"/runbook-steps/{step_id}", headers=headers)

    def list_runbook_steps(
        self, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self.get("/runbook-steps", headers=headers, params=params)

    def validate_runbook_step(
        self, step_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self.post(f"/runbook-steps/{step_id}/validations", json=payload, headers=headers)

    # --- Exercises -----------------------------------------------------------

    def create_exercise(self, payload: dict, headers: dict) -> requests.Response:
        return self.post("/exercises", json=payload, headers=headers)

    def get_exercise(self, exercise_id: str, headers: dict) -> requests.Response:
        return self.get(f"/exercises/{exercise_id}", headers=headers)

    def list_exercises(
        self, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self.get("/exercises", headers=headers, params=params)

    def create_scope_item(
        self, exercise_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self.post(f"/exercises/{exercise_id}/scope-items", json=payload, headers=headers)

    def get_scope_item(self, scope_item_id: str, headers: dict) -> requests.Response:
        return self.get(f"/exercise-scope-items/{scope_item_id}", headers=headers)

    def list_scope_items(
        self, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self.get("/exercise-scope-items", headers=headers, params=params)

    def submit_impact(
        self, exercise_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self.post(
            f"/exercises/{exercise_id}/impact-submissions", json=payload, headers=headers
        )

    def decide_impact(
        self, exercise_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self.post(
            f"/exercises/{exercise_id}/impact-decisions", json=payload, headers=headers
        )

    def schedule_exercise(
        self, exercise_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self.post(f"/exercises/{exercise_id}/schedule", json=payload, headers=headers)

    def transition_execution(
        self, exercise_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self.post(
            f"/exercises/{exercise_id}/execution-transitions", json=payload, headers=headers
        )

    def create_step_execution(
        self, exercise_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self.post(
            f"/exercises/{exercise_id}/step-executions", json=payload, headers=headers
        )

    def get_step_execution(self, step_execution_id: str, headers: dict) -> requests.Response:
        return self.get(f"/step-executions/{step_execution_id}", headers=headers)

    def list_step_executions(
        self, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self.get("/step-executions", headers=headers, params=params)

    def transition_data(
        self, exercise_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self.post(
            f"/exercises/{exercise_id}/data-transitions", json=payload, headers=headers
        )

    def transition_failback(
        self, exercise_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self.post(
            f"/exercises/{exercise_id}/failback-transitions", json=payload, headers=headers
        )

    # --- Findings ------------------------------------------------------------

    def create_finding(self, payload: dict, headers: dict) -> requests.Response:
        return self.post("/findings", json=payload, headers=headers)

    def get_finding(self, finding_id: str, headers: dict) -> requests.Response:
        return self.get(f"/findings/{finding_id}", headers=headers)

    def list_findings(self, headers: dict, params: Optional[dict] = None) -> requests.Response:
        return self.get("/findings", headers=headers, params=params)

    def transition_finding(
        self, finding_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self.post(f"/findings/{finding_id}/transitions", json=payload, headers=headers)

    # --- Evidence packages ---------------------------------------------------

    def create_evidence_package(self, payload: dict, headers: dict) -> requests.Response:
        return self.post("/evidence-packages", json=payload, headers=headers)

    def get_evidence_package(self, package_id: str, headers: dict) -> requests.Response:
        return self.get(f"/evidence-packages/{package_id}", headers=headers)

    def list_evidence_packages(
        self, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self.get("/evidence-packages", headers=headers, params=params)

    def transition_evidence_package(
        self, package_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self.post(
            f"/evidence-packages/{package_id}/transitions", json=payload, headers=headers
        )

    # --- Logical clock -------------------------------------------------------

    def set_clock(self, payload: dict, headers: dict) -> requests.Response:
        return self.post("/_clock/set_current_utc", json=payload, headers=headers)
