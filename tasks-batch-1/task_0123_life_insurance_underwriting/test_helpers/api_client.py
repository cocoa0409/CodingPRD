"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Products ─────────────────────────────────────
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    # ─── Underwriters ─────────────────────────────────
    def create_underwriter(self, payload, headers):
        return self._request("POST", "/underwriters", payload, headers)

    def get_underwriter(self, underwriter_id, headers):
        return self._request("GET", f"/underwriters/{underwriter_id}", headers=headers)

    # ─── Applicants ───────────────────────────────────
    def create_applicant(self, payload, headers):
        return self._request("POST", "/applicants", payload, headers)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"/applicants/{applicant_id}", headers=headers)

    # ─── Applications (hub) ───────────────────────────
    def create_application(self, payload, headers):
        return self._request("POST", "/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def submit_application(self, application_id, headers, payload=None):
        return self._request("POST", f"/applications/{application_id}/submit", payload or {}, headers)

    def order_exam(self, application_id, headers, payload=None):
        return self._request("POST", f"/applications/{application_id}/order-exam", payload or {}, headers)

    def begin_review(self, application_id, headers, payload=None):
        return self._request("POST", f"/applications/{application_id}/begin-review", payload or {}, headers)

    def approve_application(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/approve", payload, headers)

    def postpone_application(self, application_id, headers, payload=None):
        return self._request("POST", f"/applications/{application_id}/postpone", payload or {}, headers)

    def decline_application(self, application_id, headers, payload=None):
        return self._request("POST", f"/applications/{application_id}/decline", payload or {}, headers)

    def issue_application(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/issue", payload, headers)

    # ─── ParamedExams ─────────────────────────────────
    def create_paramed_exam(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/paramed-exams", payload, headers)

    def list_paramed_exams(self, application_id, headers, params=None):
        return self._request("GET", f"/applications/{application_id}/paramed-exams", headers=headers, params=params)

    def get_paramed_exam(self, exam_id, headers):
        return self._request("GET", f"/paramed-exams/{exam_id}", headers=headers)

    def complete_paramed_exam(self, exam_id, headers, payload=None):
        return self._request("POST", f"/paramed-exams/{exam_id}/complete", payload or {}, headers)

    def cancel_paramed_exam(self, exam_id, headers, payload=None):
        return self._request("POST", f"/paramed-exams/{exam_id}/cancel", payload or {}, headers)

    # ─── MIBChecks ────────────────────────────────────
    def create_mib_check(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/mib-checks", payload, headers)

    def list_mib_checks(self, application_id, headers, params=None):
        return self._request("GET", f"/applications/{application_id}/mib-checks", headers=headers, params=params)

    # ─── RiskAssessment ───────────────────────────────
    def get_risk_assessment(self, application_id, headers, params=None):
        return self._request("GET", f"/applications/{application_id}/risk-assessment", headers=headers, params=params)

    # ─── Policies ─────────────────────────────────────
    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/policies/{policy_id}", headers=headers)

    def list_policies_for_application(self, application_id, headers, params=None):
        return self._request("GET", f"/applications/{application_id}/policies", headers=headers, params=params)

    def create_premium_payment(self, policy_id, payload, headers):
        return self._request("POST", f"/policies/{policy_id}/premium-payments", payload, headers)

    def list_premium_payments(self, policy_id, headers, params=None):
        return self._request("GET", f"/policies/{policy_id}/premium-payments", headers=headers, params=params)

    def reinstate_policy(self, policy_id, payload, headers):
        return self._request("POST", f"/policies/{policy_id}/reinstate", payload, headers)

    # ─── Beneficiaries ────────────────────────────────
    def create_beneficiary(self, policy_id, payload, headers):
        return self._request("POST", f"/policies/{policy_id}/beneficiaries", payload, headers)

    def list_beneficiaries(self, policy_id, headers, params=None):
        return self._request("GET", f"/policies/{policy_id}/beneficiaries", headers=headers, params=params)

    def delete_beneficiary(self, beneficiary_id, headers):
        return self._request("DELETE", f"/beneficiaries/{beneficiary_id}", headers=headers)

    # ─── PolicyLoans ──────────────────────────────────
    def create_policy_loan(self, policy_id, payload, headers):
        return self._request("POST", f"/policies/{policy_id}/policy-loans", payload, headers)

    def list_policy_loans(self, policy_id, headers, params=None):
        return self._request("GET", f"/policies/{policy_id}/policy-loans", headers=headers, params=params)

    def repay_policy_loan(self, loan_id, headers, payload=None):
        return self._request("POST", f"/policy-loans/{loan_id}/repay", payload or {}, headers)

    # ─── CashValueEntries ─────────────────────────────
    def list_cash_value_entries(self, policy_id, headers, params=None):
        return self._request("GET", f"/policies/{policy_id}/cash-value-entries", headers=headers, params=params)

    # ─── Test-driving clock ───────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
