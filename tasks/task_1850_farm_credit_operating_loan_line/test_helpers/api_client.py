"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Test-driving clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- Association ---
    def create_association(self, payload, headers):
        return self._request("POST", "/associations", payload, headers)

    def get_association(self, association_id, headers):
        return self._request("GET", f"/associations/{association_id}", headers=headers)

    def declare_disaster(self, association_id, payload, headers):
        return self._request("POST", f"/associations/{association_id}/declare_disaster",
                             payload, headers)

    def run_periodic_review(self, association_id, headers):
        return self._request("POST", f"/associations/{association_id}/run_periodic_review",
                             {}, headers)

    # --- Borrower ---
    def create_borrower(self, payload, headers):
        return self._request("POST", "/borrowers", payload, headers)

    def get_borrower(self, borrower_id, headers):
        return self._request("GET", f"/borrowers/{borrower_id}", headers=headers)

    def list_borrowers(self, headers, params=None):
        return self._request("GET", "/borrowers", headers=headers, params=params)

    def terminate_borrower(self, borrower_id, headers):
        return self._request("POST", f"/borrowers/{borrower_id}/terminate", {}, headers)

    # --- LoanAccount ---
    def create_loan(self, payload, headers):
        return self._request("POST", "/loan-accounts", payload, headers)

    def get_loan(self, loan_id, headers):
        return self._request("GET", f"/loan-accounts/{loan_id}", headers=headers)

    def list_loans(self, headers, params=None):
        return self._request("GET", "/loan-accounts", headers=headers, params=params)

    def submit_loan(self, loan_id, headers):
        return self._request("POST", f"/loan-accounts/{loan_id}/submit", {}, headers)

    def approve_loan(self, loan_id, payload, headers):
        return self._request("POST", f"/loan-accounts/{loan_id}/approve", payload, headers)

    def activate_loan(self, loan_id, headers):
        return self._request("POST", f"/loan-accounts/{loan_id}/activate", {}, headers)

    def charge_off_loan(self, loan_id, headers):
        return self._request("POST", f"/loan-accounts/{loan_id}/charge_off", {}, headers)

    def foreclose_loan(self, loan_id, headers):
        return self._request("POST", f"/loan-accounts/{loan_id}/foreclose", {}, headers)

    def get_financial_summary(self, loan_id, headers):
        return self._request("GET", f"/loan-accounts/{loan_id}/financial_summary",
                             headers=headers)

    # --- CropBudget ---
    def create_crop_budget(self, payload, headers):
        return self._request("POST", "/crop-budgets", payload, headers)

    def get_crop_budget(self, budget_id, headers):
        return self._request("GET", f"/crop-budgets/{budget_id}", headers=headers)

    def list_crop_budgets(self, headers, params=None):
        return self._request("GET", "/crop-budgets", headers=headers, params=params)

    def approve_crop_budget(self, budget_id, headers):
        return self._request("POST", f"/crop-budgets/{budget_id}/approve", {}, headers)

    def record_budget_actuals(self, budget_id, payload, headers):
        return self._request("POST", f"/crop-budgets/{budget_id}/record_actuals",
                             payload, headers)

    # --- Collateral ---
    def create_collateral(self, payload, headers):
        return self._request("POST", "/collateral", payload, headers)

    def get_collateral(self, collateral_id, headers):
        return self._request("GET", f"/collateral/{collateral_id}", headers=headers)

    def list_collateral(self, headers, params=None):
        return self._request("GET", "/collateral", headers=headers, params=params)

    def appraise_collateral(self, collateral_id, payload, headers):
        return self._request("POST", f"/collateral/{collateral_id}/appraise",
                             payload, headers)

    def release_collateral(self, collateral_id, headers):
        return self._request("POST", f"/collateral/{collateral_id}/release", {}, headers)

    # --- UCCFiling ---
    def create_ucc_filing(self, payload, headers):
        return self._request("POST", "/ucc-filings", payload, headers)

    def get_ucc_filing(self, filing_id, headers):
        return self._request("GET", f"/ucc-filings/{filing_id}", headers=headers)

    def list_ucc_filings(self, headers, params=None):
        return self._request("GET", "/ucc-filings", headers=headers, params=params)

    def continue_ucc_filing(self, filing_id, headers):
        return self._request("POST", f"/ucc-filings/{filing_id}/continue", {}, headers)

    def terminate_ucc_filing(self, filing_id, headers):
        return self._request("POST", f"/ucc-filings/{filing_id}/terminate", {}, headers)

    # --- InsurancePolicy ---
    def create_insurance_policy(self, payload, headers):
        return self._request("POST", "/insurance-policies", payload, headers)

    def get_insurance_policy(self, policy_id, headers):
        return self._request("GET", f"/insurance-policies/{policy_id}", headers=headers)

    def list_insurance_policies(self, headers, params=None):
        return self._request("GET", "/insurance-policies", headers=headers, params=params)

    def assign_insurance_policy(self, policy_id, payload, headers):
        return self._request("POST", f"/insurance-policies/{policy_id}/assign",
                             payload, headers)

    def cancel_insurance_policy(self, policy_id, headers):
        return self._request("POST", f"/insurance-policies/{policy_id}/cancel", {}, headers)

    # --- InsuranceClaim ---
    def create_insurance_claim(self, payload, headers):
        return self._request("POST", "/insurance-claims", payload, headers)

    def get_insurance_claim(self, claim_id, headers):
        return self._request("GET", f"/insurance-claims/{claim_id}", headers=headers)

    def list_insurance_claims(self, headers, params=None):
        return self._request("GET", "/insurance-claims", headers=headers, params=params)

    def adjuster_report_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/insurance-claims/{claim_id}/adjuster_report",
                             payload, headers)

    def approve_claim(self, claim_id, headers):
        return self._request("POST", f"/insurance-claims/{claim_id}/approve", {}, headers)

    def deny_claim(self, claim_id, headers):
        return self._request("POST", f"/insurance-claims/{claim_id}/deny", {}, headers)

    def appeal_claim(self, claim_id, headers):
        return self._request("POST", f"/insurance-claims/{claim_id}/appeal", {}, headers)

    def pay_claim(self, claim_id, headers):
        return self._request("POST", f"/insurance-claims/{claim_id}/pay", {}, headers)

    # --- DrawRequest ---
    def create_draw_request(self, payload, headers):
        return self._request("POST", "/draw-requests", payload, headers)

    def get_draw_request(self, draw_id, headers):
        return self._request("GET", f"/draw-requests/{draw_id}", headers=headers)

    def list_draw_requests(self, headers, params=None):
        return self._request("GET", "/draw-requests", headers=headers, params=params)

    def approve_draw_request(self, draw_id, headers):
        return self._request("POST", f"/draw-requests/{draw_id}/approve", {}, headers)

    def disburse_draw_request(self, draw_id, headers):
        return self._request("POST", f"/draw-requests/{draw_id}/disburse", {}, headers)

    def deny_draw_request(self, draw_id, headers, reason=None):
        payload = {} if reason is None else {"reason": reason}
        return self._request("POST", f"/draw-requests/{draw_id}/deny", payload, headers)

    def cancel_draw_request(self, draw_id, headers):
        return self._request("POST", f"/draw-requests/{draw_id}/cancel", {}, headers)

    def rescind_draw_request(self, draw_id, headers):
        return self._request("POST", f"/draw-requests/{draw_id}/rescind", {}, headers)

    # --- Repayment ---
    def create_repayment(self, payload, headers):
        return self._request("POST", "/repayments", payload, headers)

    def get_repayment(self, repayment_id, headers):
        return self._request("GET", f"/repayments/{repayment_id}", headers=headers)

    def list_repayments(self, headers, params=None):
        return self._request("GET", "/repayments", headers=headers, params=params)

    def reverse_repayment(self, repayment_id, headers, reason=None):
        payload = {} if reason is None else {"reason": reason}
        return self._request("POST", f"/repayments/{repayment_id}/reverse",
                             payload, headers)

    # --- CovenantEvaluation ---
    def create_covenant_evaluation(self, payload, headers):
        return self._request("POST", "/covenant-evaluations", payload, headers)

    def get_covenant_evaluation(self, evaluation_id, headers):
        return self._request("GET", f"/covenant-evaluations/{evaluation_id}",
                             headers=headers)

    def list_covenant_evaluations(self, headers, params=None):
        return self._request("GET", "/covenant-evaluations", headers=headers,
                             params=params)

    def waive_covenant_evaluation(self, evaluation_id, headers):
        return self._request("POST", f"/covenant-evaluations/{evaluation_id}/waive",
                             {}, headers)

    def void_covenant_evaluation(self, evaluation_id, headers):
        return self._request("POST", f"/covenant-evaluations/{evaluation_id}/void",
                             {}, headers)

    # --- RestructurePlan ---
    def create_restructure_plan(self, payload, headers):
        return self._request("POST", "/restructure-plans", payload, headers)

    def get_restructure_plan(self, plan_id, headers):
        return self._request("GET", f"/restructure-plans/{plan_id}", headers=headers)

    def list_restructure_plans(self, headers, params=None):
        return self._request("GET", "/restructure-plans", headers=headers, params=params)

    def submit_restructure_plan(self, plan_id, headers):
        return self._request("POST", f"/restructure-plans/{plan_id}/submit", {}, headers)

    def approve_restructure_plan(self, plan_id, headers):
        return self._request("POST", f"/restructure-plans/{plan_id}/approve", {}, headers)

    def reject_restructure_plan(self, plan_id, headers, reason=None):
        payload = {} if reason is None else {"reason": reason}
        return self._request("POST", f"/restructure-plans/{plan_id}/reject",
                             payload, headers)

    def execute_restructure_plan(self, plan_id, headers):
        return self._request("POST", f"/restructure-plans/{plan_id}/execute", {}, headers)

    def withdraw_restructure_plan(self, plan_id, headers):
        return self._request("POST", f"/restructure-plans/{plan_id}/withdraw", {}, headers)

    # --- DeferralRequest ---
    def create_deferral_request(self, payload, headers):
        return self._request("POST", "/deferral-requests", payload, headers)

    def get_deferral_request(self, deferral_id, headers):
        return self._request("GET", f"/deferral-requests/{deferral_id}", headers=headers)

    def list_deferral_requests(self, headers, params=None):
        return self._request("GET", "/deferral-requests", headers=headers, params=params)

    def approve_deferral_request(self, deferral_id, headers):
        return self._request("POST", f"/deferral-requests/{deferral_id}/approve",
                             {}, headers)

    def deny_deferral_request(self, deferral_id, headers):
        return self._request("POST", f"/deferral-requests/{deferral_id}/deny", {}, headers)

    def end_deferral_early(self, deferral_id, headers):
        return self._request("POST", f"/deferral-requests/{deferral_id}/end_early",
                             {}, headers)

    # --- PatronageDistribution ---
    def create_patronage_distribution(self, payload, headers):
        return self._request("POST", "/patronage-distributions", payload, headers)

    def get_patronage_distribution(self, distribution_id, headers):
        return self._request("GET", f"/patronage-distributions/{distribution_id}",
                             headers=headers)

    def list_patronage_distributions(self, headers, params=None):
        return self._request("GET", "/patronage-distributions", headers=headers,
                             params=params)

    def allocate_patronage_distribution(self, distribution_id, headers):
        return self._request("POST", f"/patronage-distributions/{distribution_id}/allocate",
                             {}, headers)

    def pay_patronage_distribution(self, distribution_id, headers):
        return self._request("POST", f"/patronage-distributions/{distribution_id}/pay",
                             {}, headers)

    def clawback_patronage_distribution(self, distribution_id, payload, headers):
        return self._request("POST", f"/patronage-distributions/{distribution_id}/clawback",
                             payload, headers)

    # --- MarginCallNotice (system-created; read + escalate only) ---
    def get_margin_call_notice(self, notice_id, headers):
        return self._request("GET", f"/margin-call-notices/{notice_id}", headers=headers)

    def list_margin_call_notices(self, headers, params=None):
        return self._request("GET", "/margin-call-notices", headers=headers, params=params)

    def escalate_margin_call_notice(self, notice_id, headers):
        return self._request("POST", f"/margin-call-notices/{notice_id}/escalate",
                             {}, headers)


api_client = ApiClient()
