"""API client: one method per endpoint defined in the PRD."""
from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clock & system ----
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- Fund ----
    def create_fund(self, payload, headers):
        return self._request("POST", "/funds", payload, headers)

    def list_funds(self, headers, params=None):
        return self._request("GET", "/funds", headers=headers, params=params)

    def get_fund(self, fund_id, headers):
        return self._request("GET", f"/funds/{fund_id}", headers=headers)

    def suspend_redemptions(self, fund_id, headers):
        return self._request("POST", f"/funds/{fund_id}/suspend-redemptions", {}, headers)

    def resume_redemptions(self, fund_id, headers):
        return self._request("POST", f"/funds/{fund_id}/resume-redemptions", {}, headers)

    # ---- ShareClass ----
    def create_share_class(self, fund_id, payload, headers):
        return self._request("POST", f"/funds/{fund_id}/share-classes", payload, headers)

    def list_share_classes(self, fund_id, headers, params=None):
        return self._request("GET", f"/funds/{fund_id}/share-classes", headers=headers, params=params)

    def get_share_class(self, fund_id, class_id, headers):
        return self._request("GET", f"/funds/{fund_id}/share-classes/{class_id}", headers=headers)

    def close_subscription(self, fund_id, class_id, headers):
        return self._request("POST", f"/funds/{fund_id}/share-classes/{class_id}/close-subscription", {}, headers)

    def close_redemption(self, fund_id, class_id, headers):
        return self._request("POST", f"/funds/{fund_id}/share-classes/{class_id}/close-redemption", {}, headers)

    # ---- NavPeriod ----
    def create_nav_period(self, fund_id, payload, headers):
        return self._request("POST", f"/funds/{fund_id}/nav-periods", payload, headers)

    def list_nav_periods(self, fund_id, headers, params=None):
        return self._request("GET", f"/funds/{fund_id}/nav-periods", headers=headers, params=params)

    def get_nav_period(self, fund_id, period_id, headers):
        return self._request("GET", f"/funds/{fund_id}/nav-periods/{period_id}", headers=headers)

    def finalize_nav_period(self, fund_id, period_id, payload, headers):
        return self._request("POST", f"/funds/{fund_id}/nav-periods/{period_id}/finalize", payload, headers)

    def close_nav_period(self, fund_id, period_id, headers):
        return self._request("POST", f"/funds/{fund_id}/nav-periods/{period_id}/close", {}, headers)

    # ---- Series ----
    def list_series(self, fund_id, class_id, headers, params=None):
        return self._request("GET", f"/funds/{fund_id}/share-classes/{class_id}/series", headers=headers, params=params)

    def get_series(self, fund_id, class_id, series_id, headers):
        return self._request("GET", f"/funds/{fund_id}/share-classes/{class_id}/series/{series_id}", headers=headers)

    # ---- Investor ----
    def create_investor(self, payload, headers):
        return self._request("POST", "/investors", payload, headers)

    def list_investors(self, headers, params=None):
        return self._request("GET", "/investors", headers=headers, params=params)

    def get_investor(self, investor_id, headers):
        return self._request("GET", f"/investors/{investor_id}", headers=headers)

    # ---- KycCase ----
    def create_kyc_case(self, investor_id, payload, headers):
        return self._request("POST", f"/investors/{investor_id}/kyc-cases", payload, headers)

    def list_kyc_cases(self, investor_id, headers, params=None):
        return self._request("GET", f"/investors/{investor_id}/kyc-cases", headers=headers, params=params)

    def get_kyc_case(self, investor_id, case_id, headers):
        return self._request("GET", f"/investors/{investor_id}/kyc-cases/{case_id}", headers=headers)

    def submit_kyc_document(self, investor_id, case_id, payload, headers):
        return self._request("POST", f"/investors/{investor_id}/kyc-cases/{case_id}/documents", payload, headers)

    def approve_kyc_case(self, investor_id, case_id, payload, headers):
        return self._request("POST", f"/investors/{investor_id}/kyc-cases/{case_id}/approve", payload, headers)

    def reject_kyc_case(self, investor_id, case_id, payload, headers):
        return self._request("POST", f"/investors/{investor_id}/kyc-cases/{case_id}/reject", payload, headers)

    # ---- AccreditationAttestation ----
    def create_accreditation(self, investor_id, payload, headers):
        return self._request("POST", f"/investors/{investor_id}/accreditations", payload, headers)

    def list_accreditations(self, investor_id, headers, params=None):
        return self._request("GET", f"/investors/{investor_id}/accreditations", headers=headers, params=params)

    def get_accreditation(self, investor_id, att_id, headers):
        return self._request("GET", f"/investors/{investor_id}/accreditations/{att_id}", headers=headers)

    def verify_accreditation(self, investor_id, att_id, headers):
        return self._request("POST", f"/investors/{investor_id}/accreditations/{att_id}/verify", {}, headers)

    def reject_accreditation(self, investor_id, att_id, payload, headers):
        return self._request("POST", f"/investors/{investor_id}/accreditations/{att_id}/reject", payload, headers)

    # ---- Subscription ----
    def create_subscription(self, fund_id, payload, headers):
        return self._request("POST", f"/funds/{fund_id}/subscriptions", payload, headers)

    def list_subscriptions(self, fund_id, headers, params=None):
        return self._request("GET", f"/funds/{fund_id}/subscriptions", headers=headers, params=params)

    def get_subscription(self, fund_id, sub_id, headers):
        return self._request("GET", f"/funds/{fund_id}/subscriptions/{sub_id}", headers=headers)

    def submit_subscription(self, fund_id, sub_id, headers):
        return self._request("POST", f"/funds/{fund_id}/subscriptions/{sub_id}/submit", {}, headers)

    def compliance_approve_subscription(self, fund_id, sub_id, headers):
        return self._request("POST", f"/funds/{fund_id}/subscriptions/{sub_id}/compliance-approve", {}, headers)

    def compliance_reject_subscription(self, fund_id, sub_id, payload, headers):
        return self._request("POST", f"/funds/{fund_id}/subscriptions/{sub_id}/compliance-reject", payload, headers)

    def record_funding(self, fund_id, sub_id, payload, headers):
        return self._request("POST", f"/funds/{fund_id}/subscriptions/{sub_id}/fundings", payload, headers)

    def accept_subscription(self, fund_id, sub_id, payload, headers):
        return self._request("POST", f"/funds/{fund_id}/subscriptions/{sub_id}/accept", payload, headers)

    def cancel_subscription(self, fund_id, sub_id, headers):
        return self._request("POST", f"/funds/{fund_id}/subscriptions/{sub_id}/cancel", {}, headers)

    # ---- SideLetter / MfnClause ----
    def create_side_letter(self, fund_id, payload, headers):
        return self._request("POST", f"/funds/{fund_id}/side-letters", payload, headers)

    def list_side_letters(self, fund_id, headers, params=None):
        return self._request("GET", f"/funds/{fund_id}/side-letters", headers=headers, params=params)

    def get_side_letter(self, fund_id, letter_id, headers):
        return self._request("GET", f"/funds/{fund_id}/side-letters/{letter_id}", headers=headers)

    def execute_side_letter(self, fund_id, letter_id, payload, headers):
        return self._request("POST", f"/funds/{fund_id}/side-letters/{letter_id}/execute", payload, headers)

    def elect_mfn(self, fund_id, letter_id, payload, headers):
        return self._request("POST", f"/funds/{fund_id}/side-letters/{letter_id}/elect-mfn", payload, headers)

    def terminate_side_letter(self, fund_id, letter_id, headers):
        return self._request("POST", f"/funds/{fund_id}/side-letters/{letter_id}/terminate", {}, headers)

    def create_mfn_clause(self, fund_id, payload, headers):
        return self._request("POST", f"/funds/{fund_id}/mfn-clauses", payload, headers)

    def list_mfn_clauses(self, fund_id, headers, params=None):
        return self._request("GET", f"/funds/{fund_id}/mfn-clauses", headers=headers, params=params)

    def get_mfn_clause(self, fund_id, clause_id, headers):
        return self._request("GET", f"/funds/{fund_id}/mfn-clauses/{clause_id}", headers=headers)

    def retire_mfn_clause(self, fund_id, clause_id, headers):
        return self._request("POST", f"/funds/{fund_id}/mfn-clauses/{clause_id}/retire", {}, headers)

    # ---- CapitalAccount / SeriesLot ----
    def list_capital_accounts(self, investor_id, headers, params=None):
        return self._request("GET", f"/investors/{investor_id}/capital-accounts", headers=headers, params=params)

    def get_capital_account(self, investor_id, account_id, headers):
        return self._request("GET", f"/investors/{investor_id}/capital-accounts/{account_id}", headers=headers)

    def list_series_lots(self, investor_id, account_id, headers, params=None):
        return self._request("GET", f"/investors/{investor_id}/capital-accounts/{account_id}/lots", headers=headers, params=params)

    # ---- RedemptionRequest ----
    def create_redemption(self, fund_id, payload, headers):
        return self._request("POST", f"/funds/{fund_id}/redemptions", payload, headers)

    def list_redemptions(self, fund_id, headers, params=None):
        return self._request("GET", f"/funds/{fund_id}/redemptions", headers=headers, params=params)

    def get_redemption(self, fund_id, red_id, headers):
        return self._request("GET", f"/funds/{fund_id}/redemptions/{red_id}", headers=headers)

    def approve_redemption(self, fund_id, red_id, headers):
        return self._request("POST", f"/funds/{fund_id}/redemptions/{red_id}/approve", {}, headers)

    def reject_redemption(self, fund_id, red_id, payload, headers):
        return self._request("POST", f"/funds/{fund_id}/redemptions/{red_id}/reject", payload, headers)

    def cancel_redemption(self, fund_id, red_id, headers):
        return self._request("POST", f"/funds/{fund_id}/redemptions/{red_id}/cancel", {}, headers)

    # ---- InvestorStatement ----
    def list_statements(self, investor_id, account_id, headers, params=None):
        return self._request("GET", f"/investors/{investor_id}/capital-accounts/{account_id}/statements", headers=headers, params=params)

    def get_statement(self, investor_id, account_id, stmt_id, headers):
        return self._request("GET", f"/investors/{investor_id}/capital-accounts/{account_id}/statements/{stmt_id}", headers=headers)

    def deliver_statement(self, investor_id, account_id, stmt_id, headers):
        return self._request("POST", f"/investors/{investor_id}/capital-accounts/{account_id}/statements/{stmt_id}/deliver", {}, headers)

    # ---- Flat single-resource GETs ----
    def get_share_class_flat(self, class_id, headers):
        return self._request("GET", f"/share-classes/{class_id}", headers=headers)

    def get_nav_period_flat(self, period_id, headers):
        return self._request("GET", f"/nav-periods/{period_id}", headers=headers)

    def get_series_flat(self, series_id, headers):
        return self._request("GET", f"/series/{series_id}", headers=headers)

    def get_kyc_case_flat(self, case_id, headers):
        return self._request("GET", f"/kyc-cases/{case_id}", headers=headers)

    def get_accreditation_flat(self, att_id, headers):
        return self._request("GET", f"/accreditations/{att_id}", headers=headers)

    def get_subscription_flat(self, sub_id, headers):
        return self._request("GET", f"/subscriptions/{sub_id}", headers=headers)

    def get_side_letter_flat(self, letter_id, headers):
        return self._request("GET", f"/side-letters/{letter_id}", headers=headers)

    def get_mfn_clause_flat(self, clause_id, headers):
        return self._request("GET", f"/mfn-clauses/{clause_id}", headers=headers)

    def get_capital_account_flat(self, account_id, headers):
        return self._request("GET", f"/capital-accounts/{account_id}", headers=headers)

    def get_series_lot_flat(self, lot_id, headers):
        return self._request("GET", f"/series-lots/{lot_id}", headers=headers)

    def get_redemption_flat(self, red_id, headers):
        return self._request("GET", f"/redemptions/{red_id}", headers=headers)

    def get_statement_flat(self, stmt_id, headers):
        return self._request("GET", f"/statements/{stmt_id}", headers=headers)

    def get_investor_flat(self, investor_id, headers):
        return self._request("GET", f"/investors/{investor_id}", headers=headers)

    # ---- Flat filtered-list GETs ----
    def list_share_classes_flat(self, headers, params=None):
        return self._request("GET", "/share-classes", headers=headers, params=params)

    def list_nav_periods_flat(self, headers, params=None):
        return self._request("GET", "/nav-periods", headers=headers, params=params)

    def list_series_flat(self, headers, params=None):
        return self._request("GET", "/series", headers=headers, params=params)

    def list_kyc_cases_flat(self, headers, params=None):
        return self._request("GET", "/kyc-cases", headers=headers, params=params)

    def list_accreditations_flat(self, headers, params=None):
        return self._request("GET", "/accreditations", headers=headers, params=params)

    def list_subscriptions_flat(self, headers, params=None):
        return self._request("GET", "/subscriptions", headers=headers, params=params)

    def list_side_letters_flat(self, headers, params=None):
        return self._request("GET", "/side-letters", headers=headers, params=params)

    def list_mfn_clauses_flat(self, headers, params=None):
        return self._request("GET", "/mfn-clauses", headers=headers, params=params)

    def list_capital_accounts_flat(self, headers, params=None):
        return self._request("GET", "/capital-accounts", headers=headers, params=params)

    def list_series_lots_flat(self, headers, params=None):
        return self._request("GET", "/series-lots", headers=headers, params=params)

    def list_redemptions_flat(self, headers, params=None):
        return self._request("GET", "/redemptions", headers=headers, params=params)

    def list_statements_flat(self, headers, params=None):
        return self._request("GET", "/statements", headers=headers, params=params)


api_client = ApiClient()
