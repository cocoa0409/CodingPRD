"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/fsa"


class ApiClient(GenericApiClient):
    # --- Test-driving logical clock (PRD §2.4; mounted outside /fsa) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- ProjectApplication ---
    def create_application(self, payload, headers):
        return self._request("POST", f"{PREFIX}/applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/applications", headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request("GET", f"{PREFIX}/applications/{application_id}", headers=headers)

    def submit_application(self, application_id, headers):
        return self._request("POST", f"{PREFIX}/applications/{application_id}/submit", {}, headers)

    def score_mission(self, application_id, payload, headers):
        return self._request("POST", f"{PREFIX}/applications/{application_id}/mission-score", payload, headers)

    def decide_compliance(self, application_id, payload, headers):
        return self._request("POST", f"{PREFIX}/applications/{application_id}/compliance-decision", payload, headers)

    def withdraw_application(self, application_id, headers):
        return self._request("POST", f"{PREFIX}/applications/{application_id}/withdraw", {}, headers)

    def list_application_projects(self, application_id, headers):
        return self._request("GET", f"{PREFIX}/applications/{application_id}/projects", headers=headers)

    # --- Project ---
    def list_projects(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/projects", headers=headers, params=params)

    def get_project(self, project_id, headers):
        return self._request("GET", f"{PREFIX}/projects/{project_id}", headers=headers)

    def get_project_summary(self, project_id, headers):
        return self._request("GET", f"{PREFIX}/projects/{project_id}/summary", headers=headers)

    def suspend_project(self, project_id, payload, headers):
        return self._request("POST", f"{PREFIX}/projects/{project_id}/suspend", payload, headers)

    def reinstate_project(self, project_id, headers):
        return self._request("POST", f"{PREFIX}/projects/{project_id}/reinstate", {}, headers)

    def terminate_project(self, project_id, payload, headers):
        return self._request("POST", f"{PREFIX}/projects/{project_id}/terminate", payload, headers)

    # --- SponsorshipAgreement ---
    def list_agreements(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/agreements", headers=headers, params=params)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"{PREFIX}/agreements/{agreement_id}", headers=headers)

    def list_project_agreements(self, project_id, headers):
        return self._request("GET", f"{PREFIX}/projects/{project_id}/agreements", headers=headers)

    def countersign_agreement(self, agreement_id, headers):
        return self._request("POST", f"{PREFIX}/agreements/{agreement_id}/countersign", {}, headers)

    def amend_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"{PREFIX}/agreements/{agreement_id}/amend", payload, headers)

    # --- GrantTranche ---
    def create_grant_tranche(self, agreement_id, payload, headers):
        return self._request("POST", f"{PREFIX}/agreements/{agreement_id}/grant-tranches", payload, headers)

    def list_grant_tranches(self, agreement_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/agreements/{agreement_id}/grant-tranches", headers=headers, params=params)

    def get_grant_tranche(self, tranche_id, headers):
        return self._request("GET", f"{PREFIX}/grant-tranches/{tranche_id}", headers=headers)

    def close_grant_tranche(self, tranche_id, payload, headers):
        return self._request("POST", f"{PREFIX}/grant-tranches/{tranche_id}/close", payload, headers)

    # --- Donation ---
    def create_donation(self, project_id, payload, headers):
        return self._request("POST", f"{PREFIX}/projects/{project_id}/donations", payload, headers)

    def list_donations(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/donations", headers=headers, params=params)

    def get_donation(self, donation_id, headers):
        return self._request("GET", f"{PREFIX}/donations/{donation_id}", headers=headers)

    def receive_donation(self, donation_id, headers):
        return self._request("POST", f"{PREFIX}/donations/{donation_id}/receive", {}, headers)

    def issue_receipt(self, donation_id, headers):
        return self._request("POST", f"{PREFIX}/donations/{donation_id}/issue-receipt", {}, headers)

    def request_refund(self, donation_id, payload, headers):
        return self._request("POST", f"{PREFIX}/donations/{donation_id}/request-refund", payload, headers)

    def decide_refund(self, donation_id, payload, headers):
        return self._request("POST", f"{PREFIX}/donations/{donation_id}/decide-refund", payload, headers)

    # --- TaxReceipt ---
    def get_receipt(self, receipt_id, headers):
        return self._request("GET", f"{PREFIX}/receipts/{receipt_id}", headers=headers)

    def list_donation_receipts(self, donation_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/donations/{donation_id}/receipts", headers=headers, params=params)

    # --- DisbursementRequest ---
    def create_disbursement(self, project_id, payload, headers):
        return self._request("POST", f"{PREFIX}/projects/{project_id}/disbursement-requests", payload, headers)

    def list_disbursements(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/disbursement-requests", headers=headers, params=params)

    def get_disbursement(self, disbursement_id, headers):
        return self._request("GET", f"{PREFIX}/disbursement-requests/{disbursement_id}", headers=headers)

    def submit_disbursement(self, disbursement_id, headers):
        return self._request("POST", f"{PREFIX}/disbursement-requests/{disbursement_id}/submit", {}, headers)

    def compliance_review_disbursement(self, disbursement_id, payload, headers):
        return self._request("POST", f"{PREFIX}/disbursement-requests/{disbursement_id}/compliance-review", payload, headers)

    def sponsor_approve_disbursement(self, disbursement_id, payload, headers):
        return self._request("POST", f"{PREFIX}/disbursement-requests/{disbursement_id}/sponsor-approve", payload, headers)

    def pay_disbursement(self, disbursement_id, headers):
        return self._request("POST", f"{PREFIX}/disbursement-requests/{disbursement_id}/pay", {}, headers)

    def cancel_disbursement(self, disbursement_id, headers):
        return self._request("POST", f"{PREFIX}/disbursement-requests/{disbursement_id}/cancel", {}, headers)

    # --- StaffEngagement ---
    def create_staff_engagement(self, project_id, payload, headers):
        return self._request("POST", f"{PREFIX}/projects/{project_id}/staff-engagements", payload, headers)

    def get_staff_engagement(self, engagement_id, headers):
        return self._request("GET", f"{PREFIX}/staff-engagements/{engagement_id}", headers=headers)

    def list_project_staff_engagements(self, project_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/projects/{project_id}/staff-engagements", headers=headers, params=params)

    def classification_review_engagement(self, engagement_id, payload, headers):
        return self._request("POST", f"{PREFIX}/staff-engagements/{engagement_id}/classification-review", payload, headers)

    def activate_engagement(self, engagement_id, headers):
        return self._request("POST", f"{PREFIX}/staff-engagements/{engagement_id}/activate", {}, headers)

    def flag_misclassification(self, engagement_id, payload, headers):
        return self._request("POST", f"{PREFIX}/staff-engagements/{engagement_id}/flag-misclassification", payload, headers)

    def terminate_engagement(self, engagement_id, payload, headers):
        return self._request("POST", f"{PREFIX}/staff-engagements/{engagement_id}/terminate", payload, headers)

    # --- ComplianceReview ---
    def create_compliance_review(self, project_id, payload, headers):
        return self._request("POST", f"{PREFIX}/projects/{project_id}/compliance-reviews", payload, headers)

    def get_compliance_review(self, review_id, headers):
        return self._request("GET", f"{PREFIX}/compliance-reviews/{review_id}", headers=headers)

    def list_project_compliance_reviews(self, project_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/projects/{project_id}/compliance-reviews", headers=headers, params=params)

    def issue_findings(self, review_id, payload, headers):
        return self._request("POST", f"{PREFIX}/compliance-reviews/{review_id}/issue-findings", payload, headers)

    def remediate_review(self, review_id, payload, headers):
        return self._request("POST", f"{PREFIX}/compliance-reviews/{review_id}/remediate", payload, headers)

    def close_review(self, review_id, headers):
        return self._request("POST", f"{PREFIX}/compliance-reviews/{review_id}/close", {}, headers)

    def escalate_review(self, review_id, payload, headers):
        return self._request("POST", f"{PREFIX}/compliance-reviews/{review_id}/escalate", payload, headers)

    # --- RiskIncident ---
    def create_risk_incident(self, project_id, payload, headers):
        return self._request("POST", f"{PREFIX}/projects/{project_id}/risk-incidents", payload, headers)

    def get_risk_incident(self, incident_id, headers):
        return self._request("GET", f"{PREFIX}/risk-incidents/{incident_id}", headers=headers)

    def list_project_risk_incidents(self, project_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/projects/{project_id}/risk-incidents", headers=headers, params=params)

    def transition_risk_incident(self, incident_id, payload, headers):
        return self._request("POST", f"{PREFIX}/risk-incidents/{incident_id}/transition", payload, headers)

    # --- ExitPlan ---
    def create_exit_plan(self, project_id, payload, headers):
        return self._request("POST", f"{PREFIX}/projects/{project_id}/exit-plans", payload, headers)

    def get_exit_plan(self, exit_plan_id, headers):
        return self._request("GET", f"{PREFIX}/exit-plans/{exit_plan_id}", headers=headers)

    def list_project_exit_plans(self, project_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/projects/{project_id}/exit-plans", headers=headers, params=params)

    def begin_due_diligence(self, exit_plan_id, headers):
        return self._request("POST", f"{PREFIX}/exit-plans/{exit_plan_id}/begin-due-diligence", {}, headers)

    def signoff_exit_plan(self, exit_plan_id, payload, headers):
        return self._request("POST", f"{PREFIX}/exit-plans/{exit_plan_id}/signoff", payload, headers)

    def execute_exit_plan(self, exit_plan_id, headers):
        return self._request("POST", f"{PREFIX}/exit-plans/{exit_plan_id}/execute", {}, headers)

    def abandon_exit_plan(self, exit_plan_id, payload, headers):
        return self._request("POST", f"{PREFIX}/exit-plans/{exit_plan_id}/abandon", payload, headers)

    # --- FundAccount / ledger / fee assessments ---
    def get_fund_account(self, fund_account_id, headers):
        return self._request("GET", f"{PREFIX}/fund-accounts/{fund_account_id}", headers=headers)

    def list_project_fund_accounts(self, project_id, headers):
        return self._request("GET", f"{PREFIX}/projects/{project_id}/fund-accounts", headers=headers)

    def post_fund_adjustment(self, fund_account_id, payload, headers):
        return self._request("POST", f"{PREFIX}/fund-accounts/{fund_account_id}/adjustments", payload, headers)

    def close_period(self, fund_account_id, payload, headers):
        return self._request("POST", f"{PREFIX}/fund-accounts/{fund_account_id}/close-period", payload, headers)

    def list_fund_ledger_entries(self, fund_account_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/fund-accounts/{fund_account_id}/ledger-entries", headers=headers, params=params)

    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/fund-ledger-entries", headers=headers, params=params)

    def get_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"{PREFIX}/fund-ledger-entries/{entry_id}", headers=headers)

    def list_fee_assessments(self, fund_account_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/fund-accounts/{fund_account_id}/fee-assessments", headers=headers, params=params)

    def get_fee_assessment(self, assessment_id, headers):
        return self._request("GET", f"{PREFIX}/fee-assessments/{assessment_id}", headers=headers)


api_client = ApiClient()
