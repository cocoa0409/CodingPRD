"""API client: one method per endpoint defined in the PRD (§4 routing table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/coopcare/_clock/set_current_utc", payload, headers)

    # --- households ---
    def create_household(self, payload, headers):
        return self._request("POST", "/coopcare/households", payload, headers)

    def get_household(self, household_id, headers):
        return self._request("GET", f"/coopcare/households/{household_id}", headers=headers)

    def suspend_household(self, household_id, headers):
        return self._request("POST", f"/coopcare/households/{household_id}/suspend", headers=headers)

    def reinstate_household(self, household_id, headers):
        return self._request("POST", f"/coopcare/households/{household_id}/reinstate", headers=headers)

    def adjust_wallet(self, household_id, payload, headers):
        return self._request("POST", f"/coopcare/households/{household_id}/wallet-adjustments", payload, headers)

    # --- configuration ---
    def create_subscription_plan(self, payload, headers):
        return self._request("POST", "/coopcare/subscription-plans", payload, headers)

    def create_product(self, payload, headers):
        return self._request("POST", "/coopcare/products", payload, headers)

    def create_seasonal_window(self, payload, headers):
        return self._request("POST", "/coopcare/seasonal-windows", payload, headers)

    # --- subscriptions ---
    def create_subscription(self, payload, headers):
        return self._request("POST", "/coopcare/subscriptions", payload, headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/coopcare/subscriptions", headers=headers, params=params)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/coopcare/subscriptions/{subscription_id}", headers=headers)

    def pause_subscription(self, subscription_id, headers):
        return self._request("POST", f"/coopcare/subscriptions/{subscription_id}/pause", headers=headers)

    def resume_subscription(self, subscription_id, headers):
        return self._request("POST", f"/coopcare/subscriptions/{subscription_id}/resume", headers=headers)

    def cancel_subscription(self, subscription_id, headers):
        return self._request("POST", f"/coopcare/subscriptions/{subscription_id}/cancel", headers=headers)

    def create_plan_change(self, subscription_id, payload, headers):
        return self._request("POST", f"/coopcare/subscriptions/{subscription_id}/plan-changes", payload, headers)

    def renew_subscription_period(self, subscription_id, headers):
        return self._request("POST", f"/coopcare/subscriptions/{subscription_id}/renew-period", headers=headers)

    # --- coop sites ---
    def create_coop_site(self, payload, headers):
        return self._request("POST", "/coopcare/coop-sites", payload, headers)

    def list_coop_sites(self, headers, params=None):
        return self._request("GET", "/coopcare/coop-sites", headers=headers, params=params)

    def get_coop_site(self, coop_site_id, headers):
        return self._request("GET", f"/coopcare/coop-sites/{coop_site_id}", headers=headers)

    # --- service visits ---
    def create_service_visit(self, payload, headers):
        return self._request("POST", "/coopcare/service-visits", payload, headers)

    def list_service_visits(self, headers, params=None):
        return self._request("GET", "/coopcare/service-visits", headers=headers, params=params)

    def get_service_visit(self, visit_id, headers):
        return self._request("GET", f"/coopcare/service-visits/{visit_id}", headers=headers)

    def assign_service_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/coopcare/service-visits/{visit_id}/assign", payload, headers)

    def request_reschedule(self, visit_id, headers):
        return self._request("POST", f"/coopcare/service-visits/{visit_id}/request-reschedule", headers=headers)

    def check_in_visit(self, visit_id, headers):
        return self._request("POST", f"/coopcare/service-visits/{visit_id}/check-in", headers=headers)

    def complete_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/coopcare/service-visits/{visit_id}/complete", payload, headers)

    def mark_no_show(self, visit_id, headers, payload=None):
        return self._request("POST", f"/coopcare/service-visits/{visit_id}/mark-no-show", payload, headers)

    def cancel_visit(self, visit_id, headers):
        return self._request("POST", f"/coopcare/service-visits/{visit_id}/cancel", headers=headers)

    # --- sitting engagements ---
    def create_sitting_engagement(self, payload, headers):
        return self._request("POST", "/coopcare/sitting-engagements", payload, headers)

    def list_sitting_engagements(self, headers, params=None):
        return self._request("GET", "/coopcare/sitting-engagements", headers=headers, params=params)

    def get_sitting_engagement(self, engagement_id, headers):
        return self._request("GET", f"/coopcare/sitting-engagements/{engagement_id}", headers=headers)

    def quote_engagement(self, engagement_id, headers):
        return self._request("POST", f"/coopcare/sitting-engagements/{engagement_id}/quote", headers=headers)

    def confirm_engagement(self, engagement_id, headers):
        return self._request("POST", f"/coopcare/sitting-engagements/{engagement_id}/confirm", headers=headers)

    def cancel_engagement(self, engagement_id, headers):
        return self._request("POST", f"/coopcare/sitting-engagements/{engagement_id}/cancel", headers=headers)

    def settle_engagement(self, engagement_id, headers):
        return self._request("POST", f"/coopcare/sitting-engagements/{engagement_id}/settle", headers=headers)

    # --- sitting routes / stops ---
    def create_sitting_route(self, payload, headers):
        return self._request("POST", "/coopcare/sitting-routes", payload, headers)

    def get_sitting_route(self, route_id, headers):
        return self._request("GET", f"/coopcare/sitting-routes/{route_id}", headers=headers)

    def publish_sitting_route(self, route_id, headers):
        return self._request("POST", f"/coopcare/sitting-routes/{route_id}/publish", headers=headers)

    def cancel_sitting_route(self, route_id, headers):
        return self._request("POST", f"/coopcare/sitting-routes/{route_id}/cancel", headers=headers)

    def add_route_stop(self, route_id, payload, headers):
        return self._request("POST", f"/coopcare/sitting-routes/{route_id}/stops", payload, headers)

    def list_route_stops(self, headers, params=None):
        return self._request("GET", "/coopcare/route-stops", headers=headers, params=params)

    def get_route_stop(self, stop_id, headers):
        return self._request("GET", f"/coopcare/route-stops/{stop_id}", headers=headers)

    def complete_route_stop(self, stop_id, headers):
        return self._request("POST", f"/coopcare/route-stops/{stop_id}/complete", headers=headers)

    def skip_route_stop(self, stop_id, headers, payload=None):
        return self._request("POST", f"/coopcare/route-stops/{stop_id}/skip", payload, headers)

    # --- supply orders ---
    def create_supply_order(self, payload, headers):
        return self._request("POST", "/coopcare/supply-orders", payload, headers)

    def list_supply_orders(self, headers, params=None):
        return self._request("GET", "/coopcare/supply-orders", headers=headers, params=params)

    def get_supply_order(self, order_id, headers):
        return self._request("GET", f"/coopcare/supply-orders/{order_id}", headers=headers)

    def add_order_line(self, order_id, payload, headers):
        return self._request("POST", f"/coopcare/supply-orders/{order_id}/lines", payload, headers)

    def place_order(self, order_id, headers):
        return self._request("POST", f"/coopcare/supply-orders/{order_id}/place", headers=headers)

    # --- invoices ---
    def create_invoice(self, payload, headers):
        return self._request("POST", "/coopcare/invoices", payload, headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/coopcare/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/coopcare/invoices/{invoice_id}", headers=headers)

    def list_invoice_lines(self, invoice_id, headers, params=None):
        return self._request("GET", f"/coopcare/invoices/{invoice_id}/lines", headers=headers, params=params)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/coopcare/invoices/{invoice_id}/issue", headers=headers)

    def mark_invoice_paid(self, invoice_id, headers):
        return self._request("POST", f"/coopcare/invoices/{invoice_id}/mark-paid", headers=headers)

    def dispute_invoice(self, invoice_id, headers, payload=None):
        return self._request("POST", f"/coopcare/invoices/{invoice_id}/dispute", payload, headers)

    def resolve_invoice_dispute(self, invoice_id, payload, headers):
        return self._request("POST", f"/coopcare/invoices/{invoice_id}/resolve-dispute", payload, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/coopcare/invoices/{invoice_id}/void", headers=headers)


api_client = ApiClient()
