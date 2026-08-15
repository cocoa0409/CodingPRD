"""API client: one method per endpoint defined in PRD Section 4."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for the H-2A Labor Contractor API (all under /h2a)."""

    # --- Logical clock (PRD 2.4) ---
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/h2a/_clock/set_current_utc", payload, headers)

    # --- Growers (PRD 3.1) ---
    def create_grower(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/h2a/growers", payload, headers)

    def list_growers(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/h2a/growers", headers=headers, params=params)

    def refresh_grower_status(self, grower_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/h2a/growers/{grower_id}/refresh-status", {}, headers
        )

    # --- Wage determinations (PRD 3.1) ---
    def create_wage_determination(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/h2a/wage-determinations", payload, headers)

    def list_wage_determinations(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/h2a/wage-determinations", headers=headers, params=params)

    # --- Job orders (PRD 3.2) ---
    def create_job_order(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/h2a/job-orders", payload, headers)

    def list_job_orders(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/h2a/job-orders", headers=headers, params=params)

    def get_job_order(self, job_order_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/h2a/job-orders/{job_order_id}", headers=headers)

    def patch_job_order(self, job_order_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/h2a/job-orders/{job_order_id}", payload, headers)

    def submit_job_order(self, job_order_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/h2a/job-orders/{job_order_id}/submit", {}, headers)

    def flag_job_order_deficiency(self, job_order_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/h2a/job-orders/{job_order_id}/flag-deficiency", payload, headers)

    def certify_job_order(self, job_order_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/h2a/job-orders/{job_order_id}/certify", {}, headers)

    def begin_recruitment(self, job_order_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/h2a/job-orders/{job_order_id}/begin-recruitment", {}, headers)

    def close_recruitment(self, job_order_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/h2a/job-orders/{job_order_id}/close-recruitment", {}, headers)

    def activate_job_order(self, job_order_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/h2a/job-orders/{job_order_id}/activate", {}, headers)

    def close_job_order(self, job_order_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/h2a/job-orders/{job_order_id}/close", {}, headers)

    def finalize_job_order(self, job_order_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/h2a/job-orders/{job_order_id}/finalize", {}, headers)

    def withdraw_job_order(self, job_order_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/h2a/job-orders/{job_order_id}/withdraw", {}, headers)

    # --- Domestic applications (PRD 3.3) ---
    def create_domestic_application(self, job_order_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/h2a/job-orders/{job_order_id}/domestic-applications", payload, headers)

    def list_domestic_applications(self, job_order_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/h2a/job-orders/{job_order_id}/domestic-applications", headers=headers, params=params)

    def decide_domestic_application(self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/h2a/domestic-applications/{application_id}/decide", payload, headers)

    # --- Workers (PRD 3.4) ---
    def create_worker(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/h2a/workers", payload, headers)

    def list_workers(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/h2a/workers", headers=headers, params=params)

    def get_worker(self, worker_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/h2a/workers/{worker_id}", headers=headers)

    # --- Visa petitions (PRD 3.4) ---
    def create_visa_petition(self, job_order_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/h2a/job-orders/{job_order_id}/visa-petitions", payload, headers)

    def list_visa_petitions(self, job_order_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/h2a/job-orders/{job_order_id}/visa-petitions", headers=headers, params=params)

    def get_visa_petition(self, petition_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/h2a/visa-petitions/{petition_id}", headers=headers)

    def file_visa_petition(self, petition_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/h2a/visa-petitions/{petition_id}/file", {}, headers)

    def link_worker(self, petition_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/h2a/visa-petitions/{petition_id}/link-worker", payload, headers)

    def issue_rfe(self, petition_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/h2a/visa-petitions/{petition_id}/issue-rfe", payload, headers)

    def respond_rfe(self, petition_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/h2a/visa-petitions/{petition_id}/respond-rfe", payload, headers)

    def adjudicate_petition(self, petition_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/h2a/visa-petitions/{petition_id}/adjudicate", payload, headers)

    # --- Consular appointments (PRD 3.4) ---
    def create_consular_appointment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/h2a/consular-appointments", payload, headers)

    def list_consular_appointments(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/h2a/consular-appointments", headers=headers, params=params)

    def get_consular_appointment(self, appointment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/h2a/consular-appointments/{appointment_id}", headers=headers)

    def complete_consular_appointment(self, appointment_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/h2a/consular-appointments/{appointment_id}/complete", payload, headers)

    def cancel_consular_appointment(self, appointment_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/h2a/consular-appointments/{appointment_id}/cancel", {}, headers)

    # --- Housing units and inspections (PRD 3.5) ---
    def create_housing_unit(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/h2a/housing-units", payload, headers)

    def list_housing_units(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/h2a/housing-units", headers=headers, params=params)

    def get_housing_unit(self, unit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/h2a/housing-units/{unit_id}", headers=headers)

    def record_housing_inspection(self, unit_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/h2a/housing-units/{unit_id}/inspections", payload, headers)

    def list_housing_inspections(self, unit_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/h2a/housing-units/{unit_id}/inspections", headers=headers, params=params)

    def expire_housing_unit(self, unit_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/h2a/housing-units/{unit_id}/expire", {}, headers)

    # --- Housing assignments (PRD 3.5) ---
    def create_housing_assignment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/h2a/housing-assignments", payload, headers)

    def list_housing_assignments(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/h2a/housing-assignments", headers=headers, params=params)

    def get_housing_assignment(self, housing_assignment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/h2a/housing-assignments/{housing_assignment_id}", headers=headers)

    def vacate_housing_assignment(self, housing_assignment_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/h2a/housing-assignments/{housing_assignment_id}/vacate", payload, headers)

    # --- Worker assignments, work logs, reconciliations (PRD 3.6, 3.7) ---
    def create_worker_assignment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/h2a/worker-assignments", payload, headers)

    def list_worker_assignments(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/h2a/worker-assignments", headers=headers, params=params)

    def get_worker_assignment(self, assignment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/h2a/worker-assignments/{assignment_id}", headers=headers)

    def start_worker_assignment(self, assignment_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/h2a/worker-assignments/{assignment_id}/start", {}, headers)

    def end_worker_assignment(self, assignment_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/h2a/worker-assignments/{assignment_id}/end", payload, headers)

    def report_abandonment(self, assignment_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/h2a/worker-assignments/{assignment_id}/report-abandonment", payload, headers)

    def create_work_log(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/h2a/work-logs", payload, headers)

    def list_work_logs(self, assignment_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/h2a/worker-assignments/{assignment_id}/work-logs", headers=headers, params=params)

    def get_reconciliation(self, assignment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/h2a/worker-assignments/{assignment_id}/reconciliation", headers=headers)

    def finalize_reconciliation(self, assignment_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/h2a/worker-assignments/{assignment_id}/finalize-reconciliation", {}, headers)

    # --- Transfer requests (PRD 3.8) ---
    def create_transfer_request(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/h2a/transfer-requests", payload, headers)

    def list_transfer_requests(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/h2a/transfer-requests", headers=headers, params=params)

    def get_transfer_request(self, transfer_request_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/h2a/transfer-requests/{transfer_request_id}", headers=headers)

    def grower_approve_transfer(self, transfer_request_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/h2a/transfer-requests/{transfer_request_id}/grower-approve", {}, headers)

    def grower_reject_transfer(self, transfer_request_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/h2a/transfer-requests/{transfer_request_id}/grower-reject", payload, headers)

    def finalize_transfer(self, transfer_request_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/h2a/transfer-requests/{transfer_request_id}/finalize", {}, headers)

    def cancel_transfer(self, transfer_request_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/h2a/transfer-requests/{transfer_request_id}/cancel", {}, headers)

    # --- Audit cases (PRD 3.9) ---
    def create_audit_case(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/h2a/audit-cases", payload, headers)

    def list_audit_cases(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/h2a/audit-cases", headers=headers, params=params)

    def get_audit_case(self, audit_case_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/h2a/audit-cases/{audit_case_id}", headers=headers)

    def issue_findings(self, audit_case_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/h2a/audit-cases/{audit_case_id}/issue-findings", payload, headers)

    def close_audit_case_no_action(self, audit_case_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/h2a/audit-cases/{audit_case_id}/close-no-action", {}, headers)

    def assess_penalty(self, audit_case_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/h2a/audit-cases/{audit_case_id}/assess-penalty", payload, headers)

    def debar_grower(self, audit_case_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/h2a/audit-cases/{audit_case_id}/debar", payload, headers)


api_client = ApiClient()
