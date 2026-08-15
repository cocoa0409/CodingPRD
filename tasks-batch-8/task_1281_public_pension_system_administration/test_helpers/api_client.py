"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    def __init__(self, base_url=None):
        super().__init__(base_url)
        # The runner restarts the server on the same port before every test
        # (per-test-server isolation). Disable HTTP keep-alive so this
        # session-scoped client never reuses a stale pooled connection that
        # points at the previous, now-dead server process.
        self.session.headers["Connection"] = "close"

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- PensionFund ---
    def create_pension_fund(self, payload, headers):
        return self._request("POST", "/pension-funds", payload, headers)

    def get_pension_fund(self, fund_id, headers):
        return self._request("GET", f"/pension-funds/{fund_id}", headers=headers)

    def update_pension_fund(self, fund_id, payload, headers):
        return self._request("PATCH", f"/pension-funds/{fund_id}", payload, headers)

    def run_cola(self, fund_id, headers):
        return self._request("POST", f"/pension-funds/{fund_id}/cola-runs",
                             headers=headers)

    # --- Employer ---
    def create_employer(self, payload, headers):
        return self._request("POST", "/employers", payload, headers)

    def get_employer(self, employer_id, headers):
        return self._request("GET", f"/employers/{employer_id}", headers=headers)

    def list_employer_members(self, employer_id, headers, params=None):
        return self._request("GET", f"/employers/{employer_id}/members",
                             headers=headers, params=params)

    def list_employer_contribution_reports(self, employer_id, headers, params=None):
        return self._request("GET", f"/employers/{employer_id}/contribution-reports",
                             headers=headers, params=params)

    # --- Member ---
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def update_member(self, member_id, payload, headers):
        return self._request("PATCH", f"/members/{member_id}", payload, headers)

    def get_benefit_estimate(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/benefit-estimate",
                             headers=headers, params=params)

    def list_member_contribution_lines(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/contribution-lines",
                             headers=headers, params=params)

    def list_member_service_purchases(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/service-purchases",
                             headers=headers, params=params)

    def list_member_retirement_applications(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/retirement-applications",
                             headers=headers, params=params)

    def list_member_disability_applications(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/disability-applications",
                             headers=headers, params=params)

    def list_member_benefits(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/benefits",
                             headers=headers, params=params)

    def list_member_beneficiaries(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/beneficiaries",
                             headers=headers, params=params)

    # --- Contribution reporting & reconciliation ---
    def create_contribution_report(self, employer_id, payload, headers):
        return self._request("POST", f"/employers/{employer_id}/contribution-reports",
                             payload, headers)

    def get_contribution_report(self, report_id, headers):
        return self._request("GET", f"/contribution-reports/{report_id}",
                             headers=headers)

    def create_contribution_line(self, report_id, payload, headers):
        return self._request("POST", f"/contribution-reports/{report_id}/lines",
                             payload, headers)

    def list_contribution_lines(self, report_id, headers, params=None):
        return self._request("GET", f"/contribution-reports/{report_id}/lines",
                             headers=headers, params=params)

    def submit_contribution_report(self, report_id, headers):
        return self._request("POST", f"/contribution-reports/{report_id}/submit",
                             headers=headers)

    def review_contribution_line(self, report_id, line_id, payload, headers):
        return self._request(
            "POST",
            f"/contribution-reports/{report_id}/lines/{line_id}/review",
            payload, headers)

    def finalize_contribution_report(self, report_id, headers):
        return self._request("POST", f"/contribution-reports/{report_id}/finalize",
                             headers=headers)

    # --- Service purchase ---
    def create_service_purchase(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/service-purchases",
                             payload, headers)

    def get_service_purchase(self, purchase_id, headers):
        return self._request("GET", f"/service-purchases/{purchase_id}",
                             headers=headers)

    def quote_service_purchase(self, purchase_id, headers):
        return self._request("POST", f"/service-purchases/{purchase_id}/quote",
                             headers=headers)

    def accept_service_purchase(self, purchase_id, payload, headers):
        return self._request("POST", f"/service-purchases/{purchase_id}/accept",
                             payload, headers)

    def apply_payment(self, purchase_id, payload, headers):
        return self._request("POST", f"/service-purchases/{purchase_id}/payments",
                             payload, headers)

    def cancel_service_purchase(self, purchase_id, headers):
        return self._request("POST", f"/service-purchases/{purchase_id}/cancel",
                             headers=headers)

    def list_purchase_payments(self, purchase_id, headers, params=None):
        return self._request("GET", f"/service-purchases/{purchase_id}/payments",
                             headers=headers, params=params)

    # --- Retirement application ---
    def create_retirement_application(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/retirement-applications",
                             payload, headers)

    def get_retirement_application(self, application_id, headers):
        return self._request("GET", f"/retirement-applications/{application_id}",
                             headers=headers)

    def submit_retirement_application(self, application_id, headers):
        return self._request(
            "POST", f"/retirement-applications/{application_id}/submit",
            headers=headers)

    def review_retirement_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/retirement-applications/{application_id}/review",
            payload, headers)

    def approve_retirement_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/retirement-applications/{application_id}/approve",
            payload, headers)

    def cancel_retirement_application(self, application_id, headers):
        return self._request(
            "POST", f"/retirement-applications/{application_id}/cancel",
            headers=headers)

    # --- Disability application ---
    def create_disability_application(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/disability-applications",
                             payload, headers)

    def get_disability_application(self, application_id, headers):
        return self._request("GET", f"/disability-applications/{application_id}",
                             headers=headers)

    def decide_disability_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/disability-applications/{application_id}/decision",
            payload, headers)

    def appeal_disability_application(self, application_id, headers):
        return self._request(
            "POST", f"/disability-applications/{application_id}/appeal",
            headers=headers)

    # --- Benefit ---
    def get_benefit(self, benefit_id, headers):
        return self._request("GET", f"/benefits/{benefit_id}", headers=headers)

    def report_earnings(self, benefit_id, payload, headers):
        return self._request("POST", f"/benefits/{benefit_id}/earnings-reports",
                             payload, headers)

    def reinstate_benefit(self, benefit_id, headers):
        return self._request("POST", f"/benefits/{benefit_id}/reinstate",
                             headers=headers)

    # --- Beneficiary / survivor processing ---
    def create_beneficiary(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/beneficiaries",
                             payload, headers)

    def revoke_beneficiary(self, beneficiary_id, headers):
        return self._request("POST", f"/beneficiaries/{beneficiary_id}/revoke",
                             headers=headers)

    def file_claim(self, beneficiary_id, headers):
        return self._request("POST", f"/beneficiaries/{beneficiary_id}/file-claim",
                             headers=headers)

    def adjudicate_claim(self, beneficiary_id, payload, headers):
        return self._request("POST", f"/beneficiaries/{beneficiary_id}/approve",
                             payload, headers)


api_client = ApiClient()
