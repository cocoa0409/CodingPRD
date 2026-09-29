"""
Domain API client: one method per declared endpoint of the /ood-placements API.

Every method returns the raw requests.Response so tests can assert status codes
directly. Headers are always explicit because every request - reads included -
must carry X-User-ID and X-User-Role.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .constants import CLOCK_SET_PATH, MOUNT


class ApiClient(GenericApiClient):
    """Endpoint methods for the Out-of-District Placement & Tuition API."""

    # ─── Logical clock ────────────────────────────────────────────────────────
    def set_clock(self, current_utc: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", CLOCK_SET_PATH, {"current_utc": current_utc}, headers
        )

    # ─── District fiscal accounts ─────────────────────────────────────────────
    def list_fiscal_accounts(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{MOUNT}/fiscal-accounts", params, headers)

    def create_fiscal_account(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{MOUNT}/fiscal-accounts", payload, headers)

    def get_fiscal_account(
        self, account_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{MOUNT}/fiscal-accounts/{account_id}", None, headers
        )

    # ─── Students ─────────────────────────────────────────────────────────────
    def list_students(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{MOUNT}/students", params, headers)

    def create_student(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{MOUNT}/students", payload, headers)

    def get_student(self, student_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{MOUNT}/students/{student_id}", None, headers)

    def patch_medicaid_consent(
        self, student_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "PATCH", f"{MOUNT}/students/{student_id}/medicaid-consent", payload, headers
        )

    # ─── Approved private schools ─────────────────────────────────────────────
    def list_private_schools(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{MOUNT}/private-schools", params, headers)

    def create_private_school(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{MOUNT}/private-schools", payload, headers)

    def get_private_school(
        self, school_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{MOUNT}/private-schools/{school_id}", None, headers
        )

    def patch_school_approval_status(
        self, school_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "PATCH",
            f"{MOUNT}/private-schools/{school_id}/approval-status",
            payload,
            headers,
        )

    # ─── Tuition rate schedules ───────────────────────────────────────────────
    def list_rate_schedules(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{MOUNT}/tuition-rate-schedules", params, headers)

    def create_rate_schedule(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{MOUNT}/tuition-rate-schedules", payload, headers)

    def get_rate_schedule(
        self, schedule_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{MOUNT}/tuition-rate-schedules/{schedule_id}", None, headers
        )

    # ─── Placement decisions ──────────────────────────────────────────────────
    def list_placement_decisions(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{MOUNT}/placement-decisions", params, headers)

    def create_placement_decision(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{MOUNT}/placement-decisions", payload, headers)

    def get_placement_decision(
        self, decision_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{MOUNT}/placement-decisions/{decision_id}", None, headers
        )

    def patch_placement_decision(
        self, decision_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "PATCH", f"{MOUNT}/placement-decisions/{decision_id}", payload, headers
        )

    def submit_placement_decision(
        self,
        decision_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{MOUNT}/placement-decisions/{decision_id}/submit",
            payload or {},
            headers,
        )

    def return_decision_for_revision(
        self, decision_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{MOUNT}/placement-decisions/{decision_id}/return-for-revision",
            payload,
            headers,
        )

    def approve_placement_decision(
        self,
        decision_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{MOUNT}/placement-decisions/{decision_id}/approve",
            payload or {},
            headers,
        )

    # ─── Placements ───────────────────────────────────────────────────────────
    def list_placements(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{MOUNT}/placements", params, headers)

    def create_placement(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{MOUNT}/placements", payload, headers)

    def get_placement(
        self, placement_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"{MOUNT}/placements/{placement_id}", None, headers)

    def get_cost_projection(
        self,
        placement_id: str,
        headers: Dict[str, str],
        params: Optional[Dict] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{MOUNT}/placements/{placement_id}/cost-projection",
            params,
            headers,
        )

    def execute_contract(
        self,
        placement_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{MOUNT}/placements/{placement_id}/execute-contract",
            payload or {},
            headers,
        )

    def activate_placement(
        self,
        placement_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{MOUNT}/placements/{placement_id}/activate",
            payload or {},
            headers,
        )

    def terminate_placement(
        self, placement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{MOUNT}/placements/{placement_id}/terminate", payload, headers
        )

    def return_to_district(
        self, placement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{MOUNT}/placements/{placement_id}/return-to-district",
            payload,
            headers,
        )

    # ─── Service addenda ──────────────────────────────────────────────────────
    def list_service_addenda(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{MOUNT}/service-addenda", params, headers)

    def create_service_addendum(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{MOUNT}/service-addenda", payload, headers)

    def get_service_addendum(
        self, addendum_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{MOUNT}/service-addenda/{addendum_id}", None, headers
        )

    def authorize_service_addendum(
        self,
        addendum_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{MOUNT}/service-addenda/{addendum_id}/authorize",
            payload or {},
            headers,
        )

    # ─── Transport routes ─────────────────────────────────────────────────────
    def list_transport_routes(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{MOUNT}/transport-routes", params, headers)

    def create_transport_route(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{MOUNT}/transport-routes", payload, headers)

    def get_transport_route(
        self, route_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{MOUNT}/transport-routes/{route_id}", None, headers
        )

    # ─── Transportation assignments ───────────────────────────────────────────
    def list_transportation_assignments(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{MOUNT}/transportation-assignments", params, headers
        )

    def create_transportation_assignment(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{MOUNT}/transportation-assignments", payload, headers
        )

    def get_transportation_assignment(
        self, assignment_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{MOUNT}/transportation-assignments/{assignment_id}", None, headers
        )

    def release_transportation_assignment(
        self,
        assignment_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{MOUNT}/transportation-assignments/{assignment_id}/release",
            payload or {},
            headers,
        )

    # ─── Attendance records ───────────────────────────────────────────────────
    def list_attendance_records(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{MOUNT}/attendance-records", params, headers)

    def create_attendance_record(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{MOUNT}/attendance-records", payload, headers)

    def get_attendance_record(
        self, record_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{MOUNT}/attendance-records/{record_id}", None, headers
        )

    def verify_attendance_record(
        self, record_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{MOUNT}/attendance-records/{record_id}/verify", payload, headers
        )

    def amend_attendance_record(
        self, record_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{MOUNT}/attendance-records/{record_id}/amend", payload, headers
        )

    # ─── Tuition invoices ─────────────────────────────────────────────────────
    def list_tuition_invoices(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{MOUNT}/tuition-invoices", params, headers)

    def create_tuition_invoice(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{MOUNT}/tuition-invoices", payload, headers)

    def get_tuition_invoice(
        self, invoice_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{MOUNT}/tuition-invoices/{invoice_id}", None, headers
        )

    def verify_tuition_invoice(
        self, invoice_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{MOUNT}/tuition-invoices/{invoice_id}/verify", payload, headers
        )

    def resubmit_tuition_invoice(
        self, invoice_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{MOUNT}/tuition-invoices/{invoice_id}/resubmit", payload, headers
        )

    def approve_invoice_payment(
        self,
        invoice_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{MOUNT}/tuition-invoices/{invoice_id}/approve-payment",
            payload or {},
            headers,
        )

    # ─── Reimbursement claims ─────────────────────────────────────────────────
    def list_reimbursement_claims(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{MOUNT}/reimbursement-claims", params, headers)

    def create_reimbursement_claim(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{MOUNT}/reimbursement-claims", payload, headers)

    def get_reimbursement_claim(
        self, claim_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{MOUNT}/reimbursement-claims/{claim_id}", None, headers
        )

    def adjudicate_reimbursement_claim(
        self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{MOUNT}/reimbursement-claims/{claim_id}/adjudicate",
            payload,
            headers,
        )

    def remand_reimbursement_claim(
        self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{MOUNT}/reimbursement-claims/{claim_id}/remand", payload, headers
        )

    # ─── Progress reports ─────────────────────────────────────────────────────
    def list_progress_reports(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{MOUNT}/progress-reports", params, headers)

    def create_progress_report(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{MOUNT}/progress-reports", payload, headers)

    def get_progress_report(
        self, report_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{MOUNT}/progress-reports/{report_id}", None, headers
        )

    def accept_progress_report(
        self, report_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{MOUNT}/progress-reports/{report_id}/accept", payload, headers
        )

    # ─── Return transition plans ──────────────────────────────────────────────
    def list_transition_plans(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{MOUNT}/return-transition-plans", params, headers
        )

    def create_transition_plan(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{MOUNT}/return-transition-plans", payload, headers
        )

    def get_transition_plan(
        self, plan_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{MOUNT}/return-transition-plans/{plan_id}", None, headers
        )

    def get_plan_readiness(
        self, plan_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{MOUNT}/return-transition-plans/{plan_id}/readiness",
            params,
            headers,
        )

    def activate_transition_plan(
        self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{MOUNT}/return-transition-plans/{plan_id}/activate",
            payload,
            headers,
        )

    # ─── Funding claims ───────────────────────────────────────────────────────
    def list_funding_claims(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{MOUNT}/funding-claims", params, headers)

    def create_funding_claim(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{MOUNT}/funding-claims", payload, headers)

    def get_funding_claim(
        self, claim_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{MOUNT}/funding-claims/{claim_id}", None, headers
        )

    def submit_funding_claim_to_state(
        self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{MOUNT}/funding-claims/{claim_id}/submit-to-state",
            payload,
            headers,
        )
