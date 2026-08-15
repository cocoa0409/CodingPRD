"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/er/_clock/set_current_utc", payload, headers)

    # --- employees ---
    def create_employee(self, payload, headers):
        return self._request("POST", "/er/employees", payload, headers)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"/er/employees/{employee_id}", headers=headers)

    def list_employees(self, headers, params=None):
        return self._request("GET", "/er/employees", headers=headers, params=params)

    def patch_employee(self, employee_id, payload, headers):
        return self._request("PATCH", f"/er/employees/{employee_id}", payload, headers)

    # --- investigators ---
    def create_investigator(self, payload, headers):
        return self._request("POST", "/er/investigators", payload, headers)

    def get_investigator(self, investigator_id, headers):
        return self._request("GET", f"/er/investigators/{investigator_id}", headers=headers)

    def list_investigators(self, headers, params=None):
        return self._request("GET", "/er/investigators", headers=headers, params=params)

    def patch_investigator(self, investigator_id, payload, headers):
        return self._request("PATCH", f"/er/investigators/{investigator_id}", payload, headers)

    # --- intake channels ---
    def create_intake_channel(self, payload, headers):
        return self._request("POST", "/er/intake-channels", payload, headers)

    def list_intake_channels(self, headers, params=None):
        return self._request("GET", "/er/intake-channels", headers=headers, params=params)

    # --- holidays ---
    def create_holiday(self, payload, headers):
        return self._request("POST", "/er/holiday-calendar", payload, headers)

    def list_holidays(self, headers, params=None):
        return self._request("GET", "/er/holiday-calendar", headers=headers, params=params)

    # --- cases ---
    def create_case(self, payload, headers):
        return self._request("POST", "/er/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/er/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/er/cases", headers=headers, params=params)

    def patch_case(self, case_id, payload, headers):
        return self._request("PATCH", f"/er/cases/{case_id}", payload, headers)

    def assign_case(self, case_id, payload, headers):
        return self._request("POST", f"/er/cases/{case_id}/assign", payload, headers)

    def unassign_case(self, case_id, payload, headers):
        return self._request("POST", f"/er/cases/{case_id}/unassign", payload, headers)

    def begin_investigation(self, case_id, headers):
        return self._request("POST", f"/er/cases/{case_id}/begin-investigation", {}, headers)

    def hold_case(self, case_id, payload, headers):
        return self._request("POST", f"/er/cases/{case_id}/hold", payload, headers)

    def resume_case(self, case_id, headers):
        return self._request("POST", f"/er/cases/{case_id}/resume", {}, headers)

    def close_case(self, case_id, payload, headers):
        return self._request("POST", f"/er/cases/{case_id}/close", payload, headers)

    def reopen_case(self, case_id, payload, headers):
        return self._request("POST", f"/er/cases/{case_id}/reopen", payload, headers)

    # --- interviews ---
    def create_interview(self, case_id, payload, headers):
        return self._request("POST", f"/er/cases/{case_id}/interviews", payload, headers)

    def list_case_interviews(self, case_id, headers, params=None):
        return self._request("GET", f"/er/cases/{case_id}/interviews", headers=headers, params=params)

    def get_interview(self, interview_id, headers):
        return self._request("GET", f"/er/interviews/{interview_id}", headers=headers)

    def list_interviews(self, headers, params=None):
        return self._request("GET", "/er/interviews", headers=headers, params=params)

    def complete_interview(self, interview_id, payload, headers):
        return self._request("POST", f"/er/interviews/{interview_id}/complete", payload, headers)

    def mark_no_show(self, interview_id, headers):
        return self._request("POST", f"/er/interviews/{interview_id}/mark-no-show", {}, headers)

    def cancel_interview(self, interview_id, headers):
        return self._request("POST", f"/er/interviews/{interview_id}/cancel", {}, headers)

    # --- evidence ---
    def create_evidence_item(self, case_id, payload, headers):
        return self._request("POST", f"/er/cases/{case_id}/evidence-items", payload, headers)

    def list_case_evidence(self, case_id, headers, params=None):
        return self._request("GET", f"/er/cases/{case_id}/evidence-items", headers=headers, params=params)

    def get_evidence_item(self, evidence_id, headers):
        return self._request("GET", f"/er/evidence-items/{evidence_id}", headers=headers)

    def list_evidence_items(self, headers, params=None):
        return self._request("GET", "/er/evidence-items", headers=headers, params=params)

    def begin_review(self, evidence_id, headers):
        return self._request("POST", f"/er/evidence-items/{evidence_id}/begin-review", {}, headers)

    def admit_evidence(self, evidence_id, payload, headers):
        return self._request("POST", f"/er/evidence-items/{evidence_id}/admit", payload, headers)

    def exclude_evidence(self, evidence_id, payload, headers):
        return self._request("POST", f"/er/evidence-items/{evidence_id}/exclude", payload, headers)

    def archive_evidence(self, evidence_id, headers):
        return self._request("POST", f"/er/evidence-items/{evidence_id}/archive", {}, headers)

    # --- credibility assessments ---
    def create_credibility_assessment(self, case_id, payload, headers):
        return self._request("POST", f"/er/cases/{case_id}/credibility-assessments", payload, headers)

    def list_case_assessments(self, case_id, headers, params=None):
        return self._request("GET", f"/er/cases/{case_id}/credibility-assessments", headers=headers, params=params)

    def get_credibility_assessment(self, assessment_id, headers):
        return self._request("GET", f"/er/credibility-assessments/{assessment_id}", headers=headers)

    def list_credibility_assessments(self, headers, params=None):
        return self._request("GET", "/er/credibility-assessments", headers=headers, params=params)

    # --- findings & actions ---
    def create_finding(self, case_id, payload, headers):
        return self._request("POST", f"/er/cases/{case_id}/findings", payload, headers)

    def list_case_findings(self, case_id, headers, params=None):
        return self._request("GET", f"/er/cases/{case_id}/findings", headers=headers, params=params)

    def get_finding(self, finding_id, headers):
        return self._request("GET", f"/er/findings/{finding_id}", headers=headers)

    def list_findings(self, headers, params=None):
        return self._request("GET", "/er/findings", headers=headers, params=params)

    def patch_finding(self, finding_id, payload, headers):
        return self._request("PATCH", f"/er/findings/{finding_id}", payload, headers)

    def substantiate_finding(self, finding_id, payload, headers):
        return self._request("POST", f"/er/findings/{finding_id}/substantiate", payload, headers)

    def create_recommended_action(self, finding_id, payload, headers):
        return self._request("POST", f"/er/findings/{finding_id}/actions", payload, headers)

    def list_finding_actions(self, finding_id, headers, params=None):
        return self._request("GET", f"/er/findings/{finding_id}/actions", headers=headers, params=params)

    def withdraw_action(self, action_id, headers):
        return self._request("POST", f"/er/recommended-actions/{action_id}/withdraw", {}, headers)

    def submit_for_calibration(self, finding_id, headers):
        return self._request("POST", f"/er/findings/{finding_id}/submit-for-calibration", {}, headers)

    def approve_finding(self, finding_id, headers):
        return self._request("POST", f"/er/findings/{finding_id}/approve", {}, headers)

    def reject_finding(self, finding_id, payload, headers):
        return self._request("POST", f"/er/findings/{finding_id}/reject", payload, headers)

    # --- closure notices ---
    def create_closure_notice(self, case_id, payload, headers):
        return self._request("POST", f"/er/cases/{case_id}/closure-notices", payload, headers)

    def list_case_notices(self, case_id, headers, params=None):
        return self._request("GET", f"/er/cases/{case_id}/closure-notices", headers=headers, params=params)

    def get_closure_notice(self, notice_id, headers):
        return self._request("GET", f"/er/closure-notices/{notice_id}", headers=headers)

    def list_closure_notices(self, headers, params=None):
        return self._request("GET", "/er/closure-notices", headers=headers, params=params)

    def send_notice(self, notice_id, headers):
        return self._request("POST", f"/er/closure-notices/{notice_id}/send", {}, headers)

    def mark_notice_failed(self, notice_id, payload, headers):
        return self._request("POST", f"/er/closure-notices/{notice_id}/mark-failed", payload, headers)

    def retry_notice(self, notice_id, headers):
        return self._request("POST", f"/er/closure-notices/{notice_id}/retry", {}, headers)

    def suppress_notice(self, notice_id, headers):
        return self._request("POST", f"/er/closure-notices/{notice_id}/suppress", {}, headers)

    # --- trend snapshots ---
    def create_trend_snapshot(self, payload, headers):
        return self._request("POST", "/er/trend-snapshots", payload, headers)

    def list_trend_snapshots(self, headers, params=None):
        return self._request("GET", "/er/trend-snapshots", headers=headers, params=params)

    def get_trend_snapshot(self, snapshot_id, headers):
        return self._request("GET", f"/er/trend-snapshots/{snapshot_id}", headers=headers)

    # --- litigation packages ---
    def create_litigation_package(self, case_id, headers):
        return self._request("POST", f"/er/cases/{case_id}/litigation-packages", {}, headers)

    def list_case_packages(self, case_id, headers, params=None):
        return self._request("GET", f"/er/cases/{case_id}/litigation-packages", headers=headers, params=params)

    def get_litigation_package(self, package_id, headers):
        return self._request("GET", f"/er/litigation-packages/{package_id}", headers=headers)

    def finalize_package(self, package_id, headers):
        return self._request("POST", f"/er/litigation-packages/{package_id}/finalize", {}, headers)

    def seal_package(self, package_id, payload, headers):
        return self._request("POST", f"/er/litigation-packages/{package_id}/seal", payload, headers)

    def release_package(self, package_id, payload, headers):
        return self._request("POST", f"/er/litigation-packages/{package_id}/release", payload, headers)


api_client = ApiClient()
