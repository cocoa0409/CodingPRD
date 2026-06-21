"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/loan-servicing"


class ApiClient(GenericApiClient):
    # ─── Clock (test-driving) ─────────────────────────────
    def set_current_utc(self, to_iso8601: str, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ─── Borrowers ─────────────────────────────────────────
    def create_borrower(self, payload, headers):
        return self._request("POST", f"{PREFIX}/borrowers", payload, headers)

    def get_borrower(self, borrower_id, headers):
        return self._request("GET", f"{PREFIX}/borrowers/{borrower_id}", headers=headers)

    def list_borrowers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/borrowers", headers=headers, params=params)

    # ─── Loans ─────────────────────────────────────────────
    def create_loan(self, payload, headers):
        return self._request("POST", f"{PREFIX}/loans", payload, headers)

    def get_loan(self, loan_id, headers):
        return self._request("GET", f"{PREFIX}/loans/{loan_id}", headers=headers)

    def list_loans(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/loans", headers=headers, params=params)

    def enter_school(self, loan_id, headers):
        return self._request("POST", f"{PREFIX}/loans/{loan_id}/enter-school",
                             {}, headers)

    def graduate(self, loan_id, headers):
        return self._request("POST", f"{PREFIX}/loans/{loan_id}/graduate", {}, headers)

    def start_repayment(self, loan_id, headers):
        return self._request("POST", f"{PREFIX}/loans/{loan_id}/start-repayment",
                             {}, headers)

    def request_deferment(self, loan_id, headers):
        return self._request("POST", f"{PREFIX}/loans/{loan_id}/request-deferment",
                             {}, headers)

    def request_forbearance(self, loan_id, headers):
        return self._request("POST", f"{PREFIX}/loans/{loan_id}/request-forbearance",
                             {}, headers)

    def resume_repayment(self, loan_id, headers):
        return self._request("POST", f"{PREFIX}/loans/{loan_id}/resume-repayment",
                             {}, headers)

    def declare_default(self, loan_id, headers):
        return self._request("POST", f"{PREFIX}/loans/{loan_id}/declare-default",
                             {}, headers)

    def rehabilitate(self, loan_id, headers):
        return self._request("POST", f"{PREFIX}/loans/{loan_id}/rehabilitate",
                             {}, headers)

    def list_status_changes(self, loan_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/loans/{loan_id}/status-changes",
                             headers=headers, params=params)

    # ─── Repayment Plans ──────────────────────────────────
    def create_repayment_plan(self, payload, headers):
        return self._request("POST", f"{PREFIX}/repayment-plans", payload, headers)

    def activate_repayment_plan(self, plan_id, headers):
        return self._request("POST", f"{PREFIX}/repayment-plans/{plan_id}/activate",
                             {}, headers)

    def get_repayment_plan(self, plan_id, headers):
        return self._request("GET", f"{PREFIX}/repayment-plans/{plan_id}",
                             headers=headers)

    def list_repayment_plans(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/repayment-plans",
                             headers=headers, params=params)

    # ─── Income Certifications ────────────────────────────
    def create_income_certification(self, payload, headers):
        return self._request("POST", f"{PREFIX}/income-certifications",
                             payload, headers)

    def certify_income_certification(self, cert_id, headers):
        return self._request("POST",
                             f"{PREFIX}/income-certifications/{cert_id}/certify",
                             {}, headers)

    def get_income_certification(self, cert_id, headers):
        return self._request("GET", f"{PREFIX}/income-certifications/{cert_id}",
                             headers=headers)

    def list_income_certifications(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/income-certifications",
                             headers=headers, params=params)

    # ─── Qualifying Employments ───────────────────────────
    def create_qualifying_employment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/qualifying-employments",
                             payload, headers)

    def certify_qualifying_employment(self, qe_id, headers):
        return self._request("POST",
                             f"{PREFIX}/qualifying-employments/{qe_id}/certify",
                             {}, headers)

    def get_qualifying_employment(self, qe_id, headers):
        return self._request("GET", f"{PREFIX}/qualifying-employments/{qe_id}",
                             headers=headers)

    def list_qualifying_employments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/qualifying-employments",
                             headers=headers, params=params)

    # ─── Payments ─────────────────────────────────────────
    def create_payment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/payments", payload, headers)

    def apply_payment(self, payment_id, headers):
        return self._request("POST", f"{PREFIX}/payments/{payment_id}/apply",
                             {}, headers)

    def reverse_payment(self, payment_id, headers):
        return self._request("POST", f"{PREFIX}/payments/{payment_id}/reverse",
                             {}, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"{PREFIX}/payments/{payment_id}",
                             headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/payments",
                             headers=headers, params=params)

    # ─── Discharge Applications ───────────────────────────
    def create_discharge_application(self, payload, headers):
        return self._request("POST", f"{PREFIX}/discharge-applications",
                             payload, headers)

    def begin_review_discharge(self, app_id, headers):
        return self._request(
            "POST",
            f"{PREFIX}/discharge-applications/{app_id}/begin-review",
            {}, headers)

    def approve_discharge(self, app_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/discharge-applications/{app_id}/approve",
            payload, headers)

    def deny_discharge(self, app_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/discharge-applications/{app_id}/deny",
            payload, headers)

    def get_discharge_application(self, app_id, headers):
        return self._request("GET", f"{PREFIX}/discharge-applications/{app_id}",
                             headers=headers)

    def list_discharge_applications(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/discharge-applications",
                             headers=headers, params=params)


api_client = ApiClient()
