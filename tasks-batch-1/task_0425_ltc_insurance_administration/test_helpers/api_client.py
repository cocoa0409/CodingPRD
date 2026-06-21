"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Policyholder -------------------------------------------------------
    def create_policyholder(self, payload, headers):
        return self._request("POST", "/policyholders", payload, headers)

    def get_policyholder(self, policyholder_id, headers):
        return self._request("GET", f"/policyholders/{policyholder_id}", headers=headers)

    # --- Policy -------------------------------------------------------------
    def create_policy(self, payload, headers):
        return self._request("POST", "/policies", payload, headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", "/policies", headers=headers, params=params)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/policies/{policy_id}", headers=headers)

    def issue_policy(self, policy_id, headers):
        return self._request("POST", f"/policies/{policy_id}/issue", {}, headers)

    def rescind_policy(self, policy_id, headers):
        return self._request("POST", f"/policies/{policy_id}/rescind", {}, headers)

    def apply_anniversary(self, policy_id, headers):
        return self._request("POST", f"/policies/{policy_id}/apply-anniversary", {}, headers)

    def waive_premium(self, policy_id, headers):
        return self._request("POST", f"/policies/{policy_id}/waive-premium", {}, headers)

    # --- BenefitPool / Ledger ----------------------------------------------
    def get_benefit_pool(self, policy_id, headers, params=None):
        return self._request("GET", f"/policies/{policy_id}/benefit-pool", headers=headers, params=params)

    def list_policy_ledger_entries(self, policy_id, headers, params=None):
        return self._request("GET", f"/policies/{policy_id}/ledger-entries", headers=headers, params=params)

    def get_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/ledger-entries/{entry_id}", headers=headers)

    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/ledger-entries", headers=headers, params=params)

    # --- PartnershipDisregard ----------------------------------------------
    def get_partnership_disregard(self, policy_id, headers, params=None):
        return self._request("GET", f"/policies/{policy_id}/partnership-disregard", headers=headers, params=params)

    # --- PremiumInvoice -----------------------------------------------------
    def create_premium_invoice(self, policy_id, payload, headers):
        return self._request("POST", f"/policies/{policy_id}/premium-invoices", payload, headers)

    def list_premium_invoices(self, headers, params=None):
        return self._request("GET", "/premium-invoices", headers=headers, params=params)

    def get_premium_invoice(self, invoice_id, headers):
        return self._request("GET", f"/premium-invoices/{invoice_id}", headers=headers)

    def pay_premium_invoice(self, invoice_id, headers):
        return self._request("POST", f"/premium-invoices/{invoice_id}/pay", {}, headers)

    # --- RateIncreaseFiling -------------------------------------------------
    def create_rate_filing(self, payload, headers):
        return self._request("POST", "/rate-filings", payload, headers)

    def list_rate_filings(self, headers, params=None):
        return self._request("GET", "/rate-filings", headers=headers, params=params)

    def get_rate_filing(self, filing_id, headers):
        return self._request("GET", f"/rate-filings/{filing_id}", headers=headers)

    def adjudicate_rate_filing(self, filing_id, payload, headers):
        return self._request("POST", f"/rate-filings/{filing_id}/adjudicate", payload, headers)

    def withdraw_rate_filing(self, filing_id, headers):
        return self._request("POST", f"/rate-filings/{filing_id}/withdraw", {}, headers)

    # --- BenefitTriggerCertification ---------------------------------------
    def create_trigger_certification(self, policy_id, payload, headers):
        return self._request("POST", f"/policies/{policy_id}/trigger-certifications", payload, headers)

    def list_policy_trigger_certifications(self, policy_id, headers, params=None):
        return self._request("GET", f"/policies/{policy_id}/trigger-certifications", headers=headers, params=params)

    def get_trigger_certification(self, cert_id, headers):
        return self._request("GET", f"/trigger-certifications/{cert_id}", headers=headers)

    def list_trigger_certifications(self, headers, params=None):
        return self._request("GET", "/trigger-certifications", headers=headers, params=params)

    # --- Provider -----------------------------------------------------------
    def create_provider(self, payload, headers):
        return self._request("POST", "/providers", payload, headers)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/providers/{provider_id}", headers=headers)

    def certify_provider(self, provider_id, headers):
        return self._request("POST", f"/providers/{provider_id}/certify", {}, headers)

    def reject_provider(self, provider_id, headers):
        return self._request("POST", f"/providers/{provider_id}/reject", {}, headers)

    def suspend_provider(self, provider_id, headers):
        return self._request("POST", f"/providers/{provider_id}/suspend", {}, headers)

    # --- CarePlan -----------------------------------------------------------
    def create_care_plan(self, payload, headers):
        return self._request("POST", "/care-plans", payload, headers)

    def list_care_plans(self, headers, params=None):
        return self._request("GET", "/care-plans", headers=headers, params=params)

    def get_care_plan(self, care_plan_id, headers):
        return self._request("GET", f"/care-plans/{care_plan_id}", headers=headers)

    def activate_care_plan(self, care_plan_id, headers):
        return self._request("POST", f"/care-plans/{care_plan_id}/activate", {}, headers)

    def close_care_plan(self, care_plan_id, headers):
        return self._request("POST", f"/care-plans/{care_plan_id}/close", {}, headers)

    # --- Claim & ClaimLine --------------------------------------------------
    def create_claim(self, payload, headers):
        return self._request("POST", "/claims", payload, headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def add_claim_line(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/lines", payload, headers)

    def list_claim_lines(self, claim_id, headers, params=None):
        return self._request("GET", f"/claims/{claim_id}/lines", headers=headers, params=params)

    def start_review(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/start-review", {}, headers)

    def request_reassessment(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/request-reassessment", {}, headers)

    def resume_review(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/resume-review", {}, headers)

    def approve_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/approve", payload, headers)

    def deny_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/deny", payload, headers)

    # --- Clock --------------------------------------------------------------
    def advance_clock(self, payload, headers):
        return self._request("POST", "/_clock/advance_to", payload, headers)

    def read_clock(self, headers):
        return self._request("GET", "/_clock", headers=headers)


api_client = ApiClient()
