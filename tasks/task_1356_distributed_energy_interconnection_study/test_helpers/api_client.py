"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ------------------------------------------------------------------
    # Developers
    # ------------------------------------------------------------------
    def create_developer(self, payload, headers):
        return self._request("POST", "/interconnection/developers", payload, headers)

    def get_developer(self, developer_id, headers):
        return self._request(
            "GET", f"/interconnection/developers/{developer_id}", headers=headers
        )

    def list_developer_projects(self, developer_id, headers, params=None):
        return self._request(
            "GET",
            f"/interconnection/developers/{developer_id}/projects",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Cluster groups
    # ------------------------------------------------------------------
    def create_cluster_group(self, payload, headers):
        return self._request("POST", "/interconnection/cluster-groups", payload, headers)

    def get_cluster_group(self, cluster_group_id, headers):
        return self._request(
            "GET", f"/interconnection/cluster-groups/{cluster_group_id}", headers=headers
        )

    def list_cluster_projects(self, cluster_group_id, headers, params=None):
        return self._request(
            "GET",
            f"/interconnection/cluster-groups/{cluster_group_id}/projects",
            headers=headers,
            params=params,
        )

    def list_cluster_studies(self, cluster_group_id, headers):
        return self._request(
            "GET",
            f"/interconnection/cluster-groups/{cluster_group_id}/studies",
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Projects and deposit ledger
    # ------------------------------------------------------------------
    def create_project(self, payload, headers):
        return self._request("POST", "/interconnection/projects", payload, headers)

    def get_project(self, project_id, headers):
        return self._request(
            "GET", f"/interconnection/projects/{project_id}", headers=headers
        )

    def post_deposit(self, project_id, payload, headers):
        return self._request(
            "POST", f"/interconnection/projects/{project_id}/deposits", payload, headers
        )

    def list_deposits(self, project_id, headers, params=None):
        return self._request(
            "GET",
            f"/interconnection/projects/{project_id}/deposits",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Milestone submissions
    # ------------------------------------------------------------------
    def create_milestone_submission(self, project_id, payload, headers):
        return self._request(
            "POST",
            f"/interconnection/projects/{project_id}/milestone-submissions",
            payload,
            headers,
        )

    def list_milestone_submissions(self, project_id, headers, params=None):
        return self._request(
            "GET",
            f"/interconnection/projects/{project_id}/milestone-submissions",
            headers=headers,
            params=params,
        )

    def review_milestone_submission(self, submission_id, payload, headers):
        return self._request(
            "POST",
            f"/interconnection/milestone-submissions/{submission_id}/review",
            payload,
            headers,
        )

    def resubmit_milestone_submission(self, submission_id, payload, headers):
        return self._request(
            "POST",
            f"/interconnection/milestone-submissions/{submission_id}/resubmit",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Studies and cost shares
    # ------------------------------------------------------------------
    def create_study(self, cluster_group_id, payload, headers):
        return self._request(
            "POST",
            f"/interconnection/cluster-groups/{cluster_group_id}/studies",
            payload,
            headers,
        )

    def get_study(self, study_id, headers):
        return self._request(
            "GET", f"/interconnection/studies/{study_id}", headers=headers
        )

    def publish_study_results(self, study_id, headers):
        return self._request(
            "POST", f"/interconnection/studies/{study_id}/publish-results", {}, headers
        )

    def finalize_study(self, study_id, headers):
        return self._request(
            "POST", f"/interconnection/studies/{study_id}/finalize", {}, headers
        )

    def list_study_cost_shares(self, study_id, headers, params=None):
        return self._request(
            "GET",
            f"/interconnection/studies/{study_id}/cost-shares",
            headers=headers,
            params=params,
        )

    def list_project_cost_shares(self, project_id, headers, params=None):
        return self._request(
            "GET",
            f"/interconnection/projects/{project_id}/cost-shares",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Interconnection agreements
    # ------------------------------------------------------------------
    def issue_agreement(self, project_id, payload, headers):
        return self._request(
            "POST", f"/interconnection/projects/{project_id}/agreements", payload, headers
        )

    def list_project_agreements(self, project_id, headers, params=None):
        return self._request(
            "GET",
            f"/interconnection/projects/{project_id}/agreements",
            headers=headers,
            params=params,
        )

    def execute_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/interconnection/agreements/{agreement_id}/execute", {}, headers
        )

    def request_extension(self, agreement_id, payload, headers):
        return self._request(
            "POST",
            f"/interconnection/agreements/{agreement_id}/extensions",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Withdrawal and commercial operation
    # ------------------------------------------------------------------
    def withdraw_project(self, project_id, headers):
        return self._request(
            "POST", f"/interconnection/projects/{project_id}/withdraw", {}, headers
        )

    def declare_commercial_operation(self, project_id, headers):
        return self._request(
            "POST",
            f"/interconnection/projects/{project_id}/declare-commercial-operation",
            {},
            headers,
        )

    # ------------------------------------------------------------------
    # Curtailment limits
    # ------------------------------------------------------------------
    def create_curtailment_limit(self, project_id, payload, headers):
        return self._request(
            "POST",
            f"/interconnection/projects/{project_id}/curtailment-limits",
            payload,
            headers,
        )

    def list_curtailment_limits(self, project_id, headers, params=None):
        return self._request(
            "GET",
            f"/interconnection/projects/{project_id}/curtailment-limits",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Transparency reports
    # ------------------------------------------------------------------
    def create_transparency_report(self, payload, headers):
        return self._request(
            "POST", "/interconnection/transparency-reports", payload, headers
        )

    def get_transparency_report(self, report_id, headers):
        return self._request(
            "GET", f"/interconnection/transparency-reports/{report_id}", headers=headers
        )


api_client = ApiClient()
