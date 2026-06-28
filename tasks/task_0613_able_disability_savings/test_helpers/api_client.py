"""API client: one method per endpoint defined in the ABLE program PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Program ----
    def create_program(self, payload, headers):
        return self._request("POST", "/able/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/able/programs/{program_id}", headers=headers)

    # ---- InvestmentOption ----
    def create_investment_option(self, payload, headers):
        return self._request("POST", "/able/investment-options", payload, headers)

    def get_investment_option(self, option_id, headers):
        return self._request("GET", f"/able/investment-options/{option_id}", headers=headers)

    def list_investment_options(self, headers, params=None):
        return self._request("GET", "/able/investment-options", headers=headers, params=params)

    # ---- Beneficiary ----
    def create_beneficiary(self, payload, headers):
        return self._request("POST", "/able/beneficiaries", payload, headers)

    def get_beneficiary(self, beneficiary_id, headers):
        return self._request("GET", f"/able/beneficiaries/{beneficiary_id}", headers=headers)

    def list_beneficiaries(self, headers, params=None):
        return self._request("GET", "/able/beneficiaries", headers=headers, params=params)

    def record_death(self, beneficiary_id, headers):
        return self._request("POST", f"/able/beneficiaries/{beneficiary_id}/record_death", {}, headers)

    # ---- Certification ----
    def create_certification(self, beneficiary_id, payload, headers):
        return self._request("POST", f"/able/beneficiaries/{beneficiary_id}/certifications", payload, headers)

    def get_certification(self, certification_id, headers):
        return self._request("GET", f"/able/certifications/{certification_id}", headers=headers)

    def list_certifications(self, headers, params=None):
        return self._request("GET", "/able/certifications", headers=headers, params=params)

    def decide_certification(self, certification_id, payload, headers):
        return self._request("POST", f"/able/certifications/{certification_id}/decide", payload, headers)

    # ---- Account ----
    def create_account(self, payload, headers):
        return self._request("POST", "/able/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/able/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/able/accounts", headers=headers, params=params)

    def means_test(self, account_id, variant, headers):
        return self._request(
            "GET",
            f"/able/accounts/{account_id}/means-test",
            headers=headers,
            params={"variant": variant},
        )

    def suspend_account(self, account_id, headers):
        return self._request("POST", f"/able/accounts/{account_id}/suspend", {}, headers)

    def reinstate_account(self, account_id, headers):
        return self._request("POST", f"/able/accounts/{account_id}/reinstate", {}, headers)

    def assess_fee(self, account_id, payload, headers):
        return self._request("POST", f"/able/accounts/{account_id}/assess-fee", payload, headers)

    # ---- Investment changes ----
    def change_investment(self, account_id, payload, headers):
        return self._request("POST", f"/able/accounts/{account_id}/investment-changes", payload, headers)

    # ---- AuthorizedRepresentative ----
    def create_representative(self, account_id, payload, headers):
        return self._request("POST", f"/able/accounts/{account_id}/authorized-representatives", payload, headers)

    def get_representative(self, representative_id, headers):
        return self._request("GET", f"/able/authorized-representatives/{representative_id}", headers=headers)

    def list_representatives(self, headers, params=None):
        return self._request("GET", "/able/authorized-representatives", headers=headers, params=params)

    def revoke_representative(self, representative_id, headers):
        return self._request("POST", f"/able/authorized-representatives/{representative_id}/revoke", {}, headers)

    # ---- Contribution ----
    def create_contribution(self, account_id, payload, headers):
        return self._request("POST", f"/able/accounts/{account_id}/contributions", payload, headers)

    def get_contribution(self, contribution_id, headers):
        return self._request("GET", f"/able/contributions/{contribution_id}", headers=headers)

    def list_contributions(self, headers, params=None):
        return self._request("GET", "/able/contributions", headers=headers, params=params)

    def reverse_contribution(self, contribution_id, headers):
        return self._request("POST", f"/able/contributions/{contribution_id}/reverse", {}, headers)

    # ---- Distribution ----
    def create_distribution(self, account_id, payload, headers):
        return self._request("POST", f"/able/accounts/{account_id}/distributions", payload, headers)

    def get_distribution(self, distribution_id, headers):
        return self._request("GET", f"/able/distributions/{distribution_id}", headers=headers)

    def list_distributions(self, headers, params=None):
        return self._request("GET", "/able/distributions", headers=headers, params=params)

    def approve_distribution(self, distribution_id, headers):
        return self._request("POST", f"/able/distributions/{distribution_id}/approve", {}, headers)

    def reject_distribution(self, distribution_id, headers):
        return self._request("POST", f"/able/distributions/{distribution_id}/reject", {}, headers)

    def disburse_distribution(self, distribution_id, payload, headers):
        return self._request("POST", f"/able/distributions/{distribution_id}/disburse", payload, headers)

    def substantiate_distribution(self, distribution_id, headers):
        return self._request("POST", f"/able/distributions/{distribution_id}/substantiate", {}, headers)

    def clawback_distribution(self, distribution_id, headers):
        return self._request("POST", f"/able/distributions/{distribution_id}/clawback", {}, headers)

    # ---- QDERecord ----
    def create_qde_record(self, distribution_id, payload, headers):
        return self._request("POST", f"/able/distributions/{distribution_id}/qde-records", payload, headers)

    def get_qde_record(self, qde_id, headers):
        return self._request("GET", f"/able/qde-records/{qde_id}", headers=headers)

    def list_qde_records(self, headers, params=None):
        return self._request("GET", "/able/qde-records", headers=headers, params=params)

    # ---- MedicaidClaim ----
    def file_medicaid_claim(self, account_id, payload, headers):
        return self._request("POST", f"/able/accounts/{account_id}/medicaid-claims", payload, headers)

    def get_medicaid_claim(self, claim_id, headers):
        return self._request("GET", f"/able/medicaid-claims/{claim_id}", headers=headers)

    def list_medicaid_claims(self, headers, params=None):
        return self._request("GET", "/able/medicaid-claims", headers=headers, params=params)

    def settle_medicaid_claim(self, account_id, claim_id, headers):
        return self._request(
            "POST",
            f"/able/accounts/{account_id}/medicaid-claims/{claim_id}/settle",
            {},
            headers,
        )

    # ---- Test-driving capabilities ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    def credit_earnings(self, account_id, earnings_delta_cents, headers):
        return self._request(
            "POST",
            "/_market/credit_earnings",
            {"account_id": account_id, "earnings_delta_cents": earnings_delta_cents},
            headers,
        )


api_client = ApiClient()
