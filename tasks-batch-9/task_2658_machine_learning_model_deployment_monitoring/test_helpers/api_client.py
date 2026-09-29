"""One method per endpoint of the model deployment and monitoring service.

Paths follow PRD §4 exactly: there is no shared API prefix, and only three
routes are nested under a parent (challenger-evaluation scheduling under a
registry entry, and the two computed reads under a deployment).
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """HTTP client covering every endpoint declared in PRD §4."""

    # ─── Registry entries ───

    def create_model(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/models", payload, headers)

    def get_model(self, model_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/models/{model_id}", None, headers)

    def list_models(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/models", params, headers)

    def archive_model(self, model_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/models/{model_id}/archive", {}, headers)

    def schedule_challenger_evaluation(
        self, model_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/models/{model_id}/challenger-evaluations", payload, headers
        )

    # ─── Training-data snapshots ───

    def create_training_dataset(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/training-datasets", payload, headers)

    def get_training_dataset(
        self, dataset_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/training-datasets/{dataset_id}", None, headers)

    def list_training_datasets(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/training-datasets", params, headers)

    def submit_training_dataset(
        self, dataset_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/training-datasets/{dataset_id}/submit", {}, headers
        )

    def decide_training_dataset(
        self, dataset_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/training-datasets/{dataset_id}/decision", payload, headers
        )

    def revoke_training_dataset(
        self, dataset_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/training-datasets/{dataset_id}/revoke", payload, headers
        )

    # ─── Artifact versions ───

    def create_model_version(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/model-versions", payload, headers)

    def get_model_version(
        self, version_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/model-versions/{version_id}", None, headers)

    def list_model_versions(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/model-versions", params, headers)

    def update_version_documentation(
        self, version_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "PATCH", f"/model-versions/{version_id}/documentation", payload, headers
        )

    def submit_version_for_review(
        self, version_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/model-versions/{version_id}/submit-for-review", {}, headers
        )

    def decide_model_version(
        self, version_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/model-versions/{version_id}/decision", payload, headers
        )

    def deprecate_model_version(
        self, version_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/model-versions/{version_id}/deprecate", {}, headers
        )

    # ─── Serving clusters ───

    def create_serving_endpoint(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/serving-endpoints", payload, headers)

    def get_serving_endpoint(
        self, serving_endpoint_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"/serving-endpoints/{serving_endpoint_id}", None, headers
        )

    def list_serving_endpoints(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/serving-endpoints", params, headers)

    def set_operational_state(
        self,
        serving_endpoint_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/serving-endpoints/{serving_endpoint_id}/operational-state",
            payload,
            headers,
        )

    # ─── Deployments ───

    def create_deployment(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/deployments", payload, headers)

    def get_deployment(
        self, deployment_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/deployments/{deployment_id}", None, headers)

    def list_deployments(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/deployments", params, headers)

    def ramp_deployment(
        self, deployment_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/deployments/{deployment_id}/ramp", {}, headers)

    def rollout_action(
        self, deployment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/deployments/{deployment_id}/rollout-action", payload, headers
        )

    def list_deployment_ramp_steps(
        self,
        deployment_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/deployments/{deployment_id}/ramp-steps", params, headers
        )

    def get_deployment_health(
        self,
        deployment_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/deployments/{deployment_id}/health", params, headers
        )

    # ─── Traffic-ramp ledger ───

    def get_traffic_ramp_step(
        self, ramp_step_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"/traffic-ramp-steps/{ramp_step_id}", None, headers
        )

    def list_traffic_ramp_steps(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/traffic-ramp-steps", params, headers)

    # ─── Observation windows ───

    def create_monitoring_window(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/monitoring-windows", payload, headers)

    def get_monitoring_window(
        self, window_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/monitoring-windows/{window_id}", None, headers)

    def list_monitoring_windows(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/monitoring-windows", params, headers)

    def close_monitoring_window(
        self, window_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/monitoring-windows/{window_id}/close", {}, headers
        )

    # ─── Drift reports ───

    def create_drift_report(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/drift-reports", payload, headers)

    def get_drift_report(
        self, drift_report_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/drift-reports/{drift_report_id}", None, headers)

    def list_drift_reports(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/drift-reports", params, headers)

    # ─── Skew checks ───

    def create_skew_check(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/skew-checks", payload, headers)

    def get_skew_check(
        self, skew_check_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/skew-checks/{skew_check_id}", None, headers)

    def list_skew_checks(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/skew-checks", params, headers)

    # ─── Retraining triggers ───

    def get_retraining_trigger(
        self, retraining_trigger_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"/retraining-triggers/{retraining_trigger_id}", None, headers
        )

    def list_retraining_triggers(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/retraining-triggers", params, headers)

    def disposition_retraining_trigger(
        self,
        retraining_trigger_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/retraining-triggers/{retraining_trigger_id}/disposition",
            payload,
            headers,
        )

    # ─── Champion-challenger evaluations ───

    def get_challenger_evaluation(
        self, evaluation_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"/challenger-evaluations/{evaluation_id}", None, headers
        )

    def list_challenger_evaluations(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/challenger-evaluations", params, headers)

    def start_challenger_evaluation(
        self, evaluation_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/challenger-evaluations/{evaluation_id}/start", {}, headers
        )

    def conclude_challenger_evaluation(
        self, evaluation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/challenger-evaluations/{evaluation_id}/conclude",
            payload,
            headers,
        )

    def extend_challenger_evaluation(
        self, evaluation_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/challenger-evaluations/{evaluation_id}/extend", {}, headers
        )

    # ─── Prediction incidents ───

    def create_prediction_incident(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/prediction-incidents", payload, headers)

    def get_prediction_incident(
        self, incident_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"/prediction-incidents/{incident_id}", None, headers
        )

    def list_prediction_incidents(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/prediction-incidents", params, headers)

    def incident_action(
        self, incident_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/prediction-incidents/{incident_id}/actions", payload, headers
        )

    # ─── Periodic revalidation ───

    def get_revalidation_task(
        self, revalidation_task_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"/revalidation-tasks/{revalidation_task_id}", None, headers
        )

    def list_revalidation_tasks(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/revalidation-tasks", params, headers)

    def disposition_revalidation_task(
        self,
        revalidation_task_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/revalidation-tasks/{revalidation_task_id}/disposition",
            payload,
            headers,
        )

    # ─── Operational namespace ───

    def set_clock(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_revalidation_sweep(self, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/_ops/revalidation-sweep", {}, headers)
