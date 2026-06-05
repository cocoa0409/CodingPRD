"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Plans ────────────────────────────────────────
    def create_plan(self, payload, headers):
        return self._request("POST", "/plans", payload, headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/plans", headers=headers, params=params)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/plans/{plan_id}", headers=headers)

    def archive_plan(self, plan_id, headers):
        return self._request("POST", f"/plans/{plan_id}/archive", headers=headers)

    def create_price_schedule(self, plan_id, payload, headers):
        return self._request("POST", f"/plans/{plan_id}/price-schedules", payload, headers)

    def list_price_schedules(self, plan_id, headers, params=None):
        return self._request("GET", f"/plans/{plan_id}/price-schedules", headers=headers, params=params)

    # ─── Add-ons ──────────────────────────────────────
    def create_addon(self, payload, headers):
        return self._request("POST", "/add-ons", payload, headers)

    def list_addons(self, headers, params=None):
        return self._request("GET", "/add-ons", headers=headers, params=params)

    # ─── Coupons ──────────────────────────────────────
    def create_coupon(self, payload, headers):
        return self._request("POST", "/coupons", payload, headers)

    def list_coupons(self, headers, params=None):
        return self._request("GET", "/coupons", headers=headers, params=params)

    def get_coupon(self, coupon_id, headers):
        return self._request("GET", f"/coupons/{coupon_id}", headers=headers)

    # ─── Tax jurisdictions ────────────────────────────
    def create_tax_jurisdiction(self, payload, headers):
        return self._request("POST", "/tax-jurisdictions", payload, headers)

    def list_tax_jurisdictions(self, headers, params=None):
        return self._request("GET", "/tax-jurisdictions", headers=headers, params=params)

    # ─── Accounts ─────────────────────────────────────
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def close_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/close", headers=headers)

    # ─── Subscriptions ────────────────────────────────
    def create_subscription(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/subscriptions", payload, headers)

    def list_subscriptions(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/subscriptions", headers=headers, params=params)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/subscriptions/{subscription_id}", headers=headers)

    def convert_subscription(self, account_id, subscription_id, headers):
        return self._request(
            "POST", f"/accounts/{account_id}/subscriptions/{subscription_id}/convert", headers=headers
        )

    def change_plan(self, account_id, subscription_id, payload, headers):
        return self._request(
            "POST", f"/accounts/{account_id}/subscriptions/{subscription_id}/change-plan", payload, headers
        )

    def cancel_subscription(self, account_id, subscription_id, headers):
        return self._request(
            "POST", f"/accounts/{account_id}/subscriptions/{subscription_id}/cancel", headers=headers
        )

    # ─── Subscription add-ons ─────────────────────────
    def add_subscription_addon(self, account_id, subscription_id, payload, headers):
        return self._request(
            "POST", f"/accounts/{account_id}/subscriptions/{subscription_id}/addons", payload, headers
        )

    def list_subscription_addons(self, subscription_id, headers, params=None):
        return self._request(
            "GET", f"/subscriptions/{subscription_id}/addons", headers=headers, params=params
        )

    def remove_subscription_addon(self, account_id, subscription_id, addon_id, headers):
        return self._request(
            "DELETE",
            f"/accounts/{account_id}/subscriptions/{subscription_id}/addons/{addon_id}",
            headers=headers,
        )

    # ─── Pause windows ────────────────────────────────
    def create_pause_window(self, account_id, subscription_id, payload, headers):
        return self._request(
            "POST", f"/accounts/{account_id}/subscriptions/{subscription_id}/pause-windows", payload, headers
        )

    def list_pause_windows(self, subscription_id, headers, params=None):
        return self._request(
            "GET", f"/subscriptions/{subscription_id}/pause-windows", headers=headers, params=params
        )

    def cancel_pause_window(self, account_id, subscription_id, pause_window_id, headers):
        return self._request(
            "DELETE",
            f"/accounts/{account_id}/subscriptions/{subscription_id}/pause-windows/{pause_window_id}",
            headers=headers,
        )

    # ─── Usage metering ───────────────────────────────
    def record_usage(self, account_id, subscription_id, payload, headers):
        return self._request(
            "POST", f"/accounts/{account_id}/subscriptions/{subscription_id}/usage", payload, headers
        )

    def list_usage(self, subscription_id, headers, params=None):
        return self._request(
            "GET", f"/subscriptions/{subscription_id}/usage", headers=headers, params=params
        )

    # ─── Invoices / lines / payments / revenue ────────
    def list_invoices(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoice_lines(self, invoice_id, headers, params=None):
        return self._request("GET", f"/invoices/{invoice_id}/lines", headers=headers, params=params)

    def list_invoice_payments(self, invoice_id, headers, params=None):
        return self._request("GET", f"/invoices/{invoice_id}/payments", headers=headers, params=params)

    def get_revenue_schedule(self, invoice_id, headers, params=None):
        return self._request(
            "GET", f"/invoices/{invoice_id}/revenue-schedule", headers=headers, params=params
        )

    # ─── Reporting ────────────────────────────────────
    def get_mrr_report(self, headers, params=None):
        return self._request("GET", "/reporting/mrr", headers=headers, params=params)

    # ─── Test-driving (/_ namespace) ──────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set", payload, headers)

    def set_card_state(self, payload, headers):
        return self._request("POST", "/_payments/set-card-state", payload, headers)

    def run_renewals(self, headers):
        return self._request("POST", "/_billing/run-renewals", headers=headers)

    def run_dunning(self, headers):
        return self._request("POST", "/_billing/run-dunning", headers=headers)


api_client = ApiClient()
