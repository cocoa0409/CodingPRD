"""API client for the Research Funding API: one method per endpoint defined in the PRD."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Projects ---
    def create_project(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/projects", payload, headers)

    def list_projects(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/projects", headers=headers, params=params)

    def get_project(self, project_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/projects/{project_id}", headers=headers)

    def submit_project(self, project_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/projects/{project_id}/submit", payload or {}, headers)

    def approve_project(self, project_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/projects/{project_id}/approve", payload or {}, headers)

    def reject_project(self, project_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/projects/{project_id}/reject", payload or {}, headers)

    def activate_project(self, project_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/projects/{project_id}/activate", payload or {}, headers)

    def begin_closing(self, project_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/projects/{project_id}/begin-closing", payload or {}, headers)

    # --- Peer reviews ---
    def create_peer_review(self, project_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/projects/{project_id}/peer-reviews", payload, headers)

    def list_peer_reviews(self, project_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/projects/{project_id}/peer-reviews", headers=headers, params=params)

    # --- Budget items ---
    def create_budget_item(self, project_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/projects/{project_id}/budget-items", payload, headers)

    def list_budget_items(self, project_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/projects/{project_id}/budget-items", headers=headers, params=params)

    def get_budget_item(self, budget_item_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/budget-items/{budget_item_id}", headers=headers)

    # --- Budget adjustments ---
    def create_budget_adjustment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/budget-adjustments", payload, headers)

    def list_budget_adjustments(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/budget-adjustments", headers=headers, params=params)

    def get_budget_adjustment(self, adjustment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/budget-adjustments/{adjustment_id}", headers=headers)

    def submit_budget_adjustment(self, adjustment_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/budget-adjustments/{adjustment_id}/submit", payload or {}, headers)

    def dept_approve_budget_adjustment(self, adjustment_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/budget-adjustments/{adjustment_id}/dept-approve", payload or {}, headers)

    def finance_approve_budget_adjustment(self, adjustment_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/budget-adjustments/{adjustment_id}/finance-approve", payload or {}, headers)

    def reject_budget_adjustment(self, adjustment_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/budget-adjustments/{adjustment_id}/reject", payload, headers)

    # --- Reimbursements ---
    def create_reimbursement(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/reimbursements", payload, headers)

    def list_reimbursements(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/reimbursements", headers=headers, params=params)

    def get_reimbursement(self, reimbursement_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/reimbursements/{reimbursement_id}", headers=headers)

    def submit_reimbursement(self, reimbursement_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/reimbursements/{reimbursement_id}/submit", payload or {}, headers)

    def pi_approve_reimbursement(self, reimbursement_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/reimbursements/{reimbursement_id}/pi-approve", payload or {}, headers)

    def dept_approve_reimbursement(self, reimbursement_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/reimbursements/{reimbursement_id}/dept-approve", payload or {}, headers)

    def finance_approve_reimbursement(self, reimbursement_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/reimbursements/{reimbursement_id}/finance-approve", payload or {}, headers)

    def mark_paid_reimbursement(self, reimbursement_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/reimbursements/{reimbursement_id}/mark-paid", payload or {}, headers)

    def reject_reimbursement(self, reimbursement_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/reimbursements/{reimbursement_id}/reject", payload, headers)

    def rework_reimbursement(self, reimbursement_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/reimbursements/{reimbursement_id}/rework", payload or {}, headers)

    # --- Closing audits ---
    def create_closing_audit(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/closing-audits", payload, headers)

    def get_closing_audit(self, audit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/closing-audits/{audit_id}", headers=headers)

    def submit_closing_audit(self, audit_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/closing-audits/{audit_id}/submit", payload or {}, headers)

    def flag_rectification(self, audit_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/closing-audits/{audit_id}/flag-rectification", payload or {}, headers)

    def resubmit_closing_audit(self, audit_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/closing-audits/{audit_id}/resubmit", payload or {}, headers)

    def close_audit(self, audit_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/closing-audits/{audit_id}/close", payload or {}, headers)

    # --- Compliance rules ---
    def create_compliance_rule(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/compliance-rules", payload, headers)

    def list_compliance_rules(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/compliance-rules", headers=headers, params=params)

    def patch_compliance_rule(self, rule_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/compliance-rules/{rule_id}", payload, headers)

    # --- Allocation runs ---
    def create_allocation_run(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/allocation-runs", payload, headers)

    def get_allocation_run(self, run_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/allocation-runs/{run_id}", headers=headers)

    # --- Audit logs ---
    def list_audit_logs(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/audit-logs", headers=headers, params=params)

    # --- Test-driving endpoints ---
    def advance_clock(self, target_iso: str, headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", {"target_iso": target_iso}, headers)

    def emit_event(self, event_type: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_events/emit", {"event_type": event_type, "payload": payload}, headers)


api_client = ApiClient()
