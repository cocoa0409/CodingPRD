"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Borrower ---
    def create_borrower(self, payload, headers):
        return self._request("POST", "/borrowers", payload, headers)

    def get_borrower(self, borrower_id, headers):
        return self._request("GET", f"/borrowers/{borrower_id}", headers=headers)

    def list_borrower_loans(self, borrower_id, headers, params=None):
        return self._request("GET", f"/borrowers/{borrower_id}/loans", headers=headers, params=params)

    # --- Loan ---
    def create_loan(self, payload, headers):
        return self._request("POST", "/loans", payload, headers)

    def get_loan(self, loan_id, headers):
        return self._request("GET", f"/loans/{loan_id}", headers=headers)

    def list_loans(self, headers, params=None):
        return self._request("GET", "/loans", headers=headers, params=params)

    def aging_refresh(self, loan_id, payload, headers):
        return self._request("POST", f"/loans/{loan_id}/aging-refresh", payload, headers)

    # --- WorkoutCase ---
    def create_workout_case(self, loan_id, payload, headers):
        return self._request("POST", f"/loans/{loan_id}/workout-cases", payload, headers)

    def list_workout_cases(self, loan_id, headers, params=None):
        return self._request("GET", f"/loans/{loan_id}/workout-cases", headers=headers, params=params)

    def get_workout_case(self, loan_id, case_id, headers):
        return self._request("GET", f"/loans/{loan_id}/workout-cases/{case_id}", headers=headers)

    def get_workout_case_flat(self, case_id, headers):
        return self._request("GET", f"/workout-cases/{case_id}", headers=headers)

    def list_workout_cases_flat(self, headers, params=None):
        return self._request("GET", "/workout-cases", headers=headers, params=params)

    # --- ActionPlan ---
    def create_action_plan(self, loan_id, case_id, payload, headers):
        return self._request("POST", f"/loans/{loan_id}/workout-cases/{case_id}/action-plans", payload, headers)

    def list_action_plans(self, loan_id, case_id, headers, params=None):
        return self._request("GET", f"/loans/{loan_id}/workout-cases/{case_id}/action-plans", headers=headers, params=params)

    def get_action_plan_flat(self, plan_id, headers):
        return self._request("GET", f"/action-plans/{plan_id}", headers=headers)

    def list_action_plans_flat(self, headers, params=None):
        return self._request("GET", "/action-plans", headers=headers, params=params)

    def submit_action_plan(self, loan_id, case_id, plan_id, headers):
        return self._request("POST", f"/loans/{loan_id}/workout-cases/{case_id}/action-plans/{plan_id}/submit", {}, headers)

    def approve_action_plan(self, loan_id, case_id, plan_id, headers):
        return self._request("POST", f"/loans/{loan_id}/workout-cases/{case_id}/action-plans/{plan_id}/approve", {}, headers)

    def reject_action_plan(self, loan_id, case_id, plan_id, headers):
        return self._request("POST", f"/loans/{loan_id}/workout-cases/{case_id}/action-plans/{plan_id}/reject", {}, headers)

    def revise_action_plan(self, loan_id, case_id, plan_id, headers):
        return self._request("POST", f"/loans/{loan_id}/workout-cases/{case_id}/action-plans/{plan_id}/revise", {}, headers)

    # --- RestructureProposal ---
    def create_proposal(self, loan_id, case_id, payload, headers):
        return self._request("POST", f"/loans/{loan_id}/workout-cases/{case_id}/proposals", payload, headers)

    def list_proposals(self, loan_id, case_id, headers, params=None):
        return self._request("GET", f"/loans/{loan_id}/workout-cases/{case_id}/proposals", headers=headers, params=params)

    def get_proposal_flat(self, proposal_id, headers):
        return self._request("GET", f"/proposals/{proposal_id}", headers=headers)

    def list_proposals_flat(self, headers, params=None):
        return self._request("GET", "/proposals", headers=headers, params=params)

    def submit_proposal(self, loan_id, case_id, proposal_id, headers):
        return self._request("POST", f"/loans/{loan_id}/workout-cases/{case_id}/proposals/{proposal_id}/submit", {}, headers)

    def counter_proposal(self, loan_id, case_id, proposal_id, payload, headers):
        return self._request("POST", f"/loans/{loan_id}/workout-cases/{case_id}/proposals/{proposal_id}/counter", payload, headers)

    def resubmit_proposal(self, loan_id, case_id, proposal_id, headers):
        return self._request("POST", f"/loans/{loan_id}/workout-cases/{case_id}/proposals/{proposal_id}/resubmit", {}, headers)

    def escalate_proposal(self, loan_id, case_id, proposal_id, headers):
        return self._request("POST", f"/loans/{loan_id}/workout-cases/{case_id}/proposals/{proposal_id}/escalate-to-committee", {}, headers)

    def committee_approve_proposal(self, loan_id, case_id, proposal_id, headers):
        return self._request("POST", f"/loans/{loan_id}/workout-cases/{case_id}/proposals/{proposal_id}/committee-approve", {}, headers)

    def committee_reject_proposal(self, loan_id, case_id, proposal_id, headers):
        return self._request("POST", f"/loans/{loan_id}/workout-cases/{case_id}/proposals/{proposal_id}/committee-reject", {}, headers)

    def consummate_proposal(self, loan_id, case_id, proposal_id, headers):
        return self._request("POST", f"/loans/{loan_id}/workout-cases/{case_id}/proposals/{proposal_id}/consummate", {}, headers)

    def withdraw_proposal(self, loan_id, case_id, proposal_id, headers):
        return self._request("POST", f"/loans/{loan_id}/workout-cases/{case_id}/proposals/{proposal_id}/withdraw", {}, headers)

    # --- CollateralItem ---
    def create_collateral(self, loan_id, payload, headers):
        return self._request("POST", f"/loans/{loan_id}/collateral", payload, headers)

    def list_collateral(self, loan_id, headers, params=None):
        return self._request("GET", f"/loans/{loan_id}/collateral", headers=headers, params=params)

    def get_collateral(self, loan_id, collateral_id, headers):
        return self._request("GET", f"/loans/{loan_id}/collateral/{collateral_id}", headers=headers)

    def get_collateral_flat(self, collateral_id, headers):
        return self._request("GET", f"/collateral-items/{collateral_id}", headers=headers)

    def list_collateral_flat(self, headers, params=None):
        return self._request("GET", "/collateral-items", headers=headers, params=params)

    def release_collateral(self, loan_id, collateral_id, headers):
        return self._request("POST", f"/loans/{loan_id}/collateral/{collateral_id}/release", {}, headers)

    # --- CollateralAppraisal ---
    def create_appraisal(self, loan_id, collateral_id, payload, headers):
        return self._request("POST", f"/loans/{loan_id}/collateral/{collateral_id}/appraisals", payload, headers)

    def list_appraisals(self, loan_id, collateral_id, headers, params=None):
        return self._request("GET", f"/loans/{loan_id}/collateral/{collateral_id}/appraisals", headers=headers, params=params)

    def get_appraisal_flat(self, appraisal_id, headers):
        return self._request("GET", f"/appraisals/{appraisal_id}", headers=headers)

    def list_appraisals_flat(self, headers, params=None):
        return self._request("GET", "/appraisals", headers=headers, params=params)

    def submit_appraisal(self, loan_id, collateral_id, appraisal_id, headers):
        return self._request("POST", f"/loans/{loan_id}/collateral/{collateral_id}/appraisals/{appraisal_id}/submit", {}, headers)

    def accept_appraisal(self, loan_id, collateral_id, appraisal_id, headers):
        return self._request("POST", f"/loans/{loan_id}/collateral/{collateral_id}/appraisals/{appraisal_id}/accept", {}, headers)

    def reject_appraisal(self, loan_id, collateral_id, appraisal_id, headers):
        return self._request("POST", f"/loans/{loan_id}/collateral/{collateral_id}/appraisals/{appraisal_id}/reject", {}, headers)

    # --- ImpairmentAssessment ---
    def create_impairment(self, loan_id, case_id, payload, headers):
        return self._request("POST", f"/loans/{loan_id}/workout-cases/{case_id}/impairments", payload, headers)

    def list_impairments(self, loan_id, case_id, headers, params=None):
        return self._request("GET", f"/loans/{loan_id}/workout-cases/{case_id}/impairments", headers=headers, params=params)

    def get_impairment_flat(self, assessment_id, headers):
        return self._request("GET", f"/impairments/{assessment_id}", headers=headers)

    def list_impairments_flat(self, headers, params=None):
        return self._request("GET", "/impairments", headers=headers, params=params)

    def finalize_impairment(self, loan_id, case_id, assessment_id, headers):
        return self._request("POST", f"/loans/{loan_id}/workout-cases/{case_id}/impairments/{assessment_id}/finalize", {}, headers)

    # --- LegalReferral ---
    def create_legal_referral(self, loan_id, case_id, payload, headers):
        return self._request("POST", f"/loans/{loan_id}/workout-cases/{case_id}/legal-referrals", payload, headers)

    def list_legal_referrals(self, loan_id, case_id, headers, params=None):
        return self._request("GET", f"/loans/{loan_id}/workout-cases/{case_id}/legal-referrals", headers=headers, params=params)

    def get_legal_referral_flat(self, referral_id, headers):
        return self._request("GET", f"/legal-referrals/{referral_id}", headers=headers)

    def list_legal_referrals_flat(self, headers, params=None):
        return self._request("GET", "/legal-referrals", headers=headers, params=params)

    def accept_referral(self, loan_id, case_id, referral_id, headers):
        return self._request("POST", f"/loans/{loan_id}/workout-cases/{case_id}/legal-referrals/{referral_id}/accept", {}, headers)

    def settle_referral(self, loan_id, case_id, referral_id, payload, headers):
        return self._request("POST", f"/loans/{loan_id}/workout-cases/{case_id}/legal-referrals/{referral_id}/settle", payload, headers)

    def dismiss_referral(self, loan_id, case_id, referral_id, headers):
        return self._request("POST", f"/loans/{loan_id}/workout-cases/{case_id}/legal-referrals/{referral_id}/dismiss", {}, headers)

    # --- ChargeOffEvent ---
    def create_charge_off(self, loan_id, case_id, payload, headers):
        return self._request("POST", f"/loans/{loan_id}/workout-cases/{case_id}/charge-offs", payload, headers)

    def list_charge_offs(self, loan_id, case_id, headers, params=None):
        return self._request("GET", f"/loans/{loan_id}/workout-cases/{case_id}/charge-offs", headers=headers, params=params)

    def get_charge_off_flat(self, charge_off_id, headers):
        return self._request("GET", f"/charge-offs/{charge_off_id}", headers=headers)

    def list_charge_offs_flat(self, headers, params=None):
        return self._request("GET", "/charge-offs", headers=headers, params=params)

    # --- RecoveryEvent ---
    def create_recovery(self, loan_id, case_id, payload, headers):
        return self._request("POST", f"/loans/{loan_id}/workout-cases/{case_id}/recoveries", payload, headers)

    def list_recoveries(self, loan_id, case_id, headers, params=None):
        return self._request("GET", f"/loans/{loan_id}/workout-cases/{case_id}/recoveries", headers=headers, params=params)

    def get_recovery_flat(self, recovery_id, headers):
        return self._request("GET", f"/recoveries/{recovery_id}", headers=headers)

    def list_recoveries_flat(self, headers, params=None):
        return self._request("GET", "/recoveries", headers=headers, params=params)

    # --- ExitStrategyDecision / close / report ---
    def create_exit_decision(self, loan_id, case_id, payload, headers):
        return self._request("POST", f"/loans/{loan_id}/workout-cases/{case_id}/exit-decision", payload, headers)

    def list_exit_decisions(self, loan_id, case_id, headers, params=None):
        return self._request("GET", f"/loans/{loan_id}/workout-cases/{case_id}/exit-decisions", headers=headers, params=params)

    def get_exit_decision_flat(self, decision_id, headers):
        return self._request("GET", f"/exit-decisions/{decision_id}", headers=headers)

    def list_exit_decisions_flat(self, headers, params=None):
        return self._request("GET", "/exit-decisions", headers=headers, params=params)

    def close_case(self, loan_id, case_id, headers):
        return self._request("POST", f"/loans/{loan_id}/workout-cases/{case_id}/close", {}, headers)

    def get_portfolio_report(self, headers, params=None):
        return self._request("GET", "/portfolio-report", headers=headers, params=params)


api_client = ApiClient()
