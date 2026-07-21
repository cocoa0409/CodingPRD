"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- Portfolio ---
    def create_portfolio(self, payload, headers):
        return self._request("POST", "/portfolios", payload, headers)

    def get_portfolio(self, portfolio_id, headers):
        return self._request("GET", f"/portfolios/{portfolio_id}", headers=headers)

    def recompute_portfolio_risk(self, portfolio_id, headers):
        return self._request("POST", f"/portfolios/{portfolio_id}/recompute-risk",
                             {}, headers)

    # --- Applicant ---
    def create_applicant(self, payload, headers):
        return self._request("POST", "/applicants", payload, headers)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"/applicants/{applicant_id}", headers=headers)

    def verify_applicant(self, applicant_id, headers):
        return self._request("POST", f"/applicants/{applicant_id}/verify", {}, headers)

    # --- Landlord ---
    def create_landlord(self, payload, headers):
        return self._request("POST", "/landlords", payload, headers)

    def get_landlord(self, landlord_id, headers):
        return self._request("GET", f"/landlords/{landlord_id}", headers=headers)

    # --- Guarantee ---
    def create_guarantee(self, payload, headers):
        return self._request("POST", "/guarantees", payload, headers)

    def get_guarantee(self, guarantee_id, headers):
        return self._request("GET", f"/guarantees/{guarantee_id}", headers=headers)

    def list_guarantees(self, headers, params=None):
        return self._request("GET", "/guarantees", headers=headers, params=params)

    def approve_guarantee(self, guarantee_id, headers):
        return self._request("POST", f"/guarantees/{guarantee_id}/approve", {}, headers)

    def pay_fee(self, guarantee_id, payload, headers):
        return self._request("POST", f"/guarantees/{guarantee_id}/pay-fee", payload, headers)

    def activate_guarantee(self, guarantee_id, headers):
        return self._request("POST", f"/guarantees/{guarantee_id}/activate", {}, headers)

    def renew_guarantee(self, guarantee_id, headers):
        return self._request("POST", f"/guarantees/{guarantee_id}/renew", {}, headers)

    def confirm_renewal(self, guarantee_id, headers):
        return self._request("POST", f"/guarantees/{guarantee_id}/confirm-renewal", {}, headers)

    def declare_default(self, guarantee_id, headers):
        return self._request("POST", f"/guarantees/{guarantee_id}/declare-default", {}, headers)

    def cancel_guarantee(self, guarantee_id, headers):
        return self._request("POST", f"/guarantees/{guarantee_id}/cancel", {}, headers)

    def list_ledger_entries(self, guarantee_id, headers, params=None):
        return self._request("GET", f"/guarantees/{guarantee_id}/ledger-entries",
                             headers=headers, params=params)

    def create_claim(self, guarantee_id, payload, headers):
        return self._request("POST", f"/guarantees/{guarantee_id}/claims", payload, headers)

    # --- LandlordAgreement ---
    def create_agreement(self, payload, headers):
        return self._request("POST", "/agreements", payload, headers)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/agreements/{agreement_id}", headers=headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/agreements", headers=headers, params=params)

    def sign_agreement(self, agreement_id, headers):
        return self._request("POST", f"/agreements/{agreement_id}/sign", {}, headers)

    def countersign_agreement(self, agreement_id, headers):
        return self._request("POST", f"/agreements/{agreement_id}/countersign", {}, headers)

    # --- Claim ---
    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def review_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/review", {}, headers)

    def approve_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/approve", {}, headers)

    def deny_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/deny", {}, headers)

    def withdraw_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/withdraw", {}, headers)

    # --- RecoveryPlan / RecoveryInstallment ---
    def get_recovery_plan(self, plan_id, headers):
        return self._request("GET", f"/recovery-plans/{plan_id}", headers=headers)

    def list_recovery_plans(self, headers, params=None):
        return self._request("GET", "/recovery-plans", headers=headers, params=params)

    def create_installment(self, plan_id, payload, headers):
        return self._request("POST", f"/recovery-plans/{plan_id}/installments", payload, headers)

    def list_installments(self, plan_id, headers, params=None):
        return self._request("GET", f"/recovery-plans/{plan_id}/installments",
                             headers=headers, params=params)

    def reverse_installment(self, installment_id, headers):
        return self._request("POST", f"/recovery-installments/{installment_id}/reverse", {}, headers)

    def write_off_recovery_plan(self, plan_id, headers):
        return self._request("POST", f"/recovery-plans/{plan_id}/write-off", {}, headers)

    # --- ComplianceReview ---
    def create_compliance_review(self, payload, headers):
        return self._request("POST", "/compliance-reviews", payload, headers)

    def get_compliance_review(self, review_id, headers):
        return self._request("GET", f"/compliance-reviews/{review_id}", headers=headers)

    def list_compliance_reviews(self, headers, params=None):
        return self._request("GET", "/compliance-reviews", headers=headers, params=params)

    def clear_compliance_review(self, review_id, payload, headers):
        return self._request("POST", f"/compliance-reviews/{review_id}/clear", payload, headers)

    def uphold_compliance_review(self, review_id, payload, headers):
        return self._request("POST", f"/compliance-reviews/{review_id}/uphold", payload, headers)


api_client = ApiClient()
