"""API client: one method per endpoint defined in the PRD (section 4)."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed endpoint surface for the Medicare Cost Report Wage Index API."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def get_clock(self, headers):
        return self._request("GET", "/_clock", headers=headers)

    # ------------------------------------------------------------------
    # Provider
    # ------------------------------------------------------------------

    def create_provider(self, payload, headers):
        return self._request("POST", "/providers", payload, headers)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/providers/{provider_id}", headers=headers)

    def list_providers(self, headers, params=None):
        return self._request("GET", "/providers", headers=headers, params=params)

    # ------------------------------------------------------------------
    # CostReport
    # ------------------------------------------------------------------

    def create_cost_report(self, payload, headers):
        return self._request("POST", "/cost-reports", payload, headers)

    def get_cost_report(self, report_id, headers):
        return self._request("GET", f"/cost-reports/{report_id}", headers=headers)

    def list_cost_reports(self, headers, params=None):
        return self._request("GET", "/cost-reports", headers=headers, params=params)

    def file_cost_report(self, report_id, headers, payload=None):
        return self._request(
            "POST", f"/cost-reports/{report_id}/file", payload or {}, headers
        )

    def get_gme_summary(self, report_id, headers):
        return self._request(
            "GET", f"/cost-reports/{report_id}/gme-summary", headers=headers
        )

    # ------------------------------------------------------------------
    # CostCenter
    # ------------------------------------------------------------------

    def create_cost_center(self, report_id, payload, headers):
        return self._request(
            "POST", f"/cost-reports/{report_id}/cost-centers", payload, headers
        )

    def get_cost_center(self, cost_center_id, headers):
        return self._request("GET", f"/cost-centers/{cost_center_id}", headers=headers)

    def list_report_cost_centers(self, report_id, headers, params=None):
        return self._request(
            "GET",
            f"/cost-reports/{report_id}/cost-centers",
            headers=headers,
            params=params,
        )

    def update_cost_center(self, cost_center_id, payload, headers):
        return self._request(
            "PATCH", f"/cost-centers/{cost_center_id}", payload, headers
        )

    # ------------------------------------------------------------------
    # TrialBalanceLine
    # ------------------------------------------------------------------

    def create_trial_balance_line(self, report_id, payload, headers):
        return self._request(
            "POST", f"/cost-reports/{report_id}/trial-balance-lines", payload, headers
        )

    def get_trial_balance_line(self, line_id, headers):
        return self._request(
            "GET", f"/trial-balance-lines/{line_id}", headers=headers
        )

    def list_report_trial_balance_lines(self, report_id, headers, params=None):
        return self._request(
            "GET",
            f"/cost-reports/{report_id}/trial-balance-lines",
            headers=headers,
            params=params,
        )

    def list_cost_center_trial_balance_lines(self, cost_center_id, headers, params=None):
        return self._request(
            "GET",
            f"/cost-centers/{cost_center_id}/trial-balance-lines",
            headers=headers,
            params=params,
        )

    def map_trial_balance_line(self, line_id, payload, headers):
        return self._request(
            "POST", f"/trial-balance-lines/{line_id}/map", payload, headers
        )

    # ------------------------------------------------------------------
    # WorkpaperEntry
    # ------------------------------------------------------------------

    def create_workpaper_entry(self, report_id, payload, headers):
        return self._request(
            "POST", f"/cost-reports/{report_id}/workpaper-entries", payload, headers
        )

    def get_workpaper_entry(self, entry_id, headers):
        return self._request("GET", f"/workpaper-entries/{entry_id}", headers=headers)

    def list_report_workpaper_entries(self, report_id, headers, params=None):
        return self._request(
            "GET",
            f"/cost-reports/{report_id}/workpaper-entries",
            headers=headers,
            params=params,
        )

    def list_audit_adjustment_workpaper_entries(self, adjustment_id, headers, params=None):
        return self._request(
            "GET",
            f"/audit-adjustments/{adjustment_id}/workpaper-entries",
            headers=headers,
            params=params,
        )

    def reverse_workpaper_entry(self, entry_id, headers, payload=None):
        return self._request(
            "POST", f"/workpaper-entries/{entry_id}/reverse", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # StepdownRun
    # ------------------------------------------------------------------

    def create_stepdown_run(self, report_id, payload, headers):
        return self._request(
            "POST", f"/cost-reports/{report_id}/stepdown-runs", payload, headers
        )

    def get_stepdown_run(self, run_id, headers):
        return self._request("GET", f"/stepdown-runs/{run_id}", headers=headers)

    def list_report_stepdown_runs(self, report_id, headers, params=None):
        return self._request(
            "GET",
            f"/cost-reports/{report_id}/stepdown-runs",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # WageIndexSubmission and the occupational mix survey
    # ------------------------------------------------------------------

    def create_wage_index_submission(self, report_id, payload, headers):
        return self._request(
            "POST",
            f"/cost-reports/{report_id}/wage-index-submissions",
            payload,
            headers,
        )

    def get_wage_index_submission(self, submission_id, headers):
        return self._request(
            "GET", f"/wage-index-submissions/{submission_id}", headers=headers
        )

    def list_report_wage_index_submissions(self, report_id, headers, params=None):
        return self._request(
            "GET",
            f"/cost-reports/{report_id}/wage-index-submissions",
            headers=headers,
            params=params,
        )

    def update_wage_index_submission(self, submission_id, payload, headers):
        return self._request(
            "PATCH", f"/wage-index-submissions/{submission_id}", payload, headers
        )

    def submit_wage_index_submission(self, submission_id, headers, payload=None):
        return self._request(
            "POST",
            f"/wage-index-submissions/{submission_id}/submit",
            payload or {},
            headers,
        )

    def start_wage_index_review(self, submission_id, headers, payload=None):
        return self._request(
            "POST",
            f"/wage-index-submissions/{submission_id}/start-review",
            payload or {},
            headers,
        )

    def record_wage_index_review_decision(self, submission_id, payload, headers):
        return self._request(
            "POST",
            f"/wage-index-submissions/{submission_id}/review-decision",
            payload,
            headers,
        )

    def create_occ_mix_response(self, submission_id, payload, headers):
        return self._request(
            "POST",
            f"/wage-index-submissions/{submission_id}/occ-mix-responses",
            payload,
            headers,
        )

    def list_occ_mix_responses(self, submission_id, headers, params=None):
        return self._request(
            "GET",
            f"/wage-index-submissions/{submission_id}/occ-mix-responses",
            headers=headers,
            params=params,
        )

    def get_occ_mix_response(self, response_id, headers):
        return self._request(
            "GET", f"/occ-mix-responses/{response_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Resident and RotationAssignment
    # ------------------------------------------------------------------

    def create_resident(self, provider_id, payload, headers):
        return self._request(
            "POST", f"/providers/{provider_id}/residents", payload, headers
        )

    def list_provider_residents(self, provider_id, headers, params=None):
        return self._request(
            "GET", f"/providers/{provider_id}/residents", headers=headers, params=params
        )

    def get_resident(self, resident_id, headers):
        return self._request("GET", f"/residents/{resident_id}", headers=headers)

    def create_rotation_assignment(self, resident_id, payload, headers):
        return self._request(
            "POST", f"/residents/{resident_id}/rotation-assignments", payload, headers
        )

    def get_rotation_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/rotation-assignments/{assignment_id}", headers=headers
        )

    def list_rotation_assignments(self, headers, params=None):
        return self._request(
            "GET", "/rotation-assignments", headers=headers, params=params
        )

    def void_rotation_assignment(self, assignment_id, headers, payload=None):
        return self._request(
            "POST",
            f"/rotation-assignments/{assignment_id}/void",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # UccDataSet
    # ------------------------------------------------------------------

    def create_ucc_data_set(self, report_id, payload, headers):
        return self._request(
            "POST", f"/cost-reports/{report_id}/ucc-data-sets", payload, headers
        )

    def get_ucc_data_set(self, data_set_id, headers):
        return self._request("GET", f"/ucc-data-sets/{data_set_id}", headers=headers)

    def list_report_ucc_data_sets(self, report_id, headers, params=None):
        return self._request(
            "GET",
            f"/cost-reports/{report_id}/ucc-data-sets",
            headers=headers,
            params=params,
        )

    def recompute_ucc_data_set(self, data_set_id, headers, payload=None):
        return self._request(
            "POST", f"/ucc-data-sets/{data_set_id}/recompute", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Settlement
    # ------------------------------------------------------------------

    def create_settlement(self, report_id, payload, headers):
        return self._request(
            "POST", f"/cost-reports/{report_id}/settlements", payload, headers
        )

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/settlements/{settlement_id}", headers=headers)

    def list_report_settlements(self, report_id, headers, params=None):
        return self._request(
            "GET",
            f"/cost-reports/{report_id}/settlements",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # AuditAdjustment
    # ------------------------------------------------------------------

    def create_audit_adjustment(self, settlement_id, payload, headers):
        return self._request(
            "POST", f"/settlements/{settlement_id}/audit-adjustments", payload, headers
        )

    def get_audit_adjustment(self, adjustment_id, headers):
        return self._request(
            "GET", f"/audit-adjustments/{adjustment_id}", headers=headers
        )

    def list_audit_adjustments(self, headers, params=None):
        return self._request(
            "GET", "/audit-adjustments", headers=headers, params=params
        )

    def respond_to_audit_adjustment(self, adjustment_id, payload, headers):
        return self._request(
            "POST", f"/audit-adjustments/{adjustment_id}/respond", payload, headers
        )

    def resolve_audit_adjustment(self, adjustment_id, payload, headers):
        return self._request(
            "POST", f"/audit-adjustments/{adjustment_id}/resolve", payload, headers
        )

    # ------------------------------------------------------------------
    # AppealCase
    # ------------------------------------------------------------------

    def create_appeal_case(self, report_id, payload, headers):
        return self._request(
            "POST", f"/cost-reports/{report_id}/appeal-cases", payload, headers
        )

    def get_appeal_case(self, case_id, headers):
        return self._request("GET", f"/appeal-cases/{case_id}", headers=headers)

    def list_appeal_cases(self, headers, params=None):
        return self._request("GET", "/appeal-cases", headers=headers, params=params)

    def decide_appeal_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"/appeal-cases/{case_id}/decide", payload, headers
        )

    # ------------------------------------------------------------------
    # InterimRateRequest
    # ------------------------------------------------------------------

    def create_interim_rate_request(self, payload, headers):
        return self._request("POST", "/interim-rate-requests", payload, headers)

    def get_interim_rate_request(self, request_id, headers):
        return self._request(
            "GET", f"/interim-rate-requests/{request_id}", headers=headers
        )

    def list_interim_rate_requests(self, headers, params=None):
        return self._request(
            "GET", "/interim-rate-requests", headers=headers, params=params
        )

    def decide_interim_rate_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/interim-rate-requests/{request_id}/decide", payload, headers
        )


api_client = ApiClient()
