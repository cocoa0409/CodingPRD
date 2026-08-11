"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Test-driving logical clock (PRD §2.4) ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/trustee/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- Case ---
    def create_case(self, payload, headers):
        return self._request("POST", "/trustee/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/trustee/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/trustee/cases", headers=headers, params=params)

    def begin_investigation(self, case_id, headers):
        return self._request("POST", f"/trustee/cases/{case_id}/begin_investigation",
                             {}, headers)

    def set_bar_date(self, case_id, bar_date, headers):
        return self._request("POST", f"/trustee/cases/{case_id}/set_bar_date",
                             {"bar_date": bar_date}, headers)

    def begin_liquidation(self, case_id, headers):
        return self._request("POST", f"/trustee/cases/{case_id}/begin_liquidation",
                             {}, headers)

    def begin_distribution(self, case_id, headers):
        return self._request("POST", f"/trustee/cases/{case_id}/begin_distribution",
                             {}, headers)

    def file_no_asset_report(self, case_id, headers):
        return self._request("POST", f"/trustee/cases/{case_id}/file_no_asset_report",
                             {}, headers)

    def convert_or_dismiss(self, case_id, headers):
        return self._request("POST", f"/trustee/cases/{case_id}/convert_or_dismiss",
                             {}, headers)

    # --- Creditor ---
    def create_creditor(self, payload, headers):
        return self._request("POST", "/trustee/creditors", payload, headers)

    def get_creditor(self, creditor_id, headers):
        return self._request("GET", f"/trustee/creditors/{creditor_id}", headers=headers)

    def list_creditor_avoidance_actions(self, creditor_id, headers):
        return self._request("GET", f"/trustee/creditors/{creditor_id}/avoidance_actions",
                             headers=headers)

    # --- Claim ---
    def file_claim(self, case_id, payload, headers):
        return self._request("POST", f"/trustee/cases/{case_id}/claims", payload, headers)

    def list_case_claims(self, case_id, headers, params=None):
        return self._request("GET", f"/trustee/cases/{case_id}/claims",
                             headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/trustee/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/trustee/claims", headers=headers, params=params)

    def list_claim_dividends(self, claim_id, headers):
        return self._request("GET", f"/trustee/claims/{claim_id}/dividends", headers=headers)

    def list_claim_objections(self, claim_id, headers):
        return self._request("GET", f"/trustee/claims/{claim_id}/objections", headers=headers)

    def list_claim_encumbered_assets(self, claim_id, headers):
        return self._request("GET", f"/trustee/claims/{claim_id}/encumbered_assets",
                             headers=headers)

    def review_claim(self, claim_id, headers):
        return self._request("POST", f"/trustee/claims/{claim_id}/review", {}, headers)

    def allow_claim(self, claim_id, headers):
        return self._request("POST", f"/trustee/claims/{claim_id}/allow", {}, headers)

    def reopen_claim(self, claim_id, headers):
        return self._request("POST", f"/trustee/claims/{claim_id}/reopen", {}, headers)

    def withdraw_claim(self, claim_id, headers):
        return self._request("POST", f"/trustee/claims/{claim_id}/withdraw", {}, headers)

    # --- ClaimObjection ---
    def create_objection(self, claim_id, payload, headers):
        return self._request("POST", f"/trustee/claims/{claim_id}/objections",
                             payload, headers)

    def list_case_objections(self, case_id, headers, params=None):
        return self._request("GET", f"/trustee/cases/{case_id}/objections",
                             headers=headers, params=params)

    def get_objection(self, objection_id, headers):
        return self._request("GET", f"/trustee/objections/{objection_id}", headers=headers)

    def sustain_objection(self, objection_id, headers):
        return self._request("POST", f"/trustee/objections/{objection_id}/sustain",
                             {}, headers)

    def overrule_objection(self, objection_id, headers):
        return self._request("POST", f"/trustee/objections/{objection_id}/overrule",
                             {}, headers)

    def settle_objection(self, objection_id, payload, headers):
        return self._request("POST", f"/trustee/objections/{objection_id}/settle",
                             payload, headers)

    def withdraw_objection(self, objection_id, headers):
        return self._request("POST", f"/trustee/objections/{objection_id}/withdraw",
                             {}, headers)

    # --- Asset ---
    def create_asset(self, case_id, payload, headers):
        return self._request("POST", f"/trustee/cases/{case_id}/assets", payload, headers)

    def list_case_assets(self, case_id, headers, params=None):
        return self._request("GET", f"/trustee/cases/{case_id}/assets",
                             headers=headers, params=params)

    def get_asset(self, asset_id, headers):
        return self._request("GET", f"/trustee/assets/{asset_id}", headers=headers)

    def list_asset_sales(self, asset_id, headers):
        return self._request("GET", f"/trustee/assets/{asset_id}/sales", headers=headers)

    def investigate_asset(self, asset_id, headers):
        return self._request("POST", f"/trustee/assets/{asset_id}/investigate", {}, headers)

    def mark_asset_for_sale(self, asset_id, headers):
        return self._request("POST", f"/trustee/assets/{asset_id}/mark_for_sale",
                             {}, headers)

    def abandon_asset(self, asset_id, headers):
        return self._request("POST", f"/trustee/assets/{asset_id}/abandon", {}, headers)

    def release_exemption(self, asset_id, headers):
        return self._request("POST", f"/trustee/assets/{asset_id}/release_exemption",
                             {}, headers)

    # --- AuctionSale ---
    def create_sale(self, case_id, payload, headers):
        return self._request("POST", f"/trustee/cases/{case_id}/sales", payload, headers)

    def list_case_sales(self, case_id, headers, params=None):
        return self._request("GET", f"/trustee/cases/{case_id}/sales",
                             headers=headers, params=params)

    def get_sale(self, sale_id, headers):
        return self._request("GET", f"/trustee/sales/{sale_id}", headers=headers)

    def approve_sale(self, sale_id, headers):
        return self._request("POST", f"/trustee/sales/{sale_id}/approve", {}, headers)

    def consummate_sale(self, sale_id, headers):
        return self._request("POST", f"/trustee/sales/{sale_id}/consummate", {}, headers)

    def cancel_sale(self, sale_id, headers):
        return self._request("POST", f"/trustee/sales/{sale_id}/cancel", {}, headers)

    # --- AvoidanceAction ---
    def create_avoidance_action(self, case_id, payload, headers):
        return self._request("POST", f"/trustee/cases/{case_id}/avoidance_actions",
                             payload, headers)

    def list_case_avoidance_actions(self, case_id, headers, params=None):
        return self._request("GET", f"/trustee/cases/{case_id}/avoidance_actions",
                             headers=headers, params=params)

    def get_avoidance_action(self, action_id, headers):
        return self._request("GET", f"/trustee/avoidance_actions/{action_id}",
                             headers=headers)

    def list_action_recovery_deposits(self, action_id, headers):
        return self._request("GET",
                             f"/trustee/avoidance_actions/{action_id}/recovery_deposits",
                             headers=headers)

    def analyze_action(self, action_id, headers):
        return self._request("POST", f"/trustee/avoidance_actions/{action_id}/analyze",
                             {}, headers)

    def demand_action(self, action_id, headers):
        return self._request("POST", f"/trustee/avoidance_actions/{action_id}/demand",
                             {}, headers)

    def settle_action(self, action_id, settled_amount_cents, headers):
        return self._request("POST", f"/trustee/avoidance_actions/{action_id}/settle",
                             {"settled_amount_cents": settled_amount_cents}, headers)

    def enter_judgment(self, action_id, headers):
        return self._request("POST",
                             f"/trustee/avoidance_actions/{action_id}/enter_judgment",
                             {}, headers)

    def rescind_action(self, action_id, headers):
        return self._request("POST", f"/trustee/avoidance_actions/{action_id}/rescind",
                             {}, headers)

    def abandon_action(self, action_id, headers):
        return self._request("POST", f"/trustee/avoidance_actions/{action_id}/abandon",
                             {}, headers)

    # --- RecoveryDeposit ---
    def list_case_recovery_deposits(self, case_id, headers, params=None):
        return self._request("GET", f"/trustee/cases/{case_id}/recovery_deposits",
                             headers=headers, params=params)

    def get_recovery_deposit(self, deposit_id, headers):
        return self._request("GET", f"/trustee/recovery_deposits/{deposit_id}",
                             headers=headers)

    # --- DistributionPlan ---
    def create_plan(self, case_id, headers):
        return self._request("POST", f"/trustee/cases/{case_id}/plans", {}, headers)

    def list_case_plans(self, case_id, headers, params=None):
        return self._request("GET", f"/trustee/cases/{case_id}/plans",
                             headers=headers, params=params)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/trustee/plans/{plan_id}", headers=headers)

    def confirm_plan(self, plan_id, expected_case_version, headers):
        return self._request("POST", f"/trustee/plans/{plan_id}/confirm",
                             {"expected_case_version": expected_case_version}, headers)

    def vacate_plan(self, plan_id, headers):
        return self._request("POST", f"/trustee/plans/{plan_id}/vacate", {}, headers)

    # --- PlanClassAllocation / Dividend ---
    def list_plan_allocations(self, plan_id, headers):
        return self._request("GET", f"/trustee/plans/{plan_id}/allocations",
                             headers=headers)

    def list_plan_dividends(self, plan_id, headers, params=None):
        return self._request("GET", f"/trustee/plans/{plan_id}/dividends",
                             headers=headers, params=params)

    def get_dividend(self, dividend_id, headers):
        return self._request("GET", f"/trustee/dividends/{dividend_id}", headers=headers)

    def post_dividend(self, dividend_id, headers):
        return self._request("POST", f"/trustee/dividends/{dividend_id}/post", {}, headers)

    def void_dividend(self, dividend_id, headers):
        return self._request("POST", f"/trustee/dividends/{dividend_id}/void", {}, headers)

    # --- FeeApplication ---
    def create_fee_application(self, case_id, payload, headers):
        return self._request("POST", f"/trustee/cases/{case_id}/fee_applications",
                             payload, headers)

    def list_case_fee_applications(self, case_id, headers, params=None):
        return self._request("GET", f"/trustee/cases/{case_id}/fee_applications",
                             headers=headers, params=params)

    def get_fee_application(self, fee_id, headers):
        return self._request("GET", f"/trustee/fee_applications/{fee_id}", headers=headers)

    def approve_fee(self, fee_id, approved_amount_cents, headers):
        return self._request("POST", f"/trustee/fee_applications/{fee_id}/approve",
                             {"approved_amount_cents": approved_amount_cents}, headers)

    def deny_fee(self, fee_id, headers):
        return self._request("POST", f"/trustee/fee_applications/{fee_id}/deny",
                             {}, headers)

    def pay_fee(self, fee_id, headers):
        return self._request("POST", f"/trustee/fee_applications/{fee_id}/pay",
                             {}, headers)

    # --- FinalReport ---
    def get_final_report(self, case_id, headers):
        return self._request("GET", f"/trustee/cases/{case_id}/final_report",
                             headers=headers)

    def list_case_allocations(self, case_id, headers):
        return self._request("GET", f"/trustee/cases/{case_id}/allocations",
                             headers=headers)

    def file_final_report(self, case_id, headers):
        return self._request("POST", f"/trustee/cases/{case_id}/final_report/file",
                             {}, headers)

    def approve_final_report(self, case_id, headers):
        return self._request("POST", f"/trustee/cases/{case_id}/final_report/approve",
                             {}, headers)


api_client = ApiClient()
