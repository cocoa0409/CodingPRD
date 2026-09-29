"""
Open Data Portal API client — one method per endpoint the PRD exposes.

Every method returns the raw ``requests.Response`` so tests can assert on status
codes as well as bodies. The whole surface is mounted under the ``/open-data``
prefix.
"""

from typing import Any, Dict, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/open-data"


class ApiClient(GenericApiClient):
    """Typed endpoint methods for the Open Data Portal API."""

    # ─── Departments ──────────────────────────────────────────────────

    def create_department(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/departments", payload, headers)

    def list_departments(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/departments", params=params, headers=headers)

    def get_department(self, department_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/departments/{department_id}", headers=headers)

    def get_department_scorecard(self, department_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/departments/{department_id}/scorecard", headers=headers)

    def grant_department_credits(
        self, department_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/departments/{department_id}/credit-grants", payload, headers
        )

    # ─── Licences ─────────────────────────────────────────────────────

    def create_license(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/licenses", payload, headers)

    def list_licenses(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/licenses", params=params, headers=headers)

    def get_license(self, license_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/licenses/{license_id}", headers=headers)

    def retire_license(
        self, license_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/licenses/{license_id}/retire", payload or {}, headers)

    # ─── Ingest runners ───────────────────────────────────────────────

    def create_ingest_runner(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/ingest-runners", payload, headers)

    def list_ingest_runners(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/ingest-runners", params=params, headers=headers)

    def get_ingest_runner(self, runner_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/ingest-runners/{runner_id}", headers=headers)

    def update_ingest_runner(
        self, runner_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("PATCH", f"{PREFIX}/ingest-runners/{runner_id}", payload, headers)

    # ─── Datasets ─────────────────────────────────────────────────────

    def create_dataset(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/datasets", payload, headers)

    def list_datasets(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/datasets", params=params, headers=headers)

    def get_dataset(self, dataset_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/datasets/{dataset_id}", headers=headers)

    def get_dataset_analytics(self, dataset_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/datasets/{dataset_id}/analytics", headers=headers)

    def screen_dataset(
        self, dataset_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/datasets/{dataset_id}/screen", payload or {}, headers)

    def set_dataset_aggregation(
        self, dataset_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/datasets/{dataset_id}/aggregation", payload, headers)

    def mark_dataset_ready(
        self, dataset_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/datasets/{dataset_id}/mark-ready", payload or {}, headers)

    def publish_dataset(
        self, dataset_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/datasets/{dataset_id}/publish", payload, headers)

    def retire_dataset(
        self, dataset_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/datasets/{dataset_id}/retire", payload or {}, headers)

    def report_dataset_usage(
        self, dataset_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/datasets/{dataset_id}/usage-report", payload, headers)

    def commit_high_value(
        self, dataset_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/datasets/{dataset_id}/high-value-commitment", payload or {}, headers
        )

    def submit_showcase_app(
        self, dataset_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/datasets/{dataset_id}/showcase-apps", payload, headers)

    def decide_showcase_app(
        self,
        dataset_id: str,
        showcase_label: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/datasets/{dataset_id}/showcase-apps/{showcase_label}/decide",
            payload,
            headers,
        )

    # ─── Metadata records ─────────────────────────────────────────────

    def create_metadata_record(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/metadata-records", payload, headers)

    def list_metadata_records(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/metadata-records", params=params, headers=headers)

    def get_metadata_record(self, metadata_record_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/metadata-records/{metadata_record_id}", headers=headers)

    def revise_metadata_record(
        self, metadata_record_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("PATCH", f"{PREFIX}/metadata-records/{metadata_record_id}", payload, headers)

    def submit_metadata_record(
        self,
        metadata_record_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/metadata-records/{metadata_record_id}/submit", payload or {}, headers
        )

    def decide_metadata_record(
        self, metadata_record_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/metadata-records/{metadata_record_id}/decide", payload, headers
        )

    # ─── Privacy assessments ──────────────────────────────────────────

    def create_privacy_assessment(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/privacy-assessments", payload, headers)

    def list_privacy_assessments(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/privacy-assessments", params=params, headers=headers)

    def get_privacy_assessment(self, assessment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/privacy-assessments/{assessment_id}", headers=headers)

    def revise_privacy_assessment(
        self, assessment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("PATCH", f"{PREFIX}/privacy-assessments/{assessment_id}", payload, headers)

    def submit_privacy_assessment(
        self, assessment_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/privacy-assessments/{assessment_id}/submit", payload or {}, headers
        )

    def decide_privacy_assessment(
        self, assessment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/privacy-assessments/{assessment_id}/decide", payload, headers
        )

    def reopen_privacy_assessment(
        self, assessment_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/privacy-assessments/{assessment_id}/reopen", payload or {}, headers
        )

    # ─── Publication pipelines ────────────────────────────────────────

    def create_publication_pipeline(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/publication-pipelines", payload, headers)

    def list_publication_pipelines(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/publication-pipelines", params=params, headers=headers)

    def get_publication_pipeline(self, pipeline_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/publication-pipelines/{pipeline_id}", headers=headers)

    def arm_pipeline(
        self, pipeline_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/publication-pipelines/{pipeline_id}/arm", payload or {}, headers
        )

    def suspend_pipeline(
        self, pipeline_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/publication-pipelines/{pipeline_id}/suspend", payload or {}, headers
        )

    def resume_pipeline(
        self, pipeline_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/publication-pipelines/{pipeline_id}/resume", payload or {}, headers
        )

    def decommission_pipeline(
        self, pipeline_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/publication-pipelines/{pipeline_id}/decommission", payload or {}, headers
        )

    # ─── Pipeline runs ────────────────────────────────────────────────

    def create_pipeline_run(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/pipeline-runs", payload, headers)

    def list_pipeline_runs(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/pipeline-runs", params=params, headers=headers)

    def get_pipeline_run(self, run_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/pipeline-runs/{run_id}", headers=headers)

    def start_run(
        self, run_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/pipeline-runs/{run_id}/start", payload or {}, headers)

    def report_run_success(
        self, run_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/pipeline-runs/{run_id}/report-success", payload, headers)

    def report_run_failure(
        self, run_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/pipeline-runs/{run_id}/report-failure", payload, headers)

    def requeue_run(
        self, run_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/pipeline-runs/{run_id}/requeue", payload, headers)

    # ─── Dataset versions ─────────────────────────────────────────────

    def create_dataset_version(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/dataset-versions", payload, headers)

    def list_dataset_versions(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/dataset-versions", params=params, headers=headers)

    def get_dataset_version(self, version_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/dataset-versions/{version_id}", headers=headers)

    def retract_dataset_version(
        self, version_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/dataset-versions/{version_id}/retract", payload or {}, headers
        )

    # ─── Community members ────────────────────────────────────────────

    def register_member(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/members/register", payload, headers)

    def get_member(self, member_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/members/{member_id}", headers=headers)

    # ─── Quality issues ───────────────────────────────────────────────

    def create_quality_issue(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/quality-issues", payload, headers)

    def list_quality_issues(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/quality-issues", params=params, headers=headers)

    def get_quality_issue(self, issue_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/quality-issues/{issue_id}", headers=headers)

    def triage_quality_issue(
        self, issue_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/quality-issues/{issue_id}/triage", payload or {}, headers)

    def decide_quality_issue(
        self, issue_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/quality-issues/{issue_id}/decide", payload, headers)

    def link_correction(
        self, issue_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/quality-issues/{issue_id}/link-correction", payload, headers
        )

    def close_quality_issue(
        self, issue_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/quality-issues/{issue_id}/close", payload or {}, headers)

    # ─── Dataset requests ─────────────────────────────────────────────

    def create_dataset_request(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/dataset-requests", payload, headers)

    def list_dataset_requests(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/dataset-requests", params=params, headers=headers)

    def get_dataset_request(self, request_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/dataset-requests/{request_id}", headers=headers)

    def cast_request_vote(
        self, request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/dataset-requests/{request_id}/votes", payload, headers)

    def review_dataset_request(
        self, request_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/dataset-requests/{request_id}/review", payload or {}, headers
        )

    def decide_dataset_request(
        self, request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/dataset-requests/{request_id}/decide", payload, headers)

    def fulfill_dataset_request(
        self, request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/dataset-requests/{request_id}/fulfill", payload, headers)

    # ─── Operational capabilities ─────────────────────────────────────

    def run_ops_sweep(
        self, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/ops-run", payload or {}, headers)

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)


# Module-level singleton reused by every test through conftest.
api_client = ApiClient()
