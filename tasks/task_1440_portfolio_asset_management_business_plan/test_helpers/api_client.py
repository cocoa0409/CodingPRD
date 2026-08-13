"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/api/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- Portfolio ---
    def create_portfolio(self, payload, headers):
        return self._request("POST", "/api/portfolios", payload, headers)

    def get_portfolio(self, portfolio_id, headers):
        return self._request("GET", f"/api/portfolios/{portfolio_id}", headers=headers)

    def archive_portfolio(self, portfolio_id, headers):
        return self._request("POST", f"/api/portfolios/{portfolio_id}/archive", {}, headers)

    def get_portfolio_performance_report(self, portfolio_id, headers):
        return self._request("GET", f"/api/portfolios/{portfolio_id}/performance-report",
                             headers=headers)

    def list_portfolio_assets(self, portfolio_id, headers, params=None):
        return self._request("GET", f"/api/portfolios/{portfolio_id}/assets",
                             headers=headers, params=params)

    # --- PropertyManager ---
    def create_property_manager(self, payload, headers):
        return self._request("POST", "/api/property-managers", payload, headers)

    def get_property_manager(self, manager_id, headers):
        return self._request("GET", f"/api/property-managers/{manager_id}", headers=headers)

    def suspend_property_manager(self, manager_id, payload, headers):
        return self._request("POST", f"/api/property-managers/{manager_id}/suspend",
                             payload, headers)

    def reinstate_property_manager(self, manager_id, headers):
        return self._request("POST", f"/api/property-managers/{manager_id}/reinstate",
                             {}, headers)

    def list_property_manager_assets(self, manager_id, headers, params=None):
        return self._request("GET", f"/api/property-managers/{manager_id}/assets",
                             headers=headers, params=params)

    def list_property_manager_scorecards(self, manager_id, headers, params=None):
        return self._request("GET",
                             f"/api/property-managers/{manager_id}/performance-scorecards",
                             headers=headers, params=params)

    # --- Asset ---
    def create_asset(self, payload, headers):
        return self._request("POST", "/api/assets", payload, headers)

    def get_asset(self, asset_id, headers):
        return self._request("GET", f"/api/assets/{asset_id}", headers=headers)

    def record_sale(self, asset_id, payload, headers):
        return self._request("POST", f"/api/assets/{asset_id}/record-sale", payload, headers)

    def list_asset_business_plans(self, asset_id, headers, params=None):
        return self._request("GET", f"/api/assets/{asset_id}/business-plans",
                             headers=headers, params=params)

    def list_asset_capital_projects(self, asset_id, headers, params=None):
        return self._request("GET", f"/api/assets/{asset_id}/capital-projects",
                             headers=headers, params=params)

    def list_asset_lease_strategies(self, asset_id, headers, params=None):
        return self._request("GET", f"/api/assets/{asset_id}/lease-strategies",
                             headers=headers, params=params)

    def list_asset_loans(self, asset_id, headers, params=None):
        return self._request("GET", f"/api/assets/{asset_id}/loans",
                             headers=headers, params=params)

    def list_asset_valuations(self, asset_id, headers, params=None):
        return self._request("GET", f"/api/assets/{asset_id}/valuations",
                             headers=headers, params=params)

    def list_asset_performance_scorecards(self, asset_id, headers, params=None):
        return self._request("GET", f"/api/assets/{asset_id}/performance-scorecards",
                             headers=headers, params=params)

    def list_asset_disposition_decisions(self, asset_id, headers, params=None):
        return self._request("GET", f"/api/assets/{asset_id}/disposition-decisions",
                             headers=headers, params=params)

    # --- BusinessPlan ---
    def create_business_plan(self, payload, headers):
        return self._request("POST", "/api/business-plans", payload, headers)

    def get_business_plan(self, plan_id, headers):
        return self._request("GET", f"/api/business-plans/{plan_id}", headers=headers)

    def submit_business_plan(self, plan_id, headers):
        return self._request("POST", f"/api/business-plans/{plan_id}/submit", {}, headers)

    def approve_business_plan(self, plan_id, headers):
        return self._request("POST", f"/api/business-plans/{plan_id}/approve", {}, headers)

    def reject_business_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/api/business-plans/{plan_id}/reject", payload, headers)

    def get_business_plan_variance_summary(self, plan_id, headers):
        return self._request("GET", f"/api/business-plans/{plan_id}/variance-summary",
                             headers=headers)

    def list_business_plan_budget_lines(self, plan_id, headers, params=None):
        return self._request("GET", f"/api/business-plans/{plan_id}/budget-lines",
                             headers=headers, params=params)

    def list_business_plan_actuals_reports(self, plan_id, headers, params=None):
        return self._request("GET", f"/api/business-plans/{plan_id}/actuals-reports",
                             headers=headers, params=params)

    def list_business_plan_capital_projects(self, plan_id, headers, params=None):
        return self._request("GET", f"/api/business-plans/{plan_id}/capital-projects",
                             headers=headers, params=params)

    def list_business_plan_reforecasts(self, plan_id, headers, params=None):
        return self._request("GET", f"/api/business-plans/{plan_id}/reforecasts",
                             headers=headers, params=params)

    # --- BudgetLine ---
    def create_budget_lines(self, payload, headers):
        return self._request("POST", "/api/budget-lines", payload, headers)

    # --- ActualsReport ---
    def create_actuals_report(self, payload, headers):
        return self._request("POST", "/api/actuals-reports", payload, headers)

    def accept_actuals_report(self, report_id, headers):
        return self._request("POST", f"/api/actuals-reports/{report_id}/accept", {}, headers)

    def reject_actuals_report(self, report_id, payload, headers):
        return self._request("POST", f"/api/actuals-reports/{report_id}/reject",
                             payload, headers)

    # --- CapitalProject ---
    def create_capital_project(self, payload, headers):
        return self._request("POST", "/api/capital-projects", payload, headers)

    def get_capital_project(self, project_id, headers):
        return self._request("GET", f"/api/capital-projects/{project_id}", headers=headers)

    def approve_capital_project(self, project_id, payload, headers):
        return self._request("POST", f"/api/capital-projects/{project_id}/approve",
                             payload, headers)

    def reject_capital_project(self, project_id, payload, headers):
        return self._request("POST", f"/api/capital-projects/{project_id}/reject",
                             payload, headers)

    def start_capital_project(self, project_id, headers):
        return self._request("POST", f"/api/capital-projects/{project_id}/start", {}, headers)

    def complete_capital_project(self, project_id, headers):
        return self._request("POST", f"/api/capital-projects/{project_id}/complete",
                             {}, headers)

    def cancel_capital_project(self, project_id, headers):
        return self._request("POST", f"/api/capital-projects/{project_id}/cancel", {}, headers)

    def list_capital_project_funding_draws(self, project_id, headers, params=None):
        return self._request("GET", f"/api/capital-projects/{project_id}/funding-draws",
                             headers=headers, params=params)

    # --- FundingDraw ---
    def create_funding_draw(self, payload, headers):
        return self._request("POST", "/api/funding-draws", payload, headers)

    def approve_funding_draw(self, draw_id, headers):
        return self._request("POST", f"/api/funding-draws/{draw_id}/approve", {}, headers)

    def reject_funding_draw(self, draw_id, payload, headers):
        return self._request("POST", f"/api/funding-draws/{draw_id}/reject", payload, headers)

    def release_funding_draw(self, draw_id, headers):
        return self._request("POST", f"/api/funding-draws/{draw_id}/release", {}, headers)

    # --- LeaseStrategy ---
    def create_lease_strategy(self, payload, headers):
        return self._request("POST", "/api/lease-strategies", payload, headers)

    def recommend_lease_strategy(self, strategy_id, headers):
        return self._request("POST", f"/api/lease-strategies/{strategy_id}/recommend",
                             {}, headers)

    def ratify_lease_strategy(self, strategy_id, headers):
        return self._request("POST", f"/api/lease-strategies/{strategy_id}/ratify",
                             {}, headers)

    def reject_lease_strategy(self, strategy_id, payload, headers):
        return self._request("POST", f"/api/lease-strategies/{strategy_id}/reject",
                             payload, headers)

    # --- Loan / Covenant / CovenantTest ---
    def create_loan(self, payload, headers):
        return self._request("POST", "/api/loans", payload, headers)

    def get_loan(self, loan_id, headers):
        return self._request("GET", f"/api/loans/{loan_id}", headers=headers)

    def list_loan_covenants(self, loan_id, headers, params=None):
        return self._request("GET", f"/api/loans/{loan_id}/covenants",
                             headers=headers, params=params)

    def list_loan_lender_reports(self, loan_id, headers, params=None):
        return self._request("GET", f"/api/loans/{loan_id}/lender-reports",
                             headers=headers, params=params)

    def create_covenant(self, payload, headers):
        return self._request("POST", "/api/covenants", payload, headers)

    def get_covenant(self, covenant_id, headers):
        return self._request("GET", f"/api/covenants/{covenant_id}", headers=headers)

    def waive_covenant(self, covenant_id, headers):
        return self._request("POST", f"/api/covenants/{covenant_id}/waive", {}, headers)

    def list_covenant_tests(self, covenant_id, headers, params=None):
        return self._request("GET", f"/api/covenants/{covenant_id}/covenant-tests",
                             headers=headers, params=params)

    def create_covenant_test(self, payload, headers):
        return self._request("POST", "/api/covenant-tests", payload, headers)

    # --- Valuation ---
    def create_valuation(self, payload, headers):
        return self._request("POST", "/api/valuations", payload, headers)

    def confirm_valuation(self, valuation_id, payload, headers):
        return self._request("POST", f"/api/valuations/{valuation_id}/confirm",
                             payload, headers)

    # --- PerformanceScorecard ---
    def create_performance_scorecard(self, payload, headers):
        return self._request("POST", "/api/performance-scorecards", payload, headers)

    def review_performance_scorecard(self, scorecard_id, headers):
        return self._request("POST", f"/api/performance-scorecards/{scorecard_id}/review",
                             {}, headers)

    def finalize_performance_scorecard(self, scorecard_id, headers):
        return self._request("POST", f"/api/performance-scorecards/{scorecard_id}/finalize",
                             {}, headers)

    # --- ReForecast ---
    def create_reforecast(self, payload, headers):
        return self._request("POST", "/api/reforecasts", payload, headers)

    def submit_reforecast(self, reforecast_id, headers):
        return self._request("POST", f"/api/reforecasts/{reforecast_id}/submit", {}, headers)

    def accept_reforecast(self, reforecast_id, payload, headers):
        return self._request("POST", f"/api/reforecasts/{reforecast_id}/accept",
                             payload, headers)

    def reject_reforecast(self, reforecast_id, payload, headers):
        return self._request("POST", f"/api/reforecasts/{reforecast_id}/reject",
                             payload, headers)

    # --- DispositionDecision ---
    def create_disposition_decision(self, payload, headers):
        return self._request("POST", "/api/disposition-decisions", payload, headers)

    def submit_disposition_review(self, decision_id, headers):
        return self._request("POST",
                             f"/api/disposition-decisions/{decision_id}/submit-review",
                             {}, headers)

    def ratify_disposition_decision(self, decision_id, headers):
        return self._request("POST", f"/api/disposition-decisions/{decision_id}/ratify",
                             {}, headers)

    def shelve_disposition_decision(self, decision_id, payload, headers):
        return self._request("POST", f"/api/disposition-decisions/{decision_id}/shelve",
                             payload, headers)

    def execute_disposition_decision(self, decision_id, payload, headers):
        return self._request("POST", f"/api/disposition-decisions/{decision_id}/execute",
                             payload, headers)

    # --- LenderReport ---
    def create_lender_report(self, payload, headers):
        return self._request("POST", "/api/lender-reports", payload, headers)

    def submit_lender_report(self, report_id, headers):
        return self._request("POST", f"/api/lender-reports/{report_id}/submit", {}, headers)

    def acknowledge_lender_report(self, report_id, headers):
        return self._request("POST", f"/api/lender-reports/{report_id}/acknowledge",
                             {}, headers)


api_client = ApiClient()
