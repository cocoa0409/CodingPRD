"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Borrowers ---
    def create_borrower(self, payload, headers):
        return self._request("POST", "/borrowers", payload, headers)

    def get_borrower(self, borrower_id, headers):
        return self._request("GET", f"/borrowers/{borrower_id}", headers=headers)

    def suspend_borrower(self, borrower_id, headers):
        return self._request("POST", f"/borrowers/{borrower_id}/suspend", headers=headers)

    # --- Loan applications ---
    def create_loan_application(self, payload, headers):
        return self._request("POST", "/loan-applications", payload, headers)

    def get_loan_application(self, application_id, headers):
        return self._request("GET", f"/loan-applications/{application_id}", headers=headers)

    def list_loan_applications(self, headers, params=None):
        return self._request("GET", "/loan-applications", headers=headers, params=params)

    def score_application(self, application_id, headers):
        return self._request("POST", f"/loan-applications/{application_id}/score", headers=headers)

    def approve_application(self, application_id, headers):
        return self._request("POST", f"/loan-applications/{application_id}/approve", headers=headers)

    def reject_application(self, application_id, headers):
        return self._request("POST", f"/loan-applications/{application_id}/reject", headers=headers)

    # --- Loans ---
    def get_loan(self, loan_id, headers):
        return self._request("GET", f"/loans/{loan_id}", headers=headers)

    def list_loans(self, headers, params=None):
        return self._request("GET", "/loans", headers=headers, params=params)

    def get_schedule(self, loan_id, headers):
        return self._request("GET", f"/loans/{loan_id}/schedule", headers=headers)

    def disburse_loan(self, loan_id, headers):
        return self._request("POST", f"/loans/{loan_id}/disburse", headers=headers)

    def assess_late_fee(self, loan_id, headers):
        return self._request("POST", f"/loans/{loan_id}/assess-late-fee", headers=headers)

    def charge_off_loan(self, loan_id, headers):
        return self._request("POST", f"/loans/{loan_id}/charge-off", headers=headers)

    def create_repayment(self, loan_id, payload, headers):
        return self._request("POST", f"/loans/{loan_id}/repayments", payload, headers)

    def get_repayment(self, repayment_id, headers):
        return self._request("GET", f"/repayments/{repayment_id}", headers=headers)

    def list_loan_repayments(self, loan_id, headers, params=None):
        return self._request("GET", f"/loans/{loan_id}/repayments", headers=headers, params=params)

    def list_loan_investments(self, loan_id, headers, params=None):
        return self._request("GET", f"/loans/{loan_id}/investments", headers=headers, params=params)

    # --- Investors ---
    def create_investor(self, payload, headers):
        return self._request("POST", "/investors", payload, headers)

    def get_investor(self, investor_id, headers):
        return self._request("GET", f"/investors/{investor_id}", headers=headers)

    def suspend_investor(self, investor_id, headers):
        return self._request("POST", f"/investors/{investor_id}/suspend", headers=headers)

    def deposit(self, investor_id, payload, headers):
        return self._request("POST", f"/investors/{investor_id}/deposit", payload, headers)

    # --- Investments ---
    def create_investment(self, payload, headers):
        return self._request("POST", "/investments", payload, headers)

    def get_investment(self, investment_id, headers):
        return self._request("GET", f"/investments/{investment_id}", headers=headers)

    def list_investments(self, headers, params=None):
        return self._request("GET", "/investments", headers=headers, params=params)

    def list_repayment_allocations(self, repayment_id, headers, params=None):
        return self._request("GET", f"/repayments/{repayment_id}/allocations", headers=headers, params=params)

    def list_investment_allocations(self, investment_id, headers, params=None):
        return self._request("GET", f"/investments/{investment_id}/allocations", headers=headers, params=params)

    # --- Compliance disclosures ---
    def create_disclosure(self, payload, headers):
        return self._request("POST", "/compliance-disclosures", payload, headers)

    def get_disclosure(self, disclosure_id, headers):
        return self._request("GET", f"/compliance-disclosures/{disclosure_id}", headers=headers)

    def list_loan_disclosures(self, loan_id, headers, params=None):
        return self._request("GET", f"/loans/{loan_id}/compliance-disclosures", headers=headers, params=params)

    # --- Logical clock (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
