"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------- Catalog (ShippingZone / Plan / Meal) ----------------
    def create_shipping_zone(self, payload, headers):
        return self._request("POST", "/shipping-zones", payload, headers)

    def create_plan(self, payload, headers):
        return self._request("POST", "/plans", payload, headers)

    def create_meal(self, payload, headers):
        return self._request("POST", "/meals", payload, headers)

    def list_meals(self, headers, params=None):
        return self._request("GET", "/meals", headers=headers, params=params)

    # ---------------- ProductionRun ----------------
    def create_production_run(self, payload, headers):
        return self._request("POST", "/production-runs", payload, headers)

    def open_production_run(self, run_id, headers):
        return self._request("POST", f"/production-runs/{run_id}/open", {}, headers)

    def cancel_production_run(self, run_id, headers):
        return self._request("POST", f"/production-runs/{run_id}/cancel", {}, headers)

    def complete_production_run(self, run_id, headers):
        return self._request("POST", f"/production-runs/{run_id}/complete", {}, headers)

    def get_production_run(self, run_id, headers):
        return self._request("GET", f"/production-runs/{run_id}", headers=headers)

    def list_production_runs(self, headers, params=None):
        return self._request("GET", "/production-runs", headers=headers, params=params)

    # ---------------- Customer ----------------
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    def create_credit(self, customer_id, payload, headers):
        return self._request("POST", f"/customers/{customer_id}/credits", payload, headers)

    # ---------------- Subscription ----------------
    def create_subscription(self, payload, headers):
        return self._request("POST", "/subscriptions", payload, headers)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/subscriptions/{subscription_id}", headers=headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/subscriptions", headers=headers, params=params)

    def cancel_subscription(self, subscription_id, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/cancel", {}, headers)

    def create_pause_window(self, subscription_id, payload, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/pause-windows", payload, headers)

    def list_pause_windows(self, subscription_id, headers, params=None):
        return self._request("GET", f"/subscriptions/{subscription_id}/pause-windows", headers=headers, params=params)

    def create_plan_change(self, subscription_id, payload, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/plan-changes", payload, headers)

    def get_plan_change(self, plan_change_id, headers):
        return self._request("GET", f"/plan-changes/{plan_change_id}", headers=headers)

    def list_plan_changes(self, headers, params=None):
        return self._request("GET", "/plan-changes", headers=headers, params=params)

    # ---------------- Box + selection ----------------
    def create_box(self, subscription_id, payload, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/boxes", payload, headers)

    def get_box(self, box_id, headers):
        return self._request("GET", f"/boxes/{box_id}", headers=headers)

    def list_boxes(self, headers, params=None):
        return self._request("GET", "/boxes", headers=headers, params=params)

    def create_box_item(self, box_id, payload, headers):
        return self._request("POST", f"/boxes/{box_id}/items", payload, headers)

    def get_box_item(self, item_id, headers):
        return self._request("GET", f"/box-items/{item_id}", headers=headers)

    def list_box_items(self, headers, params=None):
        return self._request("GET", "/box-items", headers=headers, params=params)

    def swap_box_item(self, item_id, payload, headers):
        return self._request("POST", f"/box-items/{item_id}/swap", payload, headers)

    def skip_box(self, box_id, headers):
        return self._request("POST", f"/boxes/{box_id}/skip", {}, headers)

    def lock_box(self, box_id, headers):
        return self._request("POST", f"/boxes/{box_id}/lock", {}, headers)

    def ship_box(self, box_id, headers):
        return self._request("POST", f"/boxes/{box_id}/ship", {}, headers)

    def deliver_box(self, box_id, headers):
        return self._request("POST", f"/boxes/{box_id}/deliver", {}, headers)

    def cancel_box(self, box_id, headers):
        return self._request("POST", f"/boxes/{box_id}/cancel", {}, headers)

    # ---------------- Referral + credit ledger ----------------
    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/referrals/{referral_id}", headers=headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/referrals", headers=headers, params=params)

    def get_credit_ledger(self, credit_id, headers):
        return self._request("GET", f"/credit-ledger/{credit_id}", headers=headers)

    def list_credit_ledger(self, headers, params=None):
        return self._request("GET", "/credit-ledger", headers=headers, params=params)

    # ---------------- Test-driving (/_ namespace) ----------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def simulate_payment(self, payload, headers):
        return self._request("POST", "/_payments/simulate", payload, headers)


api_client = ApiClient()
