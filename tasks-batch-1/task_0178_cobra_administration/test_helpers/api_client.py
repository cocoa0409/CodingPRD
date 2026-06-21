"""API client: one method per endpoint defined in the COBRA Administration
PRD (§4). The base _request() method is inherited from the framework's
GenericApiClient.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- test-driving clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set", payload, headers)

    # ---- plans ----
    def create_plan(self, payload, headers):
        return self._request("POST", "/plans", payload, headers)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/plans/{plan_id}", headers=headers)

    def list_plan_beneficiaries(self, plan_id, headers, params=None):
        return self._request("GET", f"/plans/{plan_id}/beneficiaries", headers=headers, params=params)

    def tick(self, plan_id, headers):
        return self._request("POST", f"/plans/{plan_id}/tick", {}, headers)

    # ---- beneficiaries ----
    def create_beneficiary(self, payload, headers):
        return self._request("POST", "/beneficiaries", payload, headers)

    def get_beneficiary(self, beneficiary_id, headers):
        return self._request("GET", f"/beneficiaries/{beneficiary_id}", headers=headers)

    def list_beneficiary_certificates(self, beneficiary_id, headers, params=None):
        return self._request("GET", f"/beneficiaries/{beneficiary_id}/certificates", headers=headers, params=params)

    # ---- events ----
    def create_event(self, payload, headers):
        return self._request("POST", "/events", payload, headers)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/events/{event_id}", headers=headers)

    def list_events(self, headers, params=None):
        return self._request("GET", "/events", headers=headers, params=params)

    def send_notice(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/send-notice", {}, headers)

    def void_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/void", {}, headers)

    # ---- notices ----
    def get_notice(self, notice_id, headers):
        return self._request("GET", f"/notices/{notice_id}", headers=headers)

    def list_notices(self, headers, params=None):
        return self._request("GET", "/notices", headers=headers, params=params)

    def elect(self, notice_id, headers):
        return self._request("POST", f"/notices/{notice_id}/elect", {}, headers)

    # ---- enrollments ----
    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def list_enrollment_certificates(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/enrollments/{enrollment_id}/certificates", headers=headers, params=params)

    def apply_disability_extension(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/apply-disability-extension", payload, headers)

    def terminate_early(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/terminate-early", payload, headers)

    def create_subsidy(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/subsidies", payload, headers)

    # ---- subsidies ----
    def revoke_subsidy(self, subsidy_id, headers):
        return self._request("POST", f"/subsidies/{subsidy_id}/revoke", {}, headers)

    def get_subsidy(self, subsidy_id, headers):
        return self._request("GET", f"/subsidies/{subsidy_id}", headers=headers)

    def list_subsidies(self, headers, params=None):
        return self._request("GET", "/subsidies", headers=headers, params=params)

    # ---- accounts / invoices / payments / refunds ----
    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/accounts", headers=headers, params=params)

    def create_invoice(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def create_payment(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    def refund(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/refund", payload, headers)


api_client = ApiClient()
