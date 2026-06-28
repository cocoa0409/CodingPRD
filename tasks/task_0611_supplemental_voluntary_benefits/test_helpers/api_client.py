"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; the base _request() is inherited.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- Employer ---
    def create_employer(self, payload, headers):
        return self._request("POST", "/benefits/employers", payload, headers)

    def get_employer(self, employer_id, headers):
        return self._request(
            "GET", f"/benefits/employers/{employer_id}", headers=headers
        )

    # --- PlanProduct ---
    def create_plan_product(self, payload, headers):
        return self._request("POST", "/benefits/plan-products", payload, headers)

    def list_plan_products(self, headers, params=None):
        return self._request(
            "GET", "/benefits/plan-products", headers=headers, params=params
        )

    def get_plan_product(self, product_id, headers):
        return self._request(
            "GET", f"/benefits/plan-products/{product_id}", headers=headers
        )

    def open_plan_product(self, product_id, headers):
        return self._request(
            "POST", f"/benefits/plan-products/{product_id}/open", {}, headers
        )

    def close_plan_product(self, product_id, headers):
        return self._request(
            "POST", f"/benefits/plan-products/{product_id}/close", {}, headers
        )

    # --- BenefitScheduleItem ---
    def create_schedule_item(self, payload, headers):
        return self._request("POST", "/benefits/schedule-items", payload, headers)

    def list_schedule_items(self, headers, params=None):
        return self._request(
            "GET", "/benefits/schedule-items", headers=headers, params=params
        )

    def get_schedule_item(self, item_id, headers):
        return self._request(
            "GET", f"/benefits/schedule-items/{item_id}", headers=headers
        )

    # --- EnrollmentPeriod ---
    def create_enrollment_period(self, payload, headers):
        return self._request("POST", "/benefits/enrollment-periods", payload, headers)

    def list_enrollment_periods(self, headers, params=None):
        return self._request(
            "GET", "/benefits/enrollment-periods", headers=headers, params=params
        )

    def get_enrollment_period(self, period_id, headers):
        return self._request(
            "GET", f"/benefits/enrollment-periods/{period_id}", headers=headers
        )

    def open_enrollment_period(self, period_id, headers):
        return self._request(
            "POST", f"/benefits/enrollment-periods/{period_id}/open", {}, headers
        )

    def close_enrollment_period(self, period_id, headers):
        return self._request(
            "POST", f"/benefits/enrollment-periods/{period_id}/close", {}, headers
        )

    # --- Employee ---
    def create_employee(self, payload, headers):
        return self._request("POST", "/benefits/employees", payload, headers)

    def list_employees(self, headers, params=None):
        return self._request(
            "GET", "/benefits/employees", headers=headers, params=params
        )

    def get_employee(self, employee_id, headers):
        return self._request(
            "GET", f"/benefits/employees/{employee_id}", headers=headers
        )

    def terminate_employee(self, employee_id, headers):
        return self._request(
            "POST", f"/benefits/employees/{employee_id}/terminate", {}, headers
        )

    # --- DisbursementAccount ---
    def create_disbursement_account(self, payload, headers):
        return self._request(
            "POST", "/benefits/disbursement-accounts", payload, headers
        )

    def list_disbursement_accounts(self, headers, params=None):
        return self._request(
            "GET", "/benefits/disbursement-accounts", headers=headers, params=params
        )

    def get_disbursement_account(self, account_id, headers):
        return self._request(
            "GET", f"/benefits/disbursement-accounts/{account_id}", headers=headers
        )

    def verify_disbursement_account(self, account_id, headers):
        return self._request(
            "POST",
            f"/benefits/disbursement-accounts/{account_id}/verify",
            {},
            headers,
        )

    # --- Enrollment ---
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/benefits/enrollments", payload, headers)

    def list_enrollments(self, headers, params=None):
        return self._request(
            "GET", "/benefits/enrollments", headers=headers, params=params
        )

    def get_enrollment(self, enrollment_id, headers):
        return self._request(
            "GET", f"/benefits/enrollments/{enrollment_id}", headers=headers
        )

    def activate_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/benefits/enrollments/{enrollment_id}/activate", {}, headers
        )

    def decline_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/benefits/enrollments/{enrollment_id}/decline", {}, headers
        )

    def terminate_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/benefits/enrollments/{enrollment_id}/terminate", {}, headers
        )

    # --- PayrollDeduction ---
    def post_payroll_deduction(self, enrollment_id, payload, headers):
        return self._request(
            "POST",
            f"/benefits/enrollments/{enrollment_id}/payroll-deductions",
            payload,
            headers,
        )

    def list_payroll_deductions(self, headers, params=None):
        return self._request(
            "GET", "/benefits/payroll-deductions", headers=headers, params=params
        )

    def get_payroll_deduction(self, deduction_id, headers):
        return self._request(
            "GET", f"/benefits/payroll-deductions/{deduction_id}", headers=headers
        )

    # --- PortabilityConversion ---
    def create_portability_conversion(self, enrollment_id, payload, headers):
        return self._request(
            "POST",
            f"/benefits/enrollments/{enrollment_id}/portability-conversions",
            payload,
            headers,
        )

    def list_portability_conversions(self, headers, params=None):
        return self._request(
            "GET", "/benefits/portability-conversions", headers=headers, params=params
        )

    def get_portability_conversion(self, conversion_id, headers):
        return self._request(
            "GET",
            f"/benefits/portability-conversions/{conversion_id}",
            headers=headers,
        )

    # --- Section125Election ---
    def list_section125_elections(self, headers, params=None):
        return self._request(
            "GET", "/benefits/section125-elections", headers=headers, params=params
        )

    def get_section125_election(self, election_id, headers):
        return self._request(
            "GET", f"/benefits/section125-elections/{election_id}", headers=headers
        )

    # --- Claim ---
    def create_claim(self, payload, headers):
        return self._request("POST", "/benefits/claims", payload, headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/benefits/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/benefits/claims/{claim_id}", headers=headers)

    def start_review_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/benefits/claims/{claim_id}/start-review", {}, headers
        )

    def approve_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/benefits/claims/{claim_id}/approve", {}, headers
        )

    def deny_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/benefits/claims/{claim_id}/deny", payload, headers
        )

    def reopen_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/benefits/claims/{claim_id}/reopen", {}, headers
        )

    def void_claim(self, claim_id, headers):
        return self._request("POST", f"/benefits/claims/{claim_id}/void", {}, headers)

    def disburse_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/benefits/claims/{claim_id}/disburse", {}, headers
        )

    # --- Disbursement ---
    def list_disbursements(self, headers, params=None):
        return self._request(
            "GET", "/benefits/disbursements", headers=headers, params=params
        )

    def get_disbursement(self, disbursement_id, headers):
        return self._request(
            "GET", f"/benefits/disbursements/{disbursement_id}", headers=headers
        )

    def return_disbursement(self, disbursement_id, headers):
        return self._request(
            "POST", f"/benefits/disbursements/{disbursement_id}/return", {}, headers
        )


api_client = ApiClient()
