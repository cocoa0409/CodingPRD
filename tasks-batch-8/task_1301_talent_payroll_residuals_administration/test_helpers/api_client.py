"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Union agreements
    # ------------------------------------------------------------------
    def create_union_agreement(self, payload, headers):
        return self._request("POST", "/payroll/union-agreements", payload, headers)

    def list_union_agreements(self, headers, params=None):
        return self._request("GET", "/payroll/union-agreements", headers=headers, params=params)

    def ratify_union_agreement(self, agreement_id, headers):
        return self._request("POST", f"/payroll/union-agreements/{agreement_id}/ratify", {}, headers)

    # ------------------------------------------------------------------
    # Productions
    # ------------------------------------------------------------------
    def create_production(self, payload, headers):
        return self._request("POST", "/payroll/productions", payload, headers)

    def list_productions(self, headers, params=None):
        return self._request("GET", "/payroll/productions", headers=headers, params=params)

    def get_production(self, production_id, headers):
        return self._request("GET", f"/payroll/productions/{production_id}", headers=headers)

    def advance_production(self, production_id, headers):
        return self._request("POST", f"/payroll/productions/{production_id}/advance", {}, headers)

    # ------------------------------------------------------------------
    # Performers
    # ------------------------------------------------------------------
    def create_performer(self, payload, headers):
        return self._request("POST", "/payroll/performers", payload, headers)

    def get_performer(self, performer_id, headers):
        return self._request("GET", f"/payroll/performers/{performer_id}", headers=headers)

    # ------------------------------------------------------------------
    # Engagements
    # ------------------------------------------------------------------
    def create_engagement(self, payload, headers):
        return self._request("POST", "/payroll/engagements", payload, headers)

    def list_engagements(self, headers, params=None):
        return self._request("GET", "/payroll/engagements", headers=headers, params=params)

    def get_engagement(self, engagement_id, headers):
        return self._request("GET", f"/payroll/engagements/{engagement_id}", headers=headers)

    def submit_engagement(self, engagement_id, headers):
        return self._request("POST", f"/payroll/engagements/{engagement_id}/submit", {}, headers)

    def approve_engagement(self, engagement_id, headers):
        return self._request("POST", f"/payroll/engagements/{engagement_id}/approve", {}, headers)

    def reject_engagement(self, engagement_id, headers):
        return self._request("POST", f"/payroll/engagements/{engagement_id}/reject", {}, headers)

    # ------------------------------------------------------------------
    # Timecards
    # ------------------------------------------------------------------
    def create_timecard(self, payload, headers):
        return self._request("POST", "/payroll/timecards", payload, headers)

    def list_timecards(self, headers, params=None):
        return self._request("GET", "/payroll/timecards", headers=headers, params=params)

    def get_timecard(self, timecard_id, headers):
        return self._request("GET", f"/payroll/timecards/{timecard_id}", headers=headers)

    def flag_timecard(self, timecard_id, flag_reason, headers):
        return self._request("POST", f"/payroll/timecards/{timecard_id}/flag",
                             {"flag_reason": flag_reason}, headers)

    def revise_timecard(self, timecard_id, payload, headers):
        return self._request("POST", f"/payroll/timecards/{timecard_id}/revise", payload, headers)

    def approve_timecard(self, timecard_id, headers):
        return self._request("POST", f"/payroll/timecards/{timecard_id}/approve", {}, headers)

    # ------------------------------------------------------------------
    # Penalty assessments
    # ------------------------------------------------------------------
    def list_penalty_assessments(self, headers, params=None):
        return self._request("GET", "/payroll/penalty-assessments", headers=headers, params=params)

    def get_penalty_assessment(self, assessment_id, headers):
        return self._request("GET", f"/payroll/penalty-assessments/{assessment_id}", headers=headers)

    def waive_penalty_assessment(self, assessment_id, waiver_reason, headers):
        return self._request("POST", f"/payroll/penalty-assessments/{assessment_id}/waive",
                             {"waiver_reason": waiver_reason}, headers)

    # ------------------------------------------------------------------
    # Residual obligations
    # ------------------------------------------------------------------
    def create_residual_obligation(self, payload, headers):
        return self._request("POST", "/payroll/residual-obligations", payload, headers)

    def list_residual_obligations(self, headers, params=None):
        return self._request("GET", "/payroll/residual-obligations", headers=headers, params=params)

    def get_residual_obligation(self, obligation_id, headers):
        return self._request("GET", f"/payroll/residual-obligations/{obligation_id}", headers=headers)

    def calculate_residual_obligation(self, obligation_id, headers):
        return self._request("POST", f"/payroll/residual-obligations/{obligation_id}/calculate", {}, headers)

    def approve_residual_obligation(self, obligation_id, headers):
        return self._request("POST", f"/payroll/residual-obligations/{obligation_id}/approve", {}, headers)

    def dispute_residual_obligation(self, obligation_id, dispute_reason, headers):
        return self._request("POST", f"/payroll/residual-obligations/{obligation_id}/dispute",
                             {"dispute_reason": dispute_reason}, headers)

    # ------------------------------------------------------------------
    # Pay batches and pay lines
    # ------------------------------------------------------------------
    def create_pay_batch(self, payload, headers):
        return self._request("POST", "/payroll/pay-batches", payload, headers)

    def get_pay_batch(self, batch_id, headers):
        return self._request("GET", f"/payroll/pay-batches/{batch_id}", headers=headers)

    def close_pay_batch(self, batch_id, headers):
        return self._request("POST", f"/payroll/pay-batches/{batch_id}/close", {}, headers)

    def approve_pay_batch(self, batch_id, headers):
        return self._request("POST", f"/payroll/pay-batches/{batch_id}/approve", {}, headers)

    def recall_pay_batch(self, batch_id, headers):
        return self._request("POST", f"/payroll/pay-batches/{batch_id}/recall", {}, headers)

    def disburse_pay_batch(self, batch_id, headers):
        return self._request("POST", f"/payroll/pay-batches/{batch_id}/disburse", {}, headers)

    def list_pay_lines(self, headers, params=None):
        return self._request("GET", "/payroll/pay-lines", headers=headers, params=params)

    def get_pay_line(self, pay_line_id, headers):
        return self._request("GET", f"/payroll/pay-lines/{pay_line_id}", headers=headers)

    # ------------------------------------------------------------------
    # Garnishment orders
    # ------------------------------------------------------------------
    def create_garnishment_order(self, payload, headers):
        return self._request("POST", "/payroll/garnishment-orders", payload, headers)

    def list_garnishment_orders(self, headers, params=None):
        return self._request("GET", "/payroll/garnishment-orders", headers=headers, params=params)

    def get_garnishment_order(self, order_id, headers):
        return self._request("GET", f"/payroll/garnishment-orders/{order_id}", headers=headers)

    def release_garnishment_order(self, order_id, headers):
        return self._request("POST", f"/payroll/garnishment-orders/{order_id}/release", {}, headers)

    # ------------------------------------------------------------------
    # Remittance reports
    # ------------------------------------------------------------------
    def create_remittance_report(self, payload, headers):
        return self._request("POST", "/payroll/remittance-reports", payload, headers)

    def list_remittance_reports(self, headers, params=None):
        return self._request("GET", "/payroll/remittance-reports", headers=headers, params=params)

    def get_remittance_report(self, report_id, headers):
        return self._request("GET", f"/payroll/remittance-reports/{report_id}", headers=headers)

    def submit_remittance_report(self, report_id, headers):
        return self._request("POST", f"/payroll/remittance-reports/{report_id}/submit", {}, headers)

    def acknowledge_remittance_report(self, report_id, headers):
        return self._request("POST", f"/payroll/remittance-reports/{report_id}/acknowledge", {}, headers)

    # ------------------------------------------------------------------
    # Grievance cases
    # ------------------------------------------------------------------
    def create_grievance_case(self, payload, headers):
        return self._request("POST", "/payroll/grievance-cases", payload, headers)

    def list_grievance_cases(self, headers, params=None):
        return self._request("GET", "/payroll/grievance-cases", headers=headers, params=params)

    def get_grievance_case(self, case_id, headers):
        return self._request("GET", f"/payroll/grievance-cases/{case_id}", headers=headers)

    def respond_grievance_case(self, case_id, response_note, headers):
        return self._request("POST", f"/payroll/grievance-cases/{case_id}/respond",
                             {"response_note": response_note}, headers)

    def escalate_grievance_case(self, case_id, headers):
        return self._request("POST", f"/payroll/grievance-cases/{case_id}/escalate", {}, headers)

    def resolve_grievance_case(self, case_id, awarded_amount_cents, headers):
        return self._request("POST", f"/payroll/grievance-cases/{case_id}/resolve",
                             {"awarded_amount_cents": awarded_amount_cents}, headers)


api_client = ApiClient()
