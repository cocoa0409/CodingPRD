"""API client: one method per endpoint defined in the PRD.

Server URL is supplied by the runner via API_BASE_URL env var; the framework
GenericApiClient handles the underlying _request.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----- Customers -----
    def create_customer(self, payload, headers):
        return self._request("POST", "/api/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/api/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/api/customers", headers=headers, params=params)

    # ----- Yards -----
    def create_yard(self, payload, headers):
        return self._request("POST", "/api/yards", payload, headers)

    def get_yard(self, yard_id, headers):
        return self._request("GET", f"/api/yards/{yard_id}", headers=headers)

    def list_yards(self, headers, params=None):
        return self._request("GET", "/api/yards", headers=headers, params=params)

    def update_yard(self, yard_id, payload, headers):
        return self._request("PUT", f"/api/yards/{yard_id}", payload, headers)

    # ----- PropertyAccessProfile -----
    def create_access_profile(self, yard_id, payload, headers):
        return self._request("POST", f"/api/yards/{yard_id}/access-profile", payload, headers)

    def get_yard_access_profile(self, yard_id, headers):
        return self._request("GET", f"/api/yards/{yard_id}/access-profile", headers=headers)

    def list_access_profiles(self, headers, params=None):
        return self._request("GET", "/api/property-access-profiles", headers=headers, params=params)

    def verify_access_profile(self, profile_id, headers):
        return self._request("POST", f"/api/property-access-profiles/{profile_id}/verify", {}, headers)

    def suspend_access_profile(self, profile_id, payload, headers):
        return self._request("POST", f"/api/property-access-profiles/{profile_id}/suspend", payload, headers)

    def require_reverification_access_profile(self, profile_id, headers):
        return self._request(
            "POST",
            f"/api/property-access-profiles/{profile_id}/require-reverification",
            {},
            headers,
        )

    # ----- SubscriptionPlans -----
    def create_subscription_plan(self, payload, headers):
        return self._request("POST", "/api/subscription-plans", payload, headers)

    def list_subscription_plans(self, headers, params=None):
        return self._request("GET", "/api/subscription-plans", headers=headers, params=params)

    def get_subscription_plan(self, plan_id, headers):
        return self._request("GET", f"/api/subscription-plans/{plan_id}", headers=headers)

    # ----- ServiceAddons -----
    def create_service_addon(self, payload, headers):
        return self._request("POST", "/api/service-addons", payload, headers)

    def list_service_addons(self, headers, params=None):
        return self._request("GET", "/api/service-addons", headers=headers, params=params)

    # ----- Subscriptions -----
    def create_subscription(self, payload, headers):
        return self._request("POST", "/api/subscriptions", payload, headers)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/api/subscriptions/{subscription_id}", headers=headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/api/subscriptions", headers=headers, params=params)

    def activate_subscription(self, subscription_id, headers):
        return self._request("POST", f"/api/subscriptions/{subscription_id}/activate", {}, headers)

    def pause_subscription(self, subscription_id, headers):
        return self._request("POST", f"/api/subscriptions/{subscription_id}/pause", {}, headers)

    def resume_subscription(self, subscription_id, headers):
        return self._request("POST", f"/api/subscriptions/{subscription_id}/resume", {}, headers)

    def cancel_subscription(self, subscription_id, headers):
        return self._request("POST", f"/api/subscriptions/{subscription_id}/cancel", {}, headers)

    def plan_change_subscription(self, subscription_id, payload, headers):
        return self._request("POST", f"/api/subscriptions/{subscription_id}/plan-change", payload, headers)

    # ----- Technicians -----
    def create_technician(self, payload, headers):
        return self._request("POST", "/api/technicians", payload, headers)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"/api/technicians/{technician_id}", headers=headers)

    # ----- ServiceRoutes -----
    def create_service_route(self, payload, headers):
        return self._request("POST", "/api/service-routes", payload, headers)

    def get_service_route(self, route_id, headers):
        return self._request("GET", f"/api/service-routes/{route_id}", headers=headers)

    def list_service_routes(self, headers, params=None):
        return self._request("GET", "/api/service-routes", headers=headers, params=params)

    def get_route_visits(self, route_id, headers):
        return self._request("GET", f"/api/service-routes/{route_id}/visits", headers=headers)

    def publish_service_route(self, route_id, headers):
        return self._request("POST", f"/api/service-routes/{route_id}/publish", {}, headers)

    def unpublish_service_route(self, route_id, headers):
        return self._request("POST", f"/api/service-routes/{route_id}/unpublish", {}, headers)

    def start_service_route(self, route_id, headers):
        return self._request("POST", f"/api/service-routes/{route_id}/start", {}, headers)

    def close_service_route(self, route_id, headers):
        return self._request("POST", f"/api/service-routes/{route_id}/close", {}, headers)

    # ----- Visits -----
    def create_visit(self, payload, headers):
        return self._request("POST", "/api/visits", payload, headers)

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"/api/visits/{visit_id}", headers=headers)

    def list_visits(self, headers, params=None):
        return self._request("GET", "/api/visits", headers=headers, params=params)

    def assign_route_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/api/visits/{visit_id}/assign-route", payload, headers)

    def depart_visit(self, visit_id, headers):
        return self._request("POST", f"/api/visits/{visit_id}/depart", {}, headers)

    def ack_safety_visit(self, visit_id, headers):
        return self._request("POST", f"/api/visits/{visit_id}/ack-safety", {}, headers)

    def arrive_visit(self, visit_id, headers):
        return self._request("POST", f"/api/visits/{visit_id}/arrive", {}, headers)

    def complete_visit(self, visit_id, headers):
        return self._request("POST", f"/api/visits/{visit_id}/complete", {}, headers)

    def skip_visit(self, visit_id, headers):
        return self._request("POST", f"/api/visits/{visit_id}/skip", {}, headers)

    def cancel_visit(self, visit_id, headers):
        return self._request("POST", f"/api/visits/{visit_id}/cancel", {}, headers)

    # ----- VacationWindows -----
    def create_vacation_window(self, payload, headers):
        return self._request("POST", "/api/vacation-windows", payload, headers)

    def get_vacation_window(self, window_id, headers):
        return self._request("GET", f"/api/vacation-windows/{window_id}", headers=headers)

    def list_subscription_vacation_windows(self, subscription_id, headers):
        return self._request(
            "GET", f"/api/subscriptions/{subscription_id}/vacation-windows", headers=headers
        )

    def cancel_vacation_window(self, window_id, headers):
        return self._request("POST", f"/api/vacation-windows/{window_id}/cancel", {}, headers)

    # ----- Invoices -----
    def create_invoice(self, payload, headers):
        return self._request("POST", "/api/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/api/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/api/invoices", headers=headers, params=params)

    def get_invoice_line_items(self, invoice_id, headers):
        return self._request("GET", f"/api/invoices/{invoice_id}/line-items", headers=headers)

    def list_invoice_line_items(self, headers, params=None):
        return self._request("GET", "/api/invoice-line-items", headers=headers, params=params)

    def get_invoice_line_item(self, line_item_id, headers):
        return self._request("GET", f"/api/invoice-line-items/{line_item_id}", headers=headers)

    def finalize_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/api/invoices/{invoice_id}/finalize", payload, headers)

    def record_payment_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/api/invoices/{invoice_id}/record-payment", payload, headers)

    def dispute_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/api/invoices/{invoice_id}/dispute", payload, headers)

    def resolve_dispute_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/api/invoices/{invoice_id}/resolve-dispute", payload, headers)

    # ----- SatisfactionReports -----
    def create_satisfaction_report(self, payload, headers):
        return self._request("POST", "/api/satisfaction-reports", payload, headers)

    def get_satisfaction_report(self, report_id, headers):
        return self._request("GET", f"/api/satisfaction-reports/{report_id}", headers=headers)

    def list_satisfaction_reports(self, headers, params=None):
        return self._request("GET", "/api/satisfaction-reports", headers=headers, params=params)

    def begin_review_satisfaction_report(self, report_id, headers):
        return self._request(
            "POST", f"/api/satisfaction-reports/{report_id}/begin-review", {}, headers
        )

    def escalate_satisfaction_report(self, report_id, headers):
        return self._request(
            "POST", f"/api/satisfaction-reports/{report_id}/escalate", {}, headers
        )

    def resolve_satisfaction_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/api/satisfaction-reports/{report_id}/resolve", payload, headers
        )

    # ----- Test-driving -----
    def set_current_utc(self, to_iso8601, headers):
        return self._request(
            "POST", "/api/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def run_vacation_window_applier(self, headers):
        return self._request("POST", "/api/_system/vacation-window-applier/run", {}, headers)

    def run_end_of_day_sweep(self, headers):
        return self._request("POST", "/api/_system/end-of-day-sweep/run", {}, headers)


api_client = ApiClient()
