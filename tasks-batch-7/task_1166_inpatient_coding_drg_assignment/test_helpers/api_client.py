"""API client: one method per endpoint defined in the PRD (Section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- PatientAccount ----
    def create_patient_account(self, payload, headers):
        return self._request("POST", "/patient-accounts", payload, headers)

    def get_patient_account(self, account_id, headers):
        return self._request("GET", f"/patient-accounts/{account_id}", headers=headers)

    def list_patient_accounts(self, headers, params=None):
        return self._request("GET", "/patient-accounts", headers=headers, params=params)

    def discharge_patient_account(self, account_id, payload, headers):
        return self._request(
            "POST", f"/patient-accounts/{account_id}/discharge", payload, headers
        )

    # ---- Chart ----
    def create_chart(self, payload, headers):
        return self._request("POST", "/charts", payload, headers)

    def get_chart(self, chart_id, headers):
        return self._request("GET", f"/charts/{chart_id}", headers=headers)

    def list_charts(self, headers, params=None):
        return self._request("GET", "/charts", headers=headers, params=params)

    # ---- ChartDeficiency ----
    def create_deficiency(self, payload, headers):
        return self._request("POST", "/deficiencies", payload, headers)

    def get_deficiency(self, deficiency_id, headers):
        return self._request("GET", f"/deficiencies/{deficiency_id}", headers=headers)

    def list_deficiencies(self, headers, params=None):
        return self._request("GET", "/deficiencies", headers=headers, params=params)

    def resolve_deficiency(self, deficiency_id, headers):
        return self._request(
            "POST", f"/deficiencies/{deficiency_id}/resolve", {}, headers
        )

    # ---- DiagnosisLine / ProcedureLine ----
    def create_diagnosis_line(self, payload, headers):
        return self._request("POST", "/diagnosis-lines", payload, headers)

    def get_diagnosis_line(self, line_id, headers):
        return self._request("GET", f"/diagnosis-lines/{line_id}", headers=headers)

    def list_diagnosis_lines(self, headers, params=None):
        return self._request("GET", "/diagnosis-lines", headers=headers, params=params)

    def patch_diagnosis_line(self, line_id, payload, headers):
        return self._request("PATCH", f"/diagnosis-lines/{line_id}", payload, headers)

    def create_procedure_line(self, payload, headers):
        return self._request("POST", "/procedure-lines", payload, headers)

    def get_procedure_line(self, line_id, headers):
        return self._request("GET", f"/procedure-lines/{line_id}", headers=headers)

    def list_procedure_lines(self, headers, params=None):
        return self._request("GET", "/procedure-lines", headers=headers, params=params)

    # ---- Coder ----
    def create_coder(self, payload, headers):
        return self._request("POST", "/coders", payload, headers)

    def get_coder(self, coder_id, headers):
        return self._request("GET", f"/coders/{coder_id}", headers=headers)

    def patch_coder(self, coder_id, payload, headers):
        return self._request("PATCH", f"/coders/{coder_id}", payload, headers)

    # ---- CodingAssignment ----
    def create_assignment(self, payload, headers):
        return self._request("POST", "/assignments", payload, headers)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}", headers=headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/assignments", headers=headers, params=params)

    def assign_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"/assignments/{assignment_id}/assign", payload, headers
        )

    def start_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/assignments/{assignment_id}/start", {}, headers
        )

    def submit_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/assignments/{assignment_id}/submit", {}, headers
        )

    def accept_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/assignments/{assignment_id}/accept", {}, headers
        )

    def return_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"/assignments/{assignment_id}/return", payload, headers
        )

    def release_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/assignments/{assignment_id}/release", {}, headers
        )

    # ---- CodedCase ----
    def get_coded_case(self, case_id, headers):
        return self._request("GET", f"/coded-cases/{case_id}", headers=headers)

    def list_coded_cases(self, headers, params=None):
        return self._request("GET", "/coded-cases", headers=headers, params=params)

    def regroup_coded_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"/coded-cases/{case_id}/regroup", payload, headers
        )

    # ---- Bill ----
    def create_bill(self, payload, headers):
        return self._request("POST", "/bills", payload, headers)

    def get_bill(self, bill_id, headers):
        return self._request("GET", f"/bills/{bill_id}", headers=headers)

    def list_bills(self, headers, params=None):
        return self._request("GET", "/bills", headers=headers, params=params)

    def finalize_bill(self, bill_id, headers):
        return self._request("POST", f"/bills/{bill_id}/finalize", {}, headers)

    def record_payment(self, bill_id, payload, headers):
        return self._request(
            "POST", f"/bills/{bill_id}/record-payment", payload, headers
        )

    # ---- DNFB sweeps ----
    def create_dnfb_sweep(self, payload, headers):
        return self._request("POST", "/dnfb-sweeps", payload, headers)

    def get_dnfb_sweep(self, sweep_id, headers):
        return self._request("GET", f"/dnfb-sweeps/{sweep_id}", headers=headers)

    # ---- CodingAudit / AuditFinding ----
    def create_audit(self, payload, headers):
        return self._request("POST", "/audits", payload, headers)

    def get_audit(self, audit_id, headers):
        return self._request("GET", f"/audits/{audit_id}", headers=headers)

    def list_audits(self, headers, params=None):
        return self._request("GET", "/audits", headers=headers, params=params)

    def create_finding(self, audit_id, payload, headers):
        return self._request("POST", f"/audits/{audit_id}/findings", payload, headers)

    def get_finding(self, finding_id, headers):
        return self._request("GET", f"/audit-findings/{finding_id}", headers=headers)

    def list_findings(self, headers, params=None):
        return self._request("GET", "/audit-findings", headers=headers, params=params)

    def resolve_finding(self, finding_id, payload, headers):
        return self._request(
            "POST", f"/audit-findings/{finding_id}/resolve", payload, headers
        )

    def complete_audit(self, audit_id, headers):
        return self._request("POST", f"/audits/{audit_id}/complete", {}, headers)

    # ---- PostPaymentReview / RebillRequest ----
    def create_post_payment_review(self, bill_id, payload, headers):
        return self._request(
            "POST", f"/bills/{bill_id}/post-payment-reviews", payload, headers
        )

    def get_post_payment_review(self, review_id, headers):
        return self._request(
            "GET", f"/post-payment-reviews/{review_id}", headers=headers
        )

    def list_post_payment_reviews(self, headers, params=None):
        return self._request(
            "GET", "/post-payment-reviews", headers=headers, params=params
        )

    def close_post_payment_review(self, review_id, headers):
        return self._request(
            "POST", f"/post-payment-reviews/{review_id}/close", {}, headers
        )

    def create_rebill_request(self, payload, headers):
        return self._request("POST", "/rebill-requests", payload, headers)

    def get_rebill_request(self, rebill_id, headers):
        return self._request("GET", f"/rebill-requests/{rebill_id}", headers=headers)

    def list_rebill_requests(self, headers, params=None):
        return self._request("GET", "/rebill-requests", headers=headers, params=params)

    def approve_rebill_request(self, rebill_id, headers):
        return self._request(
            "POST", f"/rebill-requests/{rebill_id}/approve", {}, headers
        )

    def cancel_rebill_request(self, rebill_id, headers):
        return self._request(
            "POST", f"/rebill-requests/{rebill_id}/cancel", {}, headers
        )


api_client = ApiClient()
