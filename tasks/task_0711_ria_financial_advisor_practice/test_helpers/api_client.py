"""API client: one method per endpoint defined in the RIA Practice PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----- Logical clock ---------------------------------------------------- #
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ----- FeeSchedule ------------------------------------------------------ #
    def create_fee_schedule(self, payload, headers):
        return self._request("POST", "/fee-schedules", payload, headers)

    def get_fee_schedule(self, schedule_id, headers):
        return self._request("GET", f"/fee-schedules/{schedule_id}", headers=headers)

    def list_fee_schedules(self, headers, params=None):
        return self._request("GET", "/fee-schedules", headers=headers, params=params)

    def patch_fee_schedule(self, schedule_id, payload, headers):
        return self._request("PATCH", f"/fee-schedules/{schedule_id}", payload, headers)

    # ----- Portfolio -------------------------------------------------------- #
    def create_portfolio(self, payload, headers):
        return self._request("POST", "/portfolios", payload, headers)

    def publish_portfolio(self, portfolio_id, headers):
        return self._request("POST", f"/portfolios/{portfolio_id}/publish", {}, headers)

    def get_portfolio(self, portfolio_id, headers):
        return self._request("GET", f"/portfolios/{portfolio_id}", headers=headers)

    def list_portfolios(self, headers, params=None):
        return self._request("GET", "/portfolios", headers=headers, params=params)

    # ----- Household -------------------------------------------------------- #
    def create_household(self, payload, headers):
        return self._request("POST", "/households", payload, headers)

    def get_household(self, household_id, headers):
        return self._request("GET", f"/households/{household_id}", headers=headers)

    def list_households(self, headers, params=None):
        return self._request("GET", "/households", headers=headers, params=params)

    def close_household(self, household_id, headers):
        return self._request("POST", f"/households/{household_id}/close", {}, headers)

    def list_household_clients(self, household_id, headers, params=None):
        return self._request("GET", f"/households/{household_id}/clients",
                             headers=headers, params=params)

    def list_household_accounts(self, household_id, headers, params=None):
        return self._request("GET", f"/households/{household_id}/accounts",
                             headers=headers, params=params)

    # ----- Client ----------------------------------------------------------- #
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/clients", headers=headers, params=params)

    def client_state(self, client_id, action, headers):
        return self._request("POST", f"/clients/{client_id}/state",
                             {"action": action}, headers)

    # ----- InvestmentPolicyStatement ---------------------------------------- #
    def create_ips(self, payload, headers):
        return self._request("POST", "/investment-policy-statements", payload, headers)

    def get_ips(self, ips_id, headers):
        return self._request("GET", f"/investment-policy-statements/{ips_id}",
                             headers=headers)

    def list_ips(self, headers, params=None):
        return self._request("GET", "/investment-policy-statements",
                             headers=headers, params=params)

    def ips_state(self, ips_id, action, headers):
        return self._request("POST", f"/investment-policy-statements/{ips_id}/state",
                             {"action": action}, headers)

    # ----- Account ---------------------------------------------------------- #
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/accounts", headers=headers, params=params)

    def valuate_account(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/valuation", payload, headers)

    def account_state(self, account_id, action, headers):
        return self._request("POST", f"/accounts/{account_id}/state",
                             {"action": action}, headers)

    def list_account_rebalance_orders(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/rebalance-orders",
                             headers=headers, params=params)

    # ----- FeeRun ----------------------------------------------------------- #
    def create_fee_run(self, payload, headers):
        return self._request("POST", "/fee-runs", payload, headers)

    def get_fee_run(self, fee_run_id, headers):
        return self._request("GET", f"/fee-runs/{fee_run_id}", headers=headers)

    def list_fee_runs(self, headers, params=None):
        return self._request("GET", "/fee-runs", headers=headers, params=params)

    def fee_run_state(self, fee_run_id, action, headers):
        return self._request("POST", f"/fee-runs/{fee_run_id}/state",
                             {"action": action}, headers)

    # ----- FinancialPlan ---------------------------------------------------- #
    def create_financial_plan(self, payload, headers):
        return self._request("POST", "/financial-plans", payload, headers)

    def get_financial_plan(self, plan_id, headers):
        return self._request("GET", f"/financial-plans/{plan_id}", headers=headers)

    def list_financial_plans(self, headers, params=None):
        return self._request("GET", "/financial-plans", headers=headers, params=params)

    def financial_plan_state(self, plan_id, action, headers):
        return self._request("POST", f"/financial-plans/{plan_id}/state",
                             {"action": action}, headers)

    def list_plan_goals(self, plan_id, headers, params=None):
        return self._request("GET", f"/financial-plans/{plan_id}/goals",
                             headers=headers, params=params)

    # ----- Goal ------------------------------------------------------------- #
    def create_goal(self, payload, headers):
        return self._request("POST", "/goals", payload, headers)

    def get_goal(self, goal_id, headers):
        return self._request("GET", f"/goals/{goal_id}", headers=headers)

    def fund_goal(self, goal_id, amount_cents, headers):
        return self._request("POST", f"/goals/{goal_id}/fund",
                             {"amount_cents": amount_cents}, headers)

    # ----- RebalanceOrder --------------------------------------------------- #
    def create_rebalance_order(self, payload, headers):
        return self._request("POST", "/rebalance-orders", payload, headers)

    def get_rebalance_order(self, order_id, headers):
        return self._request("GET", f"/rebalance-orders/{order_id}", headers=headers)

    def list_rebalance_orders(self, headers, params=None):
        return self._request("GET", "/rebalance-orders", headers=headers, params=params)

    def rebalance_order_state(self, order_id, action, headers):
        return self._request("POST", f"/rebalance-orders/{order_id}/state",
                             {"action": action}, headers)

    # ----- Review ----------------------------------------------------------- #
    def create_review(self, payload, headers):
        return self._request("POST", "/reviews", payload, headers)

    def get_review(self, review_id, headers):
        return self._request("GET", f"/reviews/{review_id}", headers=headers)

    def list_reviews(self, headers, params=None):
        return self._request("GET", "/reviews", headers=headers, params=params)

    def complete_review(self, review_id, headers):
        return self._request("POST", f"/reviews/{review_id}/complete", {}, headers)

    # ----- ComplianceItem --------------------------------------------------- #
    def create_compliance_item(self, payload, headers):
        return self._request("POST", "/compliance-items", payload, headers)

    def get_compliance_item(self, item_id, headers):
        return self._request("GET", f"/compliance-items/{item_id}", headers=headers)

    def list_compliance_items(self, headers, params=None):
        return self._request("GET", "/compliance-items", headers=headers, params=params)

    def compliance_item_state(self, item_id, action, headers):
        return self._request("POST", f"/compliance-items/{item_id}/state",
                             {"action": action}, headers)


api_client = ApiClient()
