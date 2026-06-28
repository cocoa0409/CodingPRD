"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD §2.9) ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers=headers)

    # --- Funds ---
    def create_fund(self, payload, headers):
        return self._request("POST", "/funds", payload, headers=headers)

    def get_fund(self, fund_id, headers):
        return self._request("GET", f"/funds/{fund_id}", headers=headers)

    def list_funds(self, headers, params=None):
        return self._request("GET", "/funds", headers=headers, params=params)

    def close_fund_to_new(self, fund_id, headers):
        return self._request("POST", f"/funds/{fund_id}/close-to-new", headers=headers)

    def wind_down_fund(self, fund_id, headers):
        return self._request("POST", f"/funds/{fund_id}/wind-down", headers=headers)

    def get_fund_report(self, fund_id, headers):
        return self._request("GET", f"/funds/{fund_id}/report", headers=headers)

    # --- Valuations ---
    def create_valuation(self, fund_id, payload, headers):
        return self._request("POST", f"/funds/{fund_id}/valuations", payload, headers=headers)

    def list_valuations(self, fund_id, headers, params=None):
        return self._request("GET", f"/funds/{fund_id}/valuations", headers=headers, params=params)

    # --- Share classes ---
    def create_share_class(self, fund_id, payload, headers):
        return self._request("POST", f"/funds/{fund_id}/share-classes", payload, headers=headers)

    def list_share_classes(self, fund_id, headers, params=None):
        return self._request("GET", f"/funds/{fund_id}/share-classes", headers=headers, params=params)

    def get_share_class(self, share_class_id, headers):
        return self._request("GET", f"/share-classes/{share_class_id}", headers=headers)

    def suspend_share_class(self, share_class_id, headers):
        return self._request("POST", f"/share-classes/{share_class_id}/suspend", headers=headers)

    def resume_share_class(self, share_class_id, headers):
        return self._request("POST", f"/share-classes/{share_class_id}/resume", headers=headers)

    # --- Projects ---
    def create_project(self, fund_id, payload, headers):
        return self._request("POST", f"/funds/{fund_id}/projects", payload, headers=headers)

    def list_projects(self, fund_id, headers, params=None):
        return self._request("GET", f"/funds/{fund_id}/projects", headers=headers, params=params)

    def stabilize_project(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/stabilize", headers=headers)

    def dispose_project(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/dispose", headers=headers)

    # --- Investors & suitability ---
    def create_investor(self, payload, headers):
        return self._request("POST", "/investors", payload, headers=headers)

    def get_investor(self, investor_id, headers):
        return self._request("GET", f"/investors/{investor_id}", headers=headers)

    def list_investors(self, headers, params=None):
        return self._request("GET", "/investors", headers=headers, params=params)

    def approve_suitability(self, investor_id, headers):
        return self._request("POST", f"/investors/{investor_id}/approve-suitability", headers=headers)

    def reject_suitability(self, investor_id, headers):
        return self._request("POST", f"/investors/{investor_id}/reject-suitability", headers=headers)

    def revoke_suitability(self, investor_id, headers):
        return self._request("POST", f"/investors/{investor_id}/revoke-suitability", headers=headers)

    # --- Tax documents ---
    def create_tax_document(self, investor_id, payload, headers):
        return self._request("POST", f"/investors/{investor_id}/tax-documents", payload, headers=headers)

    def list_investor_tax_documents(self, investor_id, headers, params=None):
        return self._request("GET", f"/investors/{investor_id}/tax-documents", headers=headers, params=params)

    def list_fund_tax_documents(self, fund_id, headers, params=None):
        return self._request("GET", f"/funds/{fund_id}/tax-documents", headers=headers, params=params)

    # --- Subscriptions & ACH ---
    def create_subscription(self, payload, headers):
        return self._request("POST", "/subscriptions", payload, headers=headers)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/subscriptions/{subscription_id}", headers=headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/subscriptions", headers=headers, params=params)

    def settle_subscription(self, subscription_id, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/settle", headers=headers)

    def cancel_subscription(self, subscription_id, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/cancel", headers=headers)

    def reverse_subscription(self, subscription_id, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/reverse", headers=headers)

    # --- Holdings ---
    def get_holding(self, holding_id, headers):
        return self._request("GET", f"/holdings/{holding_id}", headers=headers)

    def list_holdings(self, headers, params=None):
        return self._request("GET", "/holdings", headers=headers, params=params)

    def list_holding_allocations(self, holding_id, headers, params=None):
        return self._request("GET", f"/holdings/{holding_id}/allocations", headers=headers, params=params)

    def patch_holding(self, holding_id, payload, headers):
        return self._request("PATCH", f"/holdings/{holding_id}", payload, headers=headers)

    # --- Distributions & DRIP ---
    def create_distribution(self, fund_id, payload, headers):
        return self._request("POST", f"/funds/{fund_id}/distributions", payload, headers=headers)

    def list_distributions(self, fund_id, headers, params=None):
        return self._request("GET", f"/funds/{fund_id}/distributions", headers=headers, params=params)

    def get_distribution(self, distribution_id, headers):
        return self._request("GET", f"/distributions/{distribution_id}", headers=headers)

    def pay_distribution(self, distribution_id, headers):
        return self._request("POST", f"/distributions/{distribution_id}/pay", headers=headers)

    def cancel_distribution(self, distribution_id, headers):
        return self._request("POST", f"/distributions/{distribution_id}/cancel", headers=headers)

    def list_distribution_allocations(self, distribution_id, headers, params=None):
        return self._request("GET", f"/distributions/{distribution_id}/allocations", headers=headers, params=params)

    # --- Redemptions ---
    def create_redemption_request(self, payload, headers):
        return self._request("POST", "/redemption-requests", payload, headers=headers)

    def get_redemption_request(self, request_id, headers):
        return self._request("GET", f"/redemption-requests/{request_id}", headers=headers)

    def list_redemption_requests(self, headers, params=None):
        return self._request("GET", "/redemption-requests", headers=headers, params=params)

    def cancel_redemption_request(self, request_id, headers):
        return self._request("POST", f"/redemption-requests/{request_id}/cancel", headers=headers)

    def force_fulfill_redemption(self, request_id, headers):
        return self._request("POST", f"/redemption-requests/{request_id}/force-fulfill", headers=headers)

    def run_redemption_sweep(self, fund_id, headers):
        return self._request("POST", f"/funds/{fund_id}/run-redemption-sweep", headers=headers)

    def open_redemption_window(self, fund_id, headers):
        return self._request("POST", f"/funds/{fund_id}/open-redemption-window", headers=headers)


api_client = ApiClient()
