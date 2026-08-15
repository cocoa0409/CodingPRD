"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # --- PayEquityStudy ---
    def create_study(self, payload, headers):
        return self._request("POST", "/api/pay-equity-studies", payload, headers)

    def list_studies(self, headers, params=None):
        return self._request("GET", "/api/pay-equity-studies", headers=headers, params=params)

    def get_study(self, study_id, headers):
        return self._request("GET", f"/api/pay-equity-studies/{study_id}", headers=headers)

    def advance_study(self, study_id, headers):
        return self._request("POST", f"/api/pay-equity-studies/{study_id}/advance", {}, headers)

    def submit_legal_review(self, study_id, headers):
        return self._request(
            "POST", f"/api/pay-equity-studies/{study_id}/submit-legal-review", {}, headers
        )

    def legal_decision(self, study_id, payload, headers):
        return self._request(
            "POST", f"/api/pay-equity-studies/{study_id}/legal-decision", payload, headers
        )

    def open_remediation(self, study_id, headers):
        return self._request(
            "POST", f"/api/pay-equity-studies/{study_id}/open-remediation", {}, headers
        )

    def begin_monitoring(self, study_id, headers):
        return self._request(
            "POST", f"/api/pay-equity-studies/{study_id}/begin-monitoring", {}, headers
        )

    def close_study(self, study_id, headers):
        return self._request("POST", f"/api/pay-equity-studies/{study_id}/close", {}, headers)

    # --- EmployeeSnapshot ---
    def create_snapshot(self, payload, headers):
        return self._request("POST", "/api/employee-snapshots", payload, headers)

    def list_snapshots(self, headers, params=None):
        return self._request("GET", "/api/employee-snapshots", headers=headers, params=params)

    def get_snapshot(self, snapshot_id, headers):
        return self._request("GET", f"/api/employee-snapshots/{snapshot_id}", headers=headers)

    def patch_snapshot(self, snapshot_id, payload, headers):
        return self._request("PATCH", f"/api/employee-snapshots/{snapshot_id}", payload, headers)

    # --- ComparatorGroup ---
    def create_group(self, payload, headers):
        return self._request("POST", "/api/comparator-groups", payload, headers)

    def list_groups(self, headers, params=None):
        return self._request("GET", "/api/comparator-groups", headers=headers, params=params)

    def get_group(self, group_id, headers):
        return self._request("GET", f"/api/comparator-groups/{group_id}", headers=headers)

    def lock_group(self, group_id, headers):
        return self._request("POST", f"/api/comparator-groups/{group_id}/lock", {}, headers)

    # --- ModelRun ---
    def create_model_run(self, payload, headers):
        return self._request("POST", "/api/model-runs", payload, headers)

    def list_model_runs(self, headers, params=None):
        return self._request("GET", "/api/model-runs", headers=headers, params=params)

    def get_model_run(self, run_id, headers):
        return self._request("GET", f"/api/model-runs/{run_id}", headers=headers)

    def finalize_run(self, run_id, headers):
        return self._request("POST", f"/api/model-runs/{run_id}/finalize", {}, headers)

    # --- GapFinding ---
    def list_findings(self, headers, params=None):
        return self._request("GET", "/api/gap-findings", headers=headers, params=params)

    def get_finding(self, finding_id, headers):
        return self._request("GET", f"/api/gap-findings/{finding_id}", headers=headers)

    def disposition_finding(self, finding_id, payload, headers):
        return self._request(
            "POST", f"/api/gap-findings/{finding_id}/disposition", payload, headers
        )

    # --- RemediationPlan ---
    def create_plan(self, payload, headers):
        return self._request("POST", "/api/remediation-plans", payload, headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/api/remediation-plans", headers=headers, params=params)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/api/remediation-plans/{plan_id}", headers=headers)

    def get_suggested_allocation(self, plan_id, headers):
        return self._request(
            "GET", f"/api/remediation-plans/{plan_id}/suggested-allocation", headers=headers
        )

    def submit_plan(self, plan_id, headers):
        return self._request("POST", f"/api/remediation-plans/{plan_id}/submit", {}, headers)

    def decide_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/api/remediation-plans/{plan_id}/decision", payload, headers)

    # --- Adjustment ---
    def create_adjustment(self, payload, headers):
        return self._request("POST", "/api/adjustments", payload, headers)

    def list_adjustments(self, headers, params=None):
        return self._request("GET", "/api/adjustments", headers=headers, params=params)

    def get_adjustment(self, adjustment_id, headers):
        return self._request("GET", f"/api/adjustments/{adjustment_id}", headers=headers)

    def decide_adjustment(self, adjustment_id, payload, headers):
        return self._request(
            "POST", f"/api/adjustments/{adjustment_id}/decision", payload, headers
        )

    def reverse_adjustment(self, adjustment_id, payload, headers):
        return self._request(
            "POST", f"/api/adjustments/{adjustment_id}/reverse", payload, headers
        )

    # --- ReportFiling ---
    def create_filing(self, payload, headers):
        return self._request("POST", "/api/report-filings", payload, headers)

    def list_filings(self, headers, params=None):
        return self._request("GET", "/api/report-filings", headers=headers, params=params)

    def get_filing(self, filing_id, headers):
        return self._request("GET", f"/api/report-filings/{filing_id}", headers=headers)

    def compile_filing(self, filing_id, headers):
        return self._request("POST", f"/api/report-filings/{filing_id}/compile", {}, headers)

    def submit_filing(self, filing_id, headers):
        return self._request("POST", f"/api/report-filings/{filing_id}/submit", {}, headers)

    def record_filing_decision(self, filing_id, payload, headers):
        return self._request(
            "POST", f"/api/report-filings/{filing_id}/record-decision", payload, headers
        )

    def reopen_filing(self, filing_id, headers):
        return self._request("POST", f"/api/report-filings/{filing_id}/reopen", {}, headers)

    # --- JurisdictionRule ---
    def create_jurisdiction_rule(self, payload, headers):
        return self._request("POST", "/api/jurisdiction-rules", payload, headers)

    def list_jurisdiction_rules(self, headers, params=None):
        return self._request("GET", "/api/jurisdiction-rules", headers=headers, params=params)

    def get_jurisdiction_rule(self, rule_id, headers):
        return self._request("GET", f"/api/jurisdiction-rules/{rule_id}", headers=headers)

    # --- TransparencyPosting ---
    def create_posting(self, payload, headers):
        return self._request("POST", "/api/transparency-postings", payload, headers)

    def list_postings(self, headers, params=None):
        return self._request("GET", "/api/transparency-postings", headers=headers, params=params)

    def get_posting(self, posting_id, headers):
        return self._request("GET", f"/api/transparency-postings/{posting_id}", headers=headers)

    def publish_posting(self, posting_id, headers):
        return self._request("POST", f"/api/transparency-postings/{posting_id}/publish", {}, headers)

    def close_posting(self, posting_id, headers):
        return self._request("POST", f"/api/transparency-postings/{posting_id}/close", {}, headers)

    # --- PipelineAnalysis ---
    def create_pipeline_analysis(self, payload, headers):
        return self._request("POST", "/api/pipeline-analyses", payload, headers)

    def list_pipeline_analyses(self, headers, params=None):
        return self._request("GET", "/api/pipeline-analyses", headers=headers, params=params)

    def get_pipeline_analysis(self, analysis_id, headers):
        return self._request("GET", f"/api/pipeline-analyses/{analysis_id}", headers=headers)

    # --- MonitoringCycle ---
    def create_monitoring_cycle(self, payload, headers):
        return self._request("POST", "/api/monitoring-cycles", payload, headers)

    def list_monitoring_cycles(self, headers, params=None):
        return self._request("GET", "/api/monitoring-cycles", headers=headers, params=params)

    def get_monitoring_cycle(self, cycle_id, headers):
        return self._request("GET", f"/api/monitoring-cycles/{cycle_id}", headers=headers)

    def start_cycle(self, cycle_id, headers):
        return self._request("POST", f"/api/monitoring-cycles/{cycle_id}/start", {}, headers)

    def complete_cycle(self, cycle_id, payload, headers):
        return self._request(
            "POST", f"/api/monitoring-cycles/{cycle_id}/complete", payload, headers
        )


api_client = ApiClient()
