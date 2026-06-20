"""API client: one method per endpoint defined in the PRD (all under /daf)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------- Sponsor ----------------
    def create_sponsor(self, payload, headers):
        return self._request("POST", "/daf/sponsors", payload, headers)

    def get_sponsor(self, sponsor_id, headers):
        return self._request("GET", f"/daf/sponsors/{sponsor_id}", headers=headers)

    def close_quarter(self, sponsor_id, headers):
        return self._request("POST", f"/daf/sponsors/{sponsor_id}/close_quarter", {}, headers)

    # ---------------- InvestmentPool ----------------
    def create_pool(self, payload, headers):
        return self._request("POST", "/daf/pools", payload, headers)

    def get_pool(self, pool_id, headers):
        return self._request("GET", f"/daf/pools/{pool_id}", headers=headers)

    def list_pools(self, headers, params=None):
        return self._request("GET", "/daf/pools", headers=headers, params=params)

    def close_pool(self, pool_id, headers):
        return self._request("POST", f"/daf/pools/{pool_id}/close", {}, headers)

    # ---------------- NavPeriod ----------------
    def create_nav_period(self, payload, headers):
        return self._request("POST", "/daf/nav-periods", payload, headers)

    def get_nav_period(self, nav_period_id, headers):
        return self._request("GET", f"/daf/nav-periods/{nav_period_id}", headers=headers)

    def list_nav_periods(self, headers, params=None):
        return self._request("GET", "/daf/nav-periods", headers=headers, params=params)

    # ---------------- Charity ----------------
    def create_charity(self, payload, headers):
        return self._request("POST", "/daf/charities", payload, headers)

    def get_charity(self, charity_id, headers):
        return self._request("GET", f"/daf/charities/{charity_id}", headers=headers)

    def list_charities(self, headers, params=None):
        return self._request("GET", "/daf/charities", headers=headers, params=params)

    def vet_charity(self, charity_id, payload, headers):
        return self._request("POST", f"/daf/charities/{charity_id}/vet", payload, headers)

    # ---------------- DonorAccount ----------------
    def create_account(self, payload, headers):
        return self._request("POST", "/daf/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/daf/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/daf/accounts", headers=headers, params=params)

    def get_account_summary(self, account_id, headers, params=None):
        return self._request("GET", f"/daf/accounts/{account_id}/summary", headers=headers, params=params)

    def wind_down_account(self, account_id, headers):
        return self._request("POST", f"/daf/accounts/{account_id}/wind-down", {}, headers)

    def execute_succession(self, account_id, headers):
        return self._request("POST", f"/daf/accounts/{account_id}/execute-succession", {}, headers)

    # ---------------- Contribution ----------------
    def create_contribution(self, payload, headers):
        return self._request("POST", "/daf/contributions", payload, headers)

    def get_contribution(self, contribution_id, headers):
        return self._request("GET", f"/daf/contributions/{contribution_id}", headers=headers)

    def list_contributions(self, headers, params=None):
        return self._request("GET", "/daf/contributions", headers=headers, params=params)

    def settle_contribution(self, contribution_id, headers):
        return self._request("POST", f"/daf/contributions/{contribution_id}/settle", {}, headers)

    def reject_contribution(self, contribution_id, headers):
        return self._request("POST", f"/daf/contributions/{contribution_id}/reject", {}, headers)

    # ---------------- SubstantiationReceipt ----------------
    def get_receipt(self, receipt_id, headers):
        return self._request("GET", f"/daf/receipts/{receipt_id}", headers=headers)

    def list_receipts(self, headers, params=None):
        return self._request("GET", "/daf/receipts", headers=headers, params=params)

    # ---------------- PoolAllocation ----------------
    def get_allocation(self, allocation_id, headers):
        return self._request("GET", f"/daf/allocations/{allocation_id}", headers=headers)

    def list_allocations(self, headers, params=None):
        return self._request("GET", "/daf/allocations", headers=headers, params=params)

    # ---------------- RebalanceOrder ----------------
    def create_rebalance_order(self, payload, headers):
        return self._request("POST", "/daf/rebalance-orders", payload, headers)

    def get_rebalance_order(self, order_id, headers):
        return self._request("GET", f"/daf/rebalance-orders/{order_id}", headers=headers)

    def list_rebalance_orders(self, headers, params=None):
        return self._request("GET", "/daf/rebalance-orders", headers=headers, params=params)

    def execute_rebalance_order(self, order_id, headers):
        return self._request("POST", f"/daf/rebalance-orders/{order_id}/execute", {}, headers)

    def cancel_rebalance_order(self, order_id, headers):
        return self._request("POST", f"/daf/rebalance-orders/{order_id}/cancel", {}, headers)

    # ---------------- GrantRecommendation ----------------
    def create_grant(self, payload, headers):
        return self._request("POST", "/daf/grants", payload, headers)

    def get_grant(self, grant_id, headers):
        return self._request("GET", f"/daf/grants/{grant_id}", headers=headers)

    def list_grants(self, headers, params=None):
        return self._request("GET", "/daf/grants", headers=headers, params=params)

    def approve_grant(self, grant_id, headers):
        return self._request("POST", f"/daf/grants/{grant_id}/approve", {}, headers)

    def reject_grant(self, grant_id, headers):
        return self._request("POST", f"/daf/grants/{grant_id}/reject", {}, headers)

    def schedule_grant(self, grant_id, headers):
        return self._request("POST", f"/daf/grants/{grant_id}/schedule", {}, headers)

    def pay_grant(self, grant_id, headers):
        return self._request("POST", f"/daf/grants/{grant_id}/pay", {}, headers)

    def cancel_grant(self, grant_id, headers):
        return self._request("POST", f"/daf/grants/{grant_id}/cancel", {}, headers)

    # ---------------- SuccessionPlan ----------------
    def create_succession_plan(self, payload, headers):
        return self._request("POST", "/daf/succession-plans", payload, headers)

    def get_succession_plan(self, plan_id, headers):
        return self._request("GET", f"/daf/succession-plans/{plan_id}", headers=headers)

    def list_succession_plans(self, headers, params=None):
        return self._request("GET", "/daf/succession-plans", headers=headers, params=params)

    def confirm_succession_plan(self, plan_id, headers):
        return self._request("POST", f"/daf/succession-plans/{plan_id}/confirm", {}, headers)

    # ---------------- LedgerEntry ----------------
    def get_ledger_entry(self, ledger_entry_id, headers):
        return self._request("GET", f"/daf/ledger-entries/{ledger_entry_id}", headers=headers)

    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/daf/ledger-entries", headers=headers, params=params)


api_client = ApiClient()
