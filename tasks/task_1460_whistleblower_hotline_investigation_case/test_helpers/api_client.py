"""API client: one method per endpoint defined in the PRD."""
from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock ---
    def set_clock(self, to_iso8601: str, headers: Dict):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # --- Staff ---
    def create_staff_member(self, payload: Dict, headers: Dict):
        return self._request("POST", "/hotline/staff-members", payload, headers)

    def list_staff_members(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/hotline/staff-members", headers=headers, params=params)

    def patch_staff_member(self, staff_id: str, payload: Dict, headers: Dict):
        return self._request("PATCH", f"/hotline/staff-members/{staff_id}", payload, headers)

    # --- Cases ---
    def create_case(self, payload: Dict, headers: Dict):
        return self._request("POST", "/hotline/cases", payload, headers)

    def list_cases(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/hotline/cases", headers=headers, params=params)

    def get_case(self, case_id: str, headers: Dict):
        return self._request("GET", f"/hotline/cases/{case_id}", headers=headers)

    def get_reporter_status(self, case_id: str, headers: Dict):
        return self._request("GET", f"/hotline/cases/{case_id}/reporter-status", headers=headers)

    def withdraw_case(self, case_id: str, headers: Dict):
        return self._request("POST", f"/hotline/cases/{case_id}/withdraw", {}, headers)

    def triage_case(self, case_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/hotline/cases/{case_id}/triage", payload, headers)

    # --- Assignments ---
    def create_assignment(self, case_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/hotline/cases/{case_id}/assignments", payload, headers)

    def list_assignments(self, case_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", f"/hotline/cases/{case_id}/assignments", headers=headers, params=params)

    def screen_assignment(self, assignment_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/hotline/assignments/{assignment_id}/screen", payload, headers)

    def waive_assignment(self, assignment_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/hotline/assignments/{assignment_id}/waive-conflict", payload, headers)

    def activate_assignment(self, assignment_id: str, headers: Dict):
        return self._request("POST", f"/hotline/assignments/{assignment_id}/activate", {}, headers)

    def release_assignment(self, assignment_id: str, headers: Dict):
        return self._request("POST", f"/hotline/assignments/{assignment_id}/release", {}, headers)

    # --- Interviews ---
    def create_interview(self, payload: Dict, headers: Dict):
        return self._request("POST", "/hotline/interviews", payload, headers)

    def list_interviews(self, case_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", f"/hotline/cases/{case_id}/interviews", headers=headers, params=params)

    def conclude_interview(self, interview_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/hotline/interviews/{interview_id}/conclude", payload, headers)

    # --- Evidence ---
    def create_evidence_item(self, payload: Dict, headers: Dict):
        return self._request("POST", "/hotline/evidence-items", payload, headers)

    def list_evidence_items(self, case_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", f"/hotline/cases/{case_id}/evidence-items", headers=headers, params=params)

    def seal_evidence(self, evidence_id: str, headers: Dict):
        return self._request("POST", f"/hotline/evidence-items/{evidence_id}/seal", {}, headers)

    def exclude_evidence(self, evidence_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/hotline/evidence-items/{evidence_id}/exclude", payload, headers)

    # --- Determinations ---
    def create_determination(self, case_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/hotline/cases/{case_id}/determinations", payload, headers)

    def list_determinations(self, case_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", f"/hotline/cases/{case_id}/determinations", headers=headers, params=params)

    def get_determination(self, determination_id: str, headers: Dict):
        return self._request("GET", f"/hotline/determinations/{determination_id}", headers=headers)

    def submit_determination(self, determination_id: str, headers: Dict):
        return self._request("POST", f"/hotline/determinations/{determination_id}/submit", {}, headers)

    def review_determination(self, determination_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/hotline/determinations/{determination_id}/review", payload, headers)

    # --- Remediation ---
    def create_remediation_action(self, determination_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/hotline/determinations/{determination_id}/remediation-actions", payload, headers)

    def list_remediation_actions(self, case_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", f"/hotline/cases/{case_id}/remediation-actions", headers=headers, params=params)

    def decide_remediation_action(self, action_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/hotline/remediation-actions/{action_id}/decide", payload, headers)

    def verify_remediation_action(self, action_id: str, headers: Dict):
        return self._request("POST", f"/hotline/remediation-actions/{action_id}/verify", {}, headers)

    def extend_remediation_action(self, action_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/hotline/remediation-actions/{action_id}/extend", payload, headers)

    # --- Closure notices / monitoring ---
    def list_closure_notices(self, case_id: str, headers: Dict):
        return self._request("GET", f"/hotline/cases/{case_id}/closure-notices", headers=headers)

    def acknowledge_notice(self, notice_id: str, headers: Dict):
        return self._request("POST", f"/hotline/closure-notices/{notice_id}/acknowledge", {}, headers)

    def list_monitoring_plans(self, case_id: str, headers: Dict):
        return self._request("GET", f"/hotline/cases/{case_id}/monitoring-plans", headers=headers)

    def check_in_monitoring_plan(self, plan_id: str, headers: Dict):
        return self._request("POST", f"/hotline/monitoring-plans/{plan_id}/check-in", {}, headers)

    # --- Retaliation ---
    def create_retaliation_flag(self, case_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/hotline/cases/{case_id}/retaliation-flags", payload, headers)

    def list_retaliation_flags(self, case_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", f"/hotline/cases/{case_id}/retaliation-flags", headers=headers, params=params)

    def dismiss_retaliation_flag(self, flag_id: str, headers: Dict):
        return self._request("POST", f"/hotline/retaliation-flags/{flag_id}/dismiss", {}, headers)

    # --- Legal holds ---
    def create_legal_hold(self, payload: Dict, headers: Dict):
        return self._request("POST", "/hotline/legal-holds", payload, headers)

    def list_legal_holds(self, case_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", f"/hotline/cases/{case_id}/legal-holds", headers=headers, params=params)

    def release_legal_hold(self, hold_id: str, headers: Dict):
        return self._request("POST", f"/hotline/legal-holds/{hold_id}/release", {}, headers)

    # --- Reports ---
    def create_audit_report(self, payload: Dict, headers: Dict):
        return self._request("POST", "/hotline/audit-committee-reports", payload, headers)

    def list_audit_reports(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/hotline/audit-committee-reports", headers=headers, params=params)

    def finalize_audit_report(self, report_id: str, headers: Dict):
        return self._request("POST", f"/hotline/audit-committee-reports/{report_id}/finalize", {}, headers)

    def present_audit_report(self, report_id: str, headers: Dict):
        return self._request("POST", f"/hotline/audit-committee-reports/{report_id}/present", {}, headers)

    # --- Audit trail ---
    def list_case_status_events(self, case_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", f"/hotline/cases/{case_id}/case-status-events", headers=headers, params=params)


api_client = ApiClient()
