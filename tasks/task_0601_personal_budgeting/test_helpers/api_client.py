"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- Household ---
    def create_household(self, payload, headers):
        return self._request("POST", "/households", payload, headers)

    def get_household(self, household_id, headers):
        return self._request("GET", f"/households/{household_id}", headers=headers)

    def freeze_household(self, household_id, headers):
        return self._request("POST", f"/households/{household_id}/freeze", headers=headers)

    def unfreeze_household(self, household_id, headers):
        return self._request("POST", f"/households/{household_id}/unfreeze", headers=headers)

    def cash_flow_forecast(self, household_id, headers, params=None):
        return self._request(
            "GET", f"/households/{household_id}/cash-flow-forecast",
            headers=headers, params=params,
        )

    # --- Member ---
    def create_member(self, household_id, payload, headers):
        return self._request("POST", f"/households/{household_id}/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/households/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/households/members", headers=headers, params=params)

    # --- Account ---
    def create_account(self, household_id, payload, headers):
        return self._request("POST", f"/households/{household_id}/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/households/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/households/accounts", headers=headers, params=params)

    def archive_account(self, household_id, account_id, headers):
        return self._request(
            "POST", f"/households/{household_id}/accounts/{account_id}/archive", headers=headers
        )

    # --- Transaction ---
    def create_transaction(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/transactions", payload, headers)

    def get_transaction(self, transaction_id, headers):
        return self._request("GET", f"/households/transactions/{transaction_id}", headers=headers)

    def list_transactions(self, headers, params=None):
        return self._request("GET", "/households/transactions", headers=headers, params=params)

    def post_transaction(self, account_id, transaction_id, headers):
        return self._request(
            "POST", f"/accounts/{account_id}/transactions/{transaction_id}/post", headers=headers
        )

    def recategorize_transaction(self, account_id, transaction_id, payload, headers):
        return self._request(
            "POST", f"/accounts/{account_id}/transactions/{transaction_id}/recategorize",
            payload, headers,
        )

    def remove_transaction(self, account_id, transaction_id, headers):
        return self._request(
            "POST", f"/accounts/{account_id}/transactions/{transaction_id}/remove", headers=headers
        )

    # --- CategoryRule ---
    def create_category_rule(self, household_id, payload, headers):
        return self._request(
            "POST", f"/households/{household_id}/category-rules", payload, headers
        )

    def get_category_rule(self, rule_id, headers):
        return self._request("GET", f"/households/category-rules/{rule_id}", headers=headers)

    def list_category_rules(self, headers, params=None):
        return self._request("GET", "/households/category-rules", headers=headers, params=params)

    # --- BudgetPeriod ---
    def create_budget_period(self, household_id, payload, headers):
        return self._request(
            "POST", f"/households/{household_id}/budget-periods", payload, headers
        )

    def get_budget_period(self, period_id, headers):
        return self._request("GET", f"/households/budget-periods/{period_id}", headers=headers)

    def list_budget_periods(self, headers, params=None):
        return self._request("GET", "/households/budget-periods", headers=headers, params=params)

    def patch_budget_period(self, household_id, period_id, payload, headers):
        return self._request(
            "PATCH", f"/households/{household_id}/budget-periods/{period_id}", payload, headers
        )

    def close_budget_period(self, household_id, period_id, payload, headers):
        return self._request(
            "POST", f"/households/{household_id}/budget-periods/{period_id}/close", payload, headers
        )

    # --- BudgetCategory ---
    def create_category(self, household_id, period_id, payload, headers):
        return self._request(
            "POST", f"/households/{household_id}/budget-periods/{period_id}/categories",
            payload, headers,
        )

    def get_category(self, category_id, headers):
        return self._request("GET", f"/households/budget-categories/{category_id}", headers=headers)

    def list_categories(self, headers, params=None):
        return self._request("GET", "/households/budget-categories", headers=headers, params=params)

    def allocate_category(self, household_id, category_id, payload, headers):
        return self._request(
            "POST", f"/households/{household_id}/budget-categories/{category_id}/allocate",
            payload, headers,
        )

    # --- Goal ---
    def create_goal(self, household_id, payload, headers):
        return self._request("POST", f"/households/{household_id}/goals", payload, headers)

    def get_goal(self, goal_id, headers):
        return self._request("GET", f"/households/goals/{goal_id}", headers=headers)

    def list_goals(self, headers, params=None):
        return self._request("GET", "/households/goals", headers=headers, params=params)

    def patch_goal(self, household_id, goal_id, payload, headers):
        return self._request(
            "PATCH", f"/households/{household_id}/goals/{goal_id}", payload, headers
        )

    def contribute_goal(self, household_id, goal_id, payload, headers):
        return self._request(
            "POST", f"/households/{household_id}/goals/{goal_id}/contribute", payload, headers
        )

    def abandon_goal(self, household_id, goal_id, headers):
        return self._request(
            "POST", f"/households/{household_id}/goals/{goal_id}/abandon", headers=headers
        )

    def get_goal_contribution(self, contribution_id, headers):
        return self._request(
            "GET", f"/households/goal-contributions/{contribution_id}", headers=headers
        )

    def list_goal_contributions(self, headers, params=None):
        return self._request(
            "GET", "/households/goal-contributions", headers=headers, params=params
        )

    # --- RecurringBill ---
    def create_recurring_bill(self, household_id, payload, headers):
        return self._request(
            "POST", f"/households/{household_id}/recurring-bills", payload, headers
        )

    def get_recurring_bill(self, bill_id, headers):
        return self._request("GET", f"/households/recurring-bills/{bill_id}", headers=headers)

    def list_recurring_bills(self, headers, params=None):
        return self._request("GET", "/households/recurring-bills", headers=headers, params=params)

    def pause_recurring_bill(self, household_id, bill_id, headers):
        return self._request(
            "POST", f"/households/{household_id}/recurring-bills/{bill_id}/pause", headers=headers
        )

    def resume_recurring_bill(self, household_id, bill_id, headers):
        return self._request(
            "POST", f"/households/{household_id}/recurring-bills/{bill_id}/resume", headers=headers
        )


api_client = ApiClient()
