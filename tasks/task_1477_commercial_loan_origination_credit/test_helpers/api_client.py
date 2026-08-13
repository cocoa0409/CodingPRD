"""API client: one method per endpoint defined in the PRD (all under /credit)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Bank officers ---
    def create_bank_officer(self, payload, headers):
        return self._request("POST", "/credit/bank-officers", payload, headers)

    def get_bank_officer(self, officer_id, headers):
        return self._request("GET", f"/credit/bank-officers/{officer_id}", headers=headers)

    def list_officer_policy_exceptions(self, officer_id, headers, params=None):
        return self._request("GET", f"/credit/bank-officers/{officer_id}/policy-exceptions", headers=headers, params=params)

    def list_officer_checklist_items(self, officer_id, headers, params=None):
        return self._request("GET", f"/credit/bank-officers/{officer_id}/document-checklist-items", headers=headers, params=params)

    def list_officer_funding_authorizations(self, officer_id, headers, params=None):
        return self._request("GET", f"/credit/bank-officers/{officer_id}/funding-authorizations", headers=headers, params=params)

    # --- Borrowers ---
    def create_borrower(self, payload, headers):
        return self._request("POST", "/credit/borrowers", payload, headers)

    def list_borrowers(self, headers, params=None):
        return self._request("GET", "/credit/borrowers", headers=headers, params=params)

    def get_borrower(self, borrower_id, headers):
        return self._request("GET", f"/credit/borrowers/{borrower_id}", headers=headers)

    def list_borrower_applications(self, borrower_id, headers, params=None):
        return self._request("GET", f"/credit/borrowers/{borrower_id}/loan-applications", headers=headers, params=params)

    def update_borrower(self, borrower_id, payload, headers):
        return self._request("PATCH", f"/credit/borrowers/{borrower_id}", payload, headers)

    # --- Loan applications ---
    def create_loan_application(self, payload, headers):
        return self._request("POST", "/credit/loan-applications", payload, headers)

    def list_loan_applications(self, headers, params=None):
        return self._request("GET", "/credit/loan-applications", headers=headers, params=params)

    def get_loan_application(self, app_id, headers):
        return self._request("GET", f"/credit/loan-applications/{app_id}", headers=headers)

    def update_loan_application(self, app_id, payload, headers):
        return self._request("PATCH", f"/credit/loan-applications/{app_id}", payload, headers)

    def submit_application(self, app_id, headers):
        return self._request("POST", f"/credit/loan-applications/{app_id}/submit", {}, headers)

    def finalize_spreads(self, app_id, headers):
        return self._request("POST", f"/credit/loan-applications/{app_id}/finalize-spreads", {}, headers)

    def clear_exceptions(self, app_id, headers):
        return self._request("POST", f"/credit/loan-applications/{app_id}/clear-exceptions", {}, headers)

    def submit_to_committee(self, app_id, headers):
        return self._request("POST", f"/credit/loan-applications/{app_id}/submit-to-committee", {}, headers)

    def submit_for_closing(self, app_id, headers):
        return self._request("POST", f"/credit/loan-applications/{app_id}/submit-for-closing", {}, headers)

    def withdraw_application(self, app_id, headers):
        return self._request("POST", f"/credit/loan-applications/{app_id}/withdraw", {}, headers)

    # --- Financial statements ---
    def create_financial_statement(self, payload, headers):
        return self._request("POST", "/credit/financial-statements", payload, headers)

    def list_financial_statements(self, headers, params=None):
        return self._request("GET", "/credit/financial-statements", headers=headers, params=params)

    def get_financial_statement(self, stmt_id, headers):
        return self._request("GET", f"/credit/financial-statements/{stmt_id}", headers=headers)

    def spread_statement(self, stmt_id, headers):
        return self._request("POST", f"/credit/financial-statements/{stmt_id}/spread", {}, headers)

    def finalize_statement(self, stmt_id, headers):
        return self._request("POST", f"/credit/financial-statements/{stmt_id}/finalize", {}, headers)

    # --- Policy exceptions ---
    def list_application_exceptions(self, app_id, headers, params=None):
        return self._request("GET", f"/credit/loan-applications/{app_id}/policy-exceptions", headers=headers, params=params)

    def waive_exception(self, exception_id, payload, headers):
        return self._request("POST", f"/credit/policy-exceptions/{exception_id}/waive", payload, headers)

    # --- Appraisers / appraisals ---
    def create_appraiser(self, payload, headers):
        return self._request("POST", "/credit/appraisers", payload, headers)

    def get_appraiser(self, appraiser_id, headers):
        return self._request("GET", f"/credit/appraisers/{appraiser_id}", headers=headers)

    def update_appraiser(self, appraiser_id, payload, headers):
        return self._request("PATCH", f"/credit/appraisers/{appraiser_id}", payload, headers)

    def create_appraisal(self, payload, headers):
        return self._request("POST", "/credit/appraisals", payload, headers)

    def list_application_appraisals(self, app_id, headers, params=None):
        return self._request("GET", f"/credit/loan-applications/{app_id}/appraisals", headers=headers, params=params)

    def list_appraiser_appraisals(self, appraiser_id, headers, params=None):
        return self._request("GET", f"/credit/appraisers/{appraiser_id}/appraisals", headers=headers, params=params)

    def receive_appraisal_report(self, appraisal_id, payload, headers):
        return self._request("POST", f"/credit/appraisals/{appraisal_id}/receive-report", payload, headers)

    def review_appraisal(self, appraisal_id, payload, headers):
        return self._request("POST", f"/credit/appraisals/{appraisal_id}/review", payload, headers)

    # --- Committee sessions / decisions / votes ---
    def create_committee_session(self, payload, headers):
        return self._request("POST", "/credit/committee-sessions", payload, headers)

    def get_committee_session(self, session_id, headers):
        return self._request("GET", f"/credit/committee-sessions/{session_id}", headers=headers)

    def list_session_decisions(self, session_id, headers, params=None):
        return self._request("GET", f"/credit/committee-sessions/{session_id}/committee-decisions", headers=headers, params=params)

    def create_committee_decision(self, payload, headers):
        return self._request("POST", "/credit/committee-decisions", payload, headers)

    def list_application_decisions(self, app_id, headers, params=None):
        return self._request("GET", f"/credit/loan-applications/{app_id}/committee-decisions", headers=headers, params=params)

    def cast_vote(self, decision_id, payload, headers):
        return self._request("POST", f"/credit/committee-decisions/{decision_id}/votes", payload, headers)

    # --- Term sheets ---
    def create_term_sheet(self, payload, headers):
        return self._request("POST", "/credit/term-sheets", payload, headers)

    def list_application_term_sheets(self, app_id, headers, params=None):
        return self._request("GET", f"/credit/loan-applications/{app_id}/term-sheets", headers=headers, params=params)

    def respond_term_sheet(self, sheet_id, payload, headers):
        return self._request("POST", f"/credit/term-sheets/{sheet_id}/respond", payload, headers)

    # --- Commitment letters ---
    def list_commitment_letters(self, headers, params=None):
        return self._request("GET", "/credit/commitment-letters", headers=headers, params=params)

    def get_commitment_letter(self, letter_id, headers):
        return self._request("GET", f"/credit/commitment-letters/{letter_id}", headers=headers)

    def issue_commitment_letter(self, letter_id, payload, headers):
        return self._request("POST", f"/credit/commitment-letters/{letter_id}/issue", payload, headers)

    def accept_commitment_letter(self, letter_id, headers):
        return self._request("POST", f"/credit/commitment-letters/{letter_id}/accept", {}, headers)

    # --- Document checklist items ---
    def create_checklist_item(self, payload, headers):
        return self._request("POST", "/credit/document-checklist-items", payload, headers)

    def list_application_checklist_items(self, app_id, headers, params=None):
        return self._request("GET", f"/credit/loan-applications/{app_id}/document-checklist-items", headers=headers, params=params)

    def transition_checklist_item(self, item_id, payload, headers):
        return self._request("POST", f"/credit/document-checklist-items/{item_id}/transition", payload, headers)

    # --- Funding authorizations ---
    def create_funding_authorization(self, payload, headers):
        return self._request("POST", "/credit/funding-authorizations", payload, headers)

    def list_application_funding_authorizations(self, app_id, headers, params=None):
        return self._request("GET", f"/credit/loan-applications/{app_id}/funding-authorizations", headers=headers, params=params)

    def authorize_funding(self, fa_id, headers):
        return self._request("POST", f"/credit/funding-authorizations/{fa_id}/authorize", {}, headers)

    def release_funding(self, fa_id, headers):
        return self._request("POST", f"/credit/funding-authorizations/{fa_id}/release", {}, headers)

    # --- Covenants ---
    def create_covenant(self, payload, headers):
        return self._request("POST", "/credit/covenants", payload, headers)

    def list_application_covenants(self, app_id, headers, params=None):
        return self._request("GET", f"/credit/loan-applications/{app_id}/covenants", headers=headers, params=params)

    def review_covenant(self, covenant_id, payload, headers):
        return self._request("POST", f"/credit/covenants/{covenant_id}/review", payload, headers)

    def waive_covenant_breach(self, covenant_id, payload, headers):
        return self._request("POST", f"/credit/covenants/{covenant_id}/waive-breach", payload, headers)

    # --- Participations ---
    def create_participation(self, payload, headers):
        return self._request("POST", "/credit/participations", payload, headers)

    def list_application_participations(self, app_id, headers, params=None):
        return self._request("GET", f"/credit/loan-applications/{app_id}/participations", headers=headers, params=params)

    def commit_participation(self, participation_id, headers):
        return self._request("POST", f"/credit/participations/{participation_id}/commit", {}, headers)

    def release_participation(self, participation_id, headers):
        return self._request("POST", f"/credit/participations/{participation_id}/release", {}, headers)

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/credit/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
