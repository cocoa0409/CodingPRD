"""API client: one method per endpoint defined in the BNPL PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Merchant ----
    def create_merchant(self, payload, headers):
        return self._request("POST", "/merchants", payload, headers)

    def get_merchant(self, merchant_id, headers):
        return self._request("GET", f"/merchants/{merchant_id}", headers=headers)

    def suspend_merchant(self, merchant_id, headers):
        return self._request("POST", f"/merchants/{merchant_id}/suspend", headers=headers)

    # ---- Borrower ----
    def create_borrower(self, payload, headers):
        return self._request("POST", "/borrowers", payload, headers)

    def get_borrower(self, borrower_id, headers):
        return self._request("GET", f"/borrowers/{borrower_id}", headers=headers)

    # ---- Application ----
    def create_application(self, payload, headers):
        return self._request("POST", "/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def decide_application(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/decision", payload, headers)

    def revise_application(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/revise", payload, headers)

    def withdraw_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/withdraw", headers=headers)

    # ---- DisclosureAcceptance ----
    def create_disclosure_acceptance(self, payload, headers):
        return self._request("POST", "/disclosure-acceptances", payload, headers)

    def get_disclosure_acceptance(self, disclosure_id, headers):
        return self._request("GET", f"/disclosure-acceptances/{disclosure_id}", headers=headers)

    def list_disclosure_acceptances(self, headers, params=None):
        return self._request("GET", "/disclosure-acceptances", headers=headers, params=params)

    # ---- Loan ----
    def create_loan(self, payload, headers):
        return self._request("POST", "/loans", payload, headers)

    def get_loan(self, loan_id, headers):
        return self._request("GET", f"/loans/{loan_id}", headers=headers)

    def list_loans(self, headers, params=None):
        return self._request("GET", "/loans", headers=headers, params=params)

    def default_loan(self, loan_id, payload, headers):
        return self._request("POST", f"/loans/{loan_id}/default", payload, headers)

    def cancel_loan(self, loan_id, payload, headers):
        return self._request("POST", f"/loans/{loan_id}/cancel", payload, headers)

    # ---- Installment ----
    def get_installment(self, installment_id, headers):
        return self._request("GET", f"/installments/{installment_id}", headers=headers)

    def list_installments(self, headers, params=None):
        return self._request("GET", "/installments", headers=headers, params=params)

    # ---- Payment ----
    def create_payment(self, payload, headers):
        return self._request("POST", "/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    # ---- Return ----
    def create_return(self, payload, headers):
        return self._request("POST", "/returns", payload, headers)

    def get_return(self, return_id, headers):
        return self._request("GET", f"/returns/{return_id}", headers=headers)

    def list_returns(self, headers, params=None):
        return self._request("GET", "/returns", headers=headers, params=params)

    # ---- AutopayMandate ----
    def create_autopay_mandate(self, payload, headers):
        return self._request("POST", "/autopay-mandates", payload, headers)

    def list_autopay_mandates(self, headers, params=None):
        return self._request("GET", "/autopay-mandates", headers=headers, params=params)

    def get_autopay_mandate(self, mandate_id, headers):
        return self._request("GET", f"/autopay-mandates/{mandate_id}", headers=headers)

    def disable_autopay_mandate(self, mandate_id, headers):
        return self._request("POST", f"/autopay-mandates/{mandate_id}/disable", headers=headers)

    # ---- MerchantSettlement ----
    def get_merchant_settlement(self, settlement_id, headers):
        return self._request("GET", f"/merchant-settlements/{settlement_id}", headers=headers)

    def list_merchant_settlements(self, headers, params=None):
        return self._request("GET", "/merchant-settlements", headers=headers, params=params)

    def release_merchant_settlement(self, settlement_id, headers):
        return self._request("POST", f"/merchant-settlements/{settlement_id}/release", headers=headers)

    # ---- Servicer operator endpoints ----
    def run_autopay_sweep(self, headers):
        return self._request("POST", "/_servicer/run_autopay_sweep", headers=headers)

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
