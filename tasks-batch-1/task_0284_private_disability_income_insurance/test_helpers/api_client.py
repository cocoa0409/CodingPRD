"""API client: one method per endpoint defined in the PRD.

All paths are mounted under the /disability prefix (PRD §2).
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Insurer + clock ----
    def create_insurer(self, payload, headers):
        return self._request("POST", "/disability/insurers", payload, headers)

    def get_insurer(self, insurer_id, headers):
        return self._request("GET", f"/disability/insurers/{insurer_id}", headers=headers)

    def advance_clock(self, insurer_id, payload, headers):
        return self._request(
            "POST", f"/disability/insurers/{insurer_id}/clock/advance", payload, headers
        )

    # ---- OccupationClass ----
    def create_occupation_class(self, payload, headers):
        return self._request("POST", "/disability/occupation-classes", payload, headers)

    def list_occupation_classes(self, headers, params=None):
        return self._request(
            "GET", "/disability/occupation-classes", headers=headers, params=params
        )

    def get_occupation_class(self, occupation_class_id, headers):
        return self._request(
            "GET", f"/disability/occupation-classes/{occupation_class_id}", headers=headers
        )

    # ---- Policyholder ----
    def create_policyholder(self, payload, headers):
        return self._request("POST", "/disability/policyholders", payload, headers)

    def list_policyholders(self, headers, params=None):
        return self._request("GET", "/disability/policyholders", headers=headers, params=params)

    def get_policyholder(self, policyholder_id, headers):
        return self._request(
            "GET", f"/disability/policyholders/{policyholder_id}", headers=headers
        )

    # ---- Policy ----
    def create_policy(self, payload, headers):
        return self._request("POST", "/disability/policies", payload, headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", "/disability/policies", headers=headers, params=params)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/disability/policies/{policy_id}", headers=headers)

    def activate_policy(self, policy_id, headers):
        return self._request("POST", f"/disability/policies/{policy_id}/activate", {}, headers)

    def terminate_policy(self, policy_id, headers):
        return self._request("POST", f"/disability/policies/{policy_id}/terminate", {}, headers)

    def premium_miss(self, policy_id, headers):
        return self._request(
            "POST", f"/disability/policies/{policy_id}/premium/miss", {}, headers
        )

    def premium_pay(self, policy_id, headers):
        return self._request(
            "POST", f"/disability/policies/{policy_id}/premium/pay", {}, headers
        )

    # ---- Claim ----
    def create_claim(self, payload, headers):
        return self._request("POST", "/disability/claims", payload, headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/disability/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/disability/claims/{claim_id}", headers=headers)

    def submit_claim(self, claim_id, headers):
        return self._request("POST", f"/disability/claims/{claim_id}/submit", {}, headers)

    def begin_review(self, claim_id, headers):
        return self._request("POST", f"/disability/claims/{claim_id}/begin-review", {}, headers)

    def request_info(self, claim_id, headers):
        return self._request("POST", f"/disability/claims/{claim_id}/request-info", {}, headers)

    def resume_review(self, claim_id, headers):
        return self._request("POST", f"/disability/claims/{claim_id}/resume-review", {}, headers)

    def approve_claim(self, claim_id, headers):
        return self._request("POST", f"/disability/claims/{claim_id}/approve", {}, headers)

    def deny_claim(self, claim_id, headers):
        return self._request("POST", f"/disability/claims/{claim_id}/deny", {}, headers)

    def suspend_claim(self, claim_id, headers):
        return self._request("POST", f"/disability/claims/{claim_id}/suspend", {}, headers)

    def reinstate_claim(self, claim_id, headers):
        return self._request("POST", f"/disability/claims/{claim_id}/reinstate", {}, headers)

    def reverse_claim(self, claim_id, headers):
        return self._request("POST", f"/disability/claims/{claim_id}/reverse", {}, headers)

    def close_claim(self, claim_id, headers):
        return self._request("POST", f"/disability/claims/{claim_id}/close", {}, headers)

    # ---- IncomeReport ----
    def create_income_report(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/disability/claims/{claim_id}/income-reports", payload, headers
        )

    def list_income_reports(self, claim_id, headers, params=None):
        return self._request(
            "GET", f"/disability/claims/{claim_id}/income-reports", headers=headers, params=params
        )

    # ---- DisabilityProof ----
    def create_disability_proof(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/disability/claims/{claim_id}/disability-proofs", payload, headers
        )

    def list_disability_proofs(self, claim_id, headers, params=None):
        return self._request(
            "GET", f"/disability/claims/{claim_id}/disability-proofs", headers=headers, params=params
        )

    # ---- BenefitPeriod ----
    def create_benefit_period(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/disability/claims/{claim_id}/benefit-periods", payload, headers
        )

    def list_claim_benefit_periods(self, claim_id, headers, params=None):
        return self._request(
            "GET", f"/disability/claims/{claim_id}/benefit-periods", headers=headers, params=params
        )

    def list_benefit_periods(self, headers, params=None):
        return self._request("GET", "/disability/benefit-periods", headers=headers, params=params)

    def get_benefit_period(self, benefit_period_id, headers):
        return self._request(
            "GET", f"/disability/benefit-periods/{benefit_period_id}", headers=headers
        )

    def void_benefit_period(self, benefit_period_id, headers):
        return self._request(
            "POST", f"/disability/benefit-periods/{benefit_period_id}/void", {}, headers
        )

    # ---- OffsetAward ----
    def create_offset_award(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/disability/claims/{claim_id}/offset-awards", payload, headers
        )

    def list_offset_awards(self, claim_id, headers, params=None):
        return self._request(
            "GET", f"/disability/claims/{claim_id}/offset-awards", headers=headers, params=params
        )

    def get_offset_award(self, offset_award_id, headers):
        return self._request(
            "GET", f"/disability/offset-awards/{offset_award_id}", headers=headers
        )

    def finalize_offset_award(self, offset_award_id, payload, headers):
        return self._request(
            "POST", f"/disability/offset-awards/{offset_award_id}/finalize", payload, headers
        )

    def void_offset_award(self, offset_award_id, headers):
        return self._request(
            "POST", f"/disability/offset-awards/{offset_award_id}/void", {}, headers
        )

    # ---- ClaimLedger ----
    def get_claim_ledger(self, claim_id, headers):
        return self._request("GET", f"/disability/claims/{claim_id}/ledger", headers=headers)


api_client = ApiClient()
