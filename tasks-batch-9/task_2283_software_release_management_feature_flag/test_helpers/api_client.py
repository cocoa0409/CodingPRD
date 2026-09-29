"""Typed endpoint client for the Release Management & Feature Flag Governance API.

One method per row of the PRD §4 endpoint table.  Every path is mounted at the
API root; there is no shared prefix.  All methods return the raw
``requests.Response`` so tests can assert status codes themselves.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint surface of the API under test."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------

    def set_clock(self, to_iso8601: str, headers: Dict[str, str]) -> requests.Response:
        """Reposition the logical clock; the response reports ``current_utc``."""
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ------------------------------------------------------------------
    # Environments
    # ------------------------------------------------------------------

    def create_environment(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", "/environments", payload, headers)

    def get_environment(self, environment_id: str, headers) -> requests.Response:
        return self._request("GET", f"/environments/{environment_id}", None, headers)

    # ------------------------------------------------------------------
    # Release trains
    # ------------------------------------------------------------------

    def create_release_train(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", "/release-trains", payload, headers)

    def get_release_train(self, train_id: str, headers) -> requests.Response:
        return self._request("GET", f"/release-trains/{train_id}", None, headers)

    def set_train_freeze_state(
        self, train_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/release-trains/{train_id}/freeze-state", payload, headers
        )

    def create_release(
        self, train_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/release-trains/{train_id}/releases", payload, headers
        )

    def list_train_releases(
        self, train_id: str, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/release-trains/{train_id}/releases", params, headers
        )

    # ------------------------------------------------------------------
    # Releases
    # ------------------------------------------------------------------

    def get_release(self, release_id: str, headers) -> requests.Response:
        return self._request("GET", f"/releases/{release_id}", None, headers)

    def cut_release(
        self, release_id: str, payload: Optional[Dict[str, Any]], headers
    ) -> requests.Response:
        return self._request("POST", f"/releases/{release_id}/cut", payload or {}, headers)

    def ship_release(
        self, release_id: str, payload: Optional[Dict[str, Any]], headers
    ) -> requests.Response:
        """POST /releases/{id}/release -- declare a stabilized release shipped."""
        return self._request(
            "POST", f"/releases/{release_id}/release", payload or {}, headers
        )

    def create_freeze_exception(
        self, release_id: str, payload: Optional[Dict[str, Any]], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/releases/{release_id}/freeze-exceptions", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Change requests
    # ------------------------------------------------------------------

    def create_change_request(
        self, release_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/releases/{release_id}/change-requests", payload, headers
        )

    def list_release_change_requests(
        self, release_id: str, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/releases/{release_id}/change-requests", params, headers
        )

    def get_change_request(self, change_id: str, headers) -> requests.Response:
        return self._request("GET", f"/change-requests/{change_id}", None, headers)

    def submit_change_request(
        self, change_id: str, payload: Optional[Dict[str, Any]], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/change-requests/{change_id}/submit", payload or {}, headers
        )

    def create_dependency(
        self, change_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/change-requests/{change_id}/dependencies", payload, headers
        )

    def list_dependencies(
        self, change_id: str, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/change-requests/{change_id}/dependencies", params, headers
        )

    def create_flag_link(
        self, change_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/change-requests/{change_id}/flag-links", payload, headers
        )

    def list_change_flag_links(
        self, change_id: str, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/change-requests/{change_id}/flag-links", params, headers
        )

    def create_approval(
        self, change_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/change-requests/{change_id}/approvals", payload, headers
        )

    def list_approvals(
        self, change_id: str, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/change-requests/{change_id}/approvals", params, headers
        )

    def merge_change_request(
        self, change_id: str, payload: Optional[Dict[str, Any]], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/change-requests/{change_id}/merge", payload or {}, headers
        )

    def withdraw_change_request(
        self, change_id: str, payload: Optional[Dict[str, Any]], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/change-requests/{change_id}/withdraw", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Feature flags
    # ------------------------------------------------------------------

    def create_feature_flag(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", "/feature-flags", payload, headers)

    def get_feature_flag(self, flag_id: str, headers) -> requests.Response:
        return self._request("GET", f"/feature-flags/{flag_id}", None, headers)

    def list_feature_flags(
        self, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/feature-flags", params, headers)

    def list_flag_change_links(
        self, flag_id: str, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/feature-flags/{flag_id}/change-links", params, headers
        )

    def create_rollout_step(
        self, flag_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/feature-flags/{flag_id}/rollout-steps", payload, headers
        )

    def pause_flag(
        self, flag_id: str, payload: Optional[Dict[str, Any]], headers
    ) -> requests.Response:
        return self._request("POST", f"/feature-flags/{flag_id}/pause", payload or {}, headers)

    def resume_flag(
        self, flag_id: str, payload: Optional[Dict[str, Any]], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/feature-flags/{flag_id}/resume", payload or {}, headers
        )

    def archive_flag(
        self, flag_id: str, payload: Optional[Dict[str, Any]], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/feature-flags/{flag_id}/archive", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Rollout steps
    # ------------------------------------------------------------------

    def get_rollout_step(self, step_id: str, headers) -> requests.Response:
        return self._request("GET", f"/flag-rollout-steps/{step_id}", None, headers)

    def list_rollout_steps(
        self, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/flag-rollout-steps", params, headers)

    def start_soak(
        self, step_id: str, payload: Optional[Dict[str, Any]], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/flag-rollout-steps/{step_id}/start-soak", payload or {}, headers
        )

    def apply_step(
        self, step_id: str, payload: Optional[Dict[str, Any]], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/flag-rollout-steps/{step_id}/apply", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Cleanup sweeps
    # ------------------------------------------------------------------

    def create_cleanup_sweep(
        self, payload: Optional[Dict[str, Any]], headers
    ) -> requests.Response:
        return self._request("POST", "/flag-cleanup-sweeps", payload or {}, headers)

    # ------------------------------------------------------------------
    # Deployments
    # ------------------------------------------------------------------

    def create_deployment(
        self, release_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/releases/{release_id}/deployments", payload, headers
        )

    def get_deployment(self, deployment_id: str, headers) -> requests.Response:
        return self._request("GET", f"/deployments/{deployment_id}", None, headers)

    def list_deployments(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/deployments", params, headers)

    def start_deployment(
        self, deployment_id: str, payload: Optional[Dict[str, Any]], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/deployments/{deployment_id}/start", payload or {}, headers
        )

    def create_health_signal(
        self, deployment_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/deployments/{deployment_id}/health-signals", payload, headers
        )

    def list_health_signals(
        self, deployment_id: str, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/deployments/{deployment_id}/health-signals", params, headers
        )

    def create_canary_evaluation(
        self, deployment_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/deployments/{deployment_id}/canary-evaluations", payload, headers
        )

    def list_canary_evaluations(
        self, deployment_id: str, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/deployments/{deployment_id}/canary-evaluations", params, headers
        )

    def complete_deployment(
        self, deployment_id: str, payload: Optional[Dict[str, Any]], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/deployments/{deployment_id}/complete", payload or {}, headers
        )

    def rollback_deployment(
        self, deployment_id: str, payload: Optional[Dict[str, Any]], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/deployments/{deployment_id}/rollback", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Incidents
    # ------------------------------------------------------------------

    def create_incident(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", "/incidents", payload, headers)

    def get_incident(self, incident_id: str, headers) -> requests.Response:
        return self._request("GET", f"/incidents/{incident_id}", None, headers)

    def list_incidents(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/incidents", params, headers)

    def decide_incident(
        self, incident_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request("POST", f"/incidents/{incident_id}/decide", payload, headers)

    # ------------------------------------------------------------------
    # Release notes
    # ------------------------------------------------------------------

    def create_release_notes(
        self, release_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/releases/{release_id}/release-notes", payload, headers
        )

    def list_release_notes(
        self, release_id: str, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/releases/{release_id}/release-notes", params, headers
        )

    def publish_release_notes(
        self, note_id: str, payload: Optional[Dict[str, Any]], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/release-notes/{note_id}/publish", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Evidence packets
    # ------------------------------------------------------------------

    def create_evidence_packet(
        self, release_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/releases/{release_id}/evidence-packets", payload, headers
        )

    def list_evidence_packets(
        self, release_id: str, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/releases/{release_id}/evidence-packets", params, headers
        )

    def create_waiver(
        self, packet_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/evidence-packets/{packet_id}/waivers", payload, headers
        )

    def seal_evidence_packet(
        self, packet_id: str, payload: Optional[Dict[str, Any]], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/evidence-packets/{packet_id}/seal", payload or {}, headers
        )
