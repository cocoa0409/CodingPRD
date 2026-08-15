"""API client: one method per endpoint defined in the PRD (§4 routing table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock & ops ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/assistance/_clock/set_current_utc", payload, headers)

    def run_daily_sweep(self, payload, headers):
        return self._request("POST", "/assistance/ops/daily-sweep", payload, headers)

    # --- accounts ---
    def create_account(self, payload, headers):
        return self._request("POST", "/assistance/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/assistance/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/assistance/accounts", headers=headers, params=params)

    def post_charge(self, account_id, payload, headers):
        return self._request("POST", f"/assistance/accounts/{account_id}/charges", payload, headers)

    def reconnect_account(self, account_id, payload, headers):
        return self._request("POST", f"/assistance/accounts/{account_id}/reconnect", payload, headers)

    # --- assistance applications ---
    def create_application(self, payload, headers):
        return self._request("POST", "/assistance/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/assistance/applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/assistance/applications", headers=headers, params=params)

    def begin_review(self, application_id, headers):
        return self._request("POST", f"/assistance/applications/{application_id}/begin-review", {}, headers)

    def request_documents(self, application_id, headers):
        return self._request("POST", f"/assistance/applications/{application_id}/request-documents", {}, headers)

    def submit_documents(self, application_id, headers):
        return self._request("POST", f"/assistance/applications/{application_id}/submit-documents", {}, headers)

    def verify_application(self, application_id, headers):
        return self._request("POST", f"/assistance/applications/{application_id}/verify", {}, headers)

    def deny_application(self, application_id, payload, headers):
        return self._request("POST", f"/assistance/applications/{application_id}/deny", payload, headers)

    def withdraw_application(self, application_id, headers):
        return self._request("POST", f"/assistance/applications/{application_id}/withdraw", {}, headers)

    # --- enrollments ---
    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/assistance/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/assistance/enrollments", headers=headers, params=params)

    def activate_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/assistance/enrollments/{enrollment_id}/activate", {}, headers)

    def recertify_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"/assistance/enrollments/{enrollment_id}/recertify", payload, headers)

    def terminate_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/assistance/enrollments/{enrollment_id}/terminate", {}, headers)

    # --- deferred payment agreements ---
    def create_dpa(self, payload, headers):
        return self._request("POST", "/assistance/dpas", payload, headers)

    def get_dpa(self, dpa_id, headers):
        return self._request("GET", f"/assistance/dpas/{dpa_id}", headers=headers)

    def list_dpas(self, headers, params=None):
        return self._request("GET", "/assistance/dpas", headers=headers, params=params)

    def cancel_dpa(self, dpa_id, headers):
        return self._request("POST", f"/assistance/dpas/{dpa_id}/cancel", {}, headers)

    def reinstate_dpa(self, dpa_id, headers):
        return self._request("POST", f"/assistance/dpas/{dpa_id}/reinstate", {}, headers)

    def list_forgiveness_credits(self, dpa_id, headers, params=None):
        return self._request("GET", f"/assistance/dpas/{dpa_id}/forgiveness-credits",
                             headers=headers, params=params)

    # --- payments ---
    def create_payment(self, payload, headers):
        return self._request("POST", "/assistance/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/assistance/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/assistance/payments", headers=headers, params=params)

    # --- medical certificates ---
    def create_certificate(self, payload, headers):
        return self._request("POST", "/assistance/medical-certificates", payload, headers)

    def get_certificate(self, certificate_id, headers):
        return self._request("GET", f"/assistance/medical-certificates/{certificate_id}", headers=headers)

    def list_certificates(self, headers, params=None):
        return self._request("GET", "/assistance/medical-certificates", headers=headers, params=params)

    def renew_certificate(self, certificate_id, headers):
        return self._request("POST", f"/assistance/medical-certificates/{certificate_id}/renew", {}, headers)

    def revoke_certificate(self, certificate_id, headers):
        return self._request("POST", f"/assistance/medical-certificates/{certificate_id}/revoke", {}, headers)

    # --- shutoff orders ---
    def create_shutoff_order(self, payload, headers):
        return self._request("POST", "/assistance/shutoff-orders", payload, headers)

    def get_shutoff_order(self, order_id, headers):
        return self._request("GET", f"/assistance/shutoff-orders/{order_id}", headers=headers)

    def list_shutoff_orders(self, headers, params=None):
        return self._request("GET", "/assistance/shutoff-orders", headers=headers, params=params)

    def execute_shutoff_order(self, order_id, headers):
        return self._request("POST", f"/assistance/shutoff-orders/{order_id}/execute", {}, headers)

    def cancel_shutoff_order(self, order_id, headers):
        return self._request("POST", f"/assistance/shutoff-orders/{order_id}/cancel", {}, headers)

    # --- funding sources & allocations ---
    def create_funding_source(self, payload, headers):
        return self._request("POST", "/assistance/funding-sources", payload, headers)

    def get_funding_source(self, source_id, headers):
        return self._request("GET", f"/assistance/funding-sources/{source_id}", headers=headers)

    def list_funding_sources(self, headers, params=None):
        return self._request("GET", "/assistance/funding-sources", headers=headers, params=params)

    def suspend_funding_source(self, source_id, headers):
        return self._request("POST", f"/assistance/funding-sources/{source_id}/suspend", {}, headers)

    def close_funding_source(self, source_id, headers):
        return self._request("POST", f"/assistance/funding-sources/{source_id}/close", {}, headers)

    def get_funding_report(self, source_id, headers):
        return self._request("GET", f"/assistance/funding-sources/{source_id}/report", headers=headers)

    def create_fund_allocations(self, payload, headers):
        return self._request("POST", "/assistance/fund-allocations", payload, headers)

    def get_fund_allocation(self, allocation_id, headers):
        return self._request("GET", f"/assistance/fund-allocations/{allocation_id}", headers=headers)

    def list_fund_allocations(self, headers, params=None):
        return self._request("GET", "/assistance/fund-allocations", headers=headers, params=params)

    def disburse_allocation(self, allocation_id, headers):
        return self._request("POST", f"/assistance/fund-allocations/{allocation_id}/disburse", {}, headers)

    def release_allocation(self, allocation_id, headers):
        return self._request("POST", f"/assistance/fund-allocations/{allocation_id}/release", {}, headers)

    # --- referrals ---
    def create_referral(self, payload, headers):
        return self._request("POST", "/assistance/referrals", payload, headers)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/assistance/referrals/{referral_id}", headers=headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/assistance/referrals", headers=headers, params=params)

    def complete_referral(self, referral_id, headers):
        return self._request("POST", f"/assistance/referrals/{referral_id}/complete", {}, headers)


api_client = ApiClient()
