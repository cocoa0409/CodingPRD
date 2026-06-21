"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Taxpayer ---
    def create_taxpayer(self, payload, headers):
        return self._request("POST", "/taxpayers", payload, headers)

    def get_taxpayer(self, taxpayer_id, headers):
        return self._request("GET", f"/taxpayers/{taxpayer_id}", headers=headers)

    # --- TaxReturn ---
    def create_tax_return(self, payload, headers):
        return self._request("POST", "/tax-returns", payload, headers)

    def get_tax_return(self, return_id, headers):
        return self._request("GET", f"/tax-returns/{return_id}", headers=headers)

    def list_tax_returns(self, headers, params=None):
        return self._request("GET", "/tax-returns", headers=headers, params=params)

    def patch_tax_return(self, return_id, payload, headers):
        return self._request("PATCH", f"/tax-returns/{return_id}", payload, headers)

    def compute_tax_return(self, return_id, headers):
        return self._request("POST", f"/tax-returns/{return_id}/compute", {}, headers)

    def get_estimated_tax_status(self, return_id, headers):
        return self._request("GET", f"/tax-returns/{return_id}/estimated-tax-status",
                             headers=headers)

    # --- IncomeDocument ---
    def create_income_document(self, return_id, payload, headers):
        return self._request("POST", f"/tax-returns/{return_id}/income-documents",
                             payload, headers)

    def list_income_documents(self, return_id, headers, params=None):
        return self._request("GET", f"/tax-returns/{return_id}/income-documents",
                             headers=headers, params=params)

    # --- Schedule ---
    def create_schedule(self, return_id, payload, headers):
        return self._request("POST", f"/tax-returns/{return_id}/schedules", payload, headers)

    def list_schedules(self, return_id, headers, params=None):
        return self._request("GET", f"/tax-returns/{return_id}/schedules",
                             headers=headers, params=params)

    # --- Dependent ---
    def create_dependent(self, return_id, payload, headers):
        return self._request("POST", f"/tax-returns/{return_id}/dependents", payload, headers)

    def list_dependents(self, return_id, headers, params=None):
        return self._request("GET", f"/tax-returns/{return_id}/dependents",
                             headers=headers, params=params)

    # --- CreditClaim ---
    def create_credit_claim(self, return_id, payload, headers):
        return self._request("POST", f"/tax-returns/{return_id}/credit-claims",
                             payload, headers)

    def list_credit_claims(self, return_id, headers, params=None):
        return self._request("GET", f"/tax-returns/{return_id}/credit-claims",
                             headers=headers, params=params)

    # --- EstimatedTaxPayment ---
    def create_estimated_tax_payment(self, payload, headers):
        return self._request("POST", "/estimated-tax-payments", payload, headers)

    def get_estimated_tax_payment(self, payment_id, headers):
        return self._request("GET", f"/estimated-tax-payments/{payment_id}", headers=headers)

    def list_estimated_tax_payments(self, headers, params=None):
        return self._request("GET", "/estimated-tax-payments", headers=headers, params=params)

    # --- EFilingSubmission ---
    def efile_tax_return(self, return_id, payload, headers):
        return self._request("POST", f"/tax-returns/{return_id}/efile", payload, headers)

    def get_efiling(self, efiling_id, headers):
        return self._request("GET", f"/efilings/{efiling_id}", headers=headers)

    def list_efilings(self, headers, params=None):
        return self._request("GET", "/efilings", headers=headers, params=params)

    def acknowledge_efiling(self, efiling_id, payload, headers):
        return self._request("POST", f"/efilings/{efiling_id}/acknowledge", payload, headers)

    # --- AmendedReturn ---
    def create_amended_return(self, payload, headers):
        return self._request("POST", "/amended-returns", payload, headers)

    def get_amended_return(self, amended_id, headers):
        return self._request("GET", f"/amended-returns/{amended_id}", headers=headers)

    def list_amended_returns(self, headers, params=None):
        return self._request("GET", "/amended-returns", headers=headers, params=params)

    def file_amended_return(self, amended_id, headers):
        return self._request("POST", f"/amended-returns/{amended_id}/file", {}, headers)


api_client = ApiClient()
