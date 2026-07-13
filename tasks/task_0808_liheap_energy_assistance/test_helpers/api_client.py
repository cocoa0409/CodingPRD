"""API client: one method per LIHEAP endpoint."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- FundingPool ------------------------------------------------------
    def create_funding_pool(self, payload, headers):
        return self._request("POST", "/liheap/funding-pools", payload, headers)

    def get_funding_pool(self, pool_id, headers):
        return self._request("GET", f"/liheap/funding-pools/{pool_id}", headers=headers)

    def close_funding_pool(self, pool_id, headers):
        return self._request("POST", f"/liheap/funding-pools/{pool_id}/close", {}, headers)

    # ---- Household --------------------------------------------------------
    def create_household(self, payload, headers):
        return self._request("POST", "/liheap/households", payload, headers)

    def get_household(self, household_id, headers):
        return self._request("GET", f"/liheap/households/{household_id}", headers=headers)

    # ---- Application ------------------------------------------------------
    def create_application(self, payload, headers):
        return self._request("POST", "/liheap/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/liheap/applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/liheap/applications", headers=headers, params=params)

    def submit_application(self, application_id, headers):
        return self._request("POST", f"/liheap/applications/{application_id}/submit", {}, headers)

    def request_info_application(self, application_id, headers):
        return self._request("POST", f"/liheap/applications/{application_id}/request-info", {}, headers)

    def approve_application(self, application_id, headers):
        return self._request("POST", f"/liheap/applications/{application_id}/approve", {}, headers)

    def deny_application(self, application_id, headers, payload=None):
        return self._request("POST", f"/liheap/applications/{application_id}/deny", payload or {}, headers)

    # ---- IncomeDocument ---------------------------------------------------
    def create_income_document(self, payload, headers):
        return self._request("POST", "/liheap/income-documents", payload, headers)

    def get_income_document(self, doc_id, headers):
        return self._request("GET", f"/liheap/income-documents/{doc_id}", headers=headers)

    def list_income_documents(self, headers, params=None):
        return self._request("GET", "/liheap/income-documents", headers=headers, params=params)

    def verify_income_document(self, doc_id, payload, headers):
        return self._request("POST", f"/liheap/income-documents/{doc_id}/verify", payload, headers)

    # ---- Vendor -----------------------------------------------------------
    def create_vendor(self, payload, headers):
        return self._request("POST", "/liheap/vendors", payload, headers)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/liheap/vendors/{vendor_id}", headers=headers)

    def enroll_vendor(self, vendor_id, headers):
        return self._request("POST", f"/liheap/vendors/{vendor_id}/enroll", {}, headers)

    # ---- UtilityAccount ---------------------------------------------------
    def create_utility_account(self, payload, headers):
        return self._request("POST", "/liheap/utility-accounts", payload, headers)

    def get_utility_account(self, account_id, headers):
        return self._request("GET", f"/liheap/utility-accounts/{account_id}", headers=headers)

    def list_utility_accounts(self, headers, params=None):
        return self._request("GET", "/liheap/utility-accounts", headers=headers, params=params)

    def report_status_utility_account(self, account_id, payload, headers):
        return self._request("POST", f"/liheap/utility-accounts/{account_id}/report-status", payload, headers)

    # ---- Pledge -----------------------------------------------------------
    def create_pledge(self, payload, headers):
        return self._request("POST", "/liheap/pledges", payload, headers)

    def get_pledge(self, pledge_id, headers):
        return self._request("GET", f"/liheap/pledges/{pledge_id}", headers=headers)

    def list_pledges(self, headers, params=None):
        return self._request("GET", "/liheap/pledges", headers=headers, params=params)

    def cancel_pledge(self, pledge_id, headers):
        return self._request("POST", f"/liheap/pledges/{pledge_id}/cancel", {}, headers)

    # ---- Payment ----------------------------------------------------------
    def create_payment(self, payload, headers):
        return self._request("POST", "/liheap/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/liheap/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/liheap/payments", headers=headers, params=params)

    def remit_payment(self, payment_id, headers):
        return self._request("POST", f"/liheap/payments/{payment_id}/remit", {}, headers)

    def return_payment(self, payment_id, headers):
        return self._request("POST", f"/liheap/payments/{payment_id}/return", {}, headers)

    # ---- BillCredit -------------------------------------------------------
    def get_bill_credit(self, credit_id, headers):
        return self._request("GET", f"/liheap/bill-credits/{credit_id}", headers=headers)

    def list_bill_credits(self, headers, params=None):
        return self._request("GET", "/liheap/bill-credits", headers=headers, params=params)

    # ---- CrisisBenefit ----------------------------------------------------
    def create_crisis_benefit(self, payload, headers):
        return self._request("POST", "/liheap/crisis-benefits", payload, headers)

    def get_crisis_benefit(self, crisis_id, headers):
        return self._request("GET", f"/liheap/crisis-benefits/{crisis_id}", headers=headers)

    def list_crisis_benefits(self, headers, params=None):
        return self._request("GET", "/liheap/crisis-benefits", headers=headers, params=params)

    def resolve_crisis_benefit(self, crisis_id, headers):
        return self._request("POST", f"/liheap/crisis-benefits/{crisis_id}/resolve", {}, headers)

    def breach_crisis_benefit(self, crisis_id, headers):
        return self._request("POST", f"/liheap/crisis-benefits/{crisis_id}/breach", {}, headers)

    # ---- WeatherizationReferral ------------------------------------------
    def create_weatherization_referral(self, payload, headers):
        return self._request("POST", "/liheap/weatherization-referrals", payload, headers)

    def get_weatherization_referral(self, referral_id, headers):
        return self._request("GET", f"/liheap/weatherization-referrals/{referral_id}", headers=headers)

    def list_weatherization_referrals(self, headers, params=None):
        return self._request("GET", "/liheap/weatherization-referrals", headers=headers, params=params)

    def schedule_weatherization_referral(self, referral_id, headers):
        return self._request("POST", f"/liheap/weatherization-referrals/{referral_id}/schedule", {}, headers)

    # ---- Logical clock (test-driving) ------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
