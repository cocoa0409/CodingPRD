"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Service plans ----
    def create_service_plan(self, payload, headers):
        return self._request("POST", "/service-plans", payload, headers)

    def get_service_plan(self, plan_id, headers):
        return self._request("GET", f"/service-plans/{plan_id}", headers=headers)

    # ---- Account holders ----
    def create_account_holder(self, payload, headers):
        return self._request("POST", "/account-holders", payload, headers)

    def get_account_holder(self, ah_id, headers):
        return self._request("GET", f"/account-holders/{ah_id}", headers=headers)

    def list_account_holder_properties(self, ah_id, headers, params=None):
        return self._request("GET", f"/account-holders/{ah_id}/properties", headers=headers, params=params)

    # ---- Crews ----
    def create_crew(self, payload, headers):
        return self._request("POST", "/crews", payload, headers)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/crews/{crew_id}", headers=headers)

    def list_crew_routes_for_crew(self, crew_id, headers, params=None):
        return self._request("GET", f"/crews/{crew_id}/crew-routes", headers=headers, params=params)

    # ---- Properties + zones ----
    def create_property(self, payload, headers):
        return self._request("POST", "/properties", payload, headers)

    def get_property(self, prop_id, headers):
        return self._request("GET", f"/properties/{prop_id}", headers=headers)

    def add_zone(self, prop_id, payload, headers):
        return self._request("POST", f"/properties/{prop_id}/zones", payload, headers)

    def list_zones(self, prop_id, headers, params=None):
        return self._request("GET", f"/properties/{prop_id}/zones", headers=headers, params=params)

    def exclude_zone(self, zone_id, headers):
        return self._request("POST", f"/zones/{zone_id}/exclude", {}, headers)

    # ---- Subscriptions ----
    def create_subscription(self, payload, headers):
        return self._request("POST", "/subscriptions", payload, headers)

    def get_subscription(self, sub_id, headers):
        return self._request("GET", f"/subscriptions/{sub_id}", headers=headers)

    def list_property_subscriptions(self, prop_id, headers, params=None):
        return self._request("GET", f"/properties/{prop_id}/subscriptions", headers=headers, params=params)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/subscriptions", headers=headers, params=params)

    def activate_subscription(self, sub_id, headers):
        return self._request("POST", f"/subscriptions/{sub_id}/activate", {}, headers)

    def close_season(self, sub_id, headers):
        return self._request("POST", f"/subscriptions/{sub_id}/close-season", {}, headers)

    def confirm_renewal(self, sub_id, headers):
        return self._request("POST", f"/subscriptions/{sub_id}/confirm-renewal", {}, headers)

    def cancel_subscription(self, sub_id, headers):
        return self._request("POST", f"/subscriptions/{sub_id}/cancel", {}, headers)

    def schedule_special_event(self, sub_id, payload, headers):
        return self._request("POST", f"/subscriptions/{sub_id}/special-event", payload, headers)

    def list_subscription_visits(self, sub_id, headers, params=None):
        return self._request("GET", f"/subscriptions/{sub_id}/visits", headers=headers, params=params)

    def list_subscription_invoices(self, sub_id, headers, params=None):
        return self._request("GET", f"/subscriptions/{sub_id}/invoices", headers=headers, params=params)

    # ---- Visits ----
    def get_visit(self, visit_id, headers):
        return self._request("GET", f"/visits/{visit_id}", headers=headers)

    def list_visits(self, headers, params=None):
        return self._request("GET", "/visits", headers=headers, params=params)

    def weather_hold(self, visit_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/weather-hold", payload, headers)

    def reschedule_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/reschedule", payload, headers)

    def cancel_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/cancel", {}, headers)

    def add_application_log(self, visit_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/application-logs", payload, headers)

    def list_application_logs(self, visit_id, headers, params=None):
        return self._request("GET", f"/visits/{visit_id}/application-logs", headers=headers, params=params)

    def get_application_log(self, log_id, headers):
        return self._request("GET", f"/application-logs/{log_id}", headers=headers)

    def list_all_application_logs(self, headers, params=None):
        return self._request("GET", "/application-logs", headers=headers, params=params)

    def complete_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/complete", {}, headers)

    def request_retreat(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/request-retreat", {}, headers)

    def schedule_retreat(self, visit_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/schedule-retreat", payload, headers)

    def close_retreat(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/close-retreat", {}, headers)

    # ---- Routes / dispatch ----
    def create_crew_route(self, payload, headers):
        return self._request("POST", "/crew-routes", payload, headers)

    def get_crew_route(self, route_id, headers):
        return self._request("GET", f"/crew-routes/{route_id}", headers=headers)

    def get_crew_route_summary(self, route_id, headers):
        return self._request("GET", f"/crew-routes/{route_id}/summary", headers=headers)

    def dispatch_visit(self, route_id, payload, headers):
        return self._request("POST", f"/crew-routes/{route_id}/dispatch-visit", payload, headers)

    def lock_route(self, route_id, headers):
        return self._request("POST", f"/crew-routes/{route_id}/lock", {}, headers)

    def close_route(self, route_id, headers):
        return self._request("POST", f"/crew-routes/{route_id}/close", {}, headers)

    # ---- Weather feed ----
    def create_weather_event(self, payload, headers):
        return self._request("POST", "/weather-events", payload, headers)

    def get_weather_event(self, we_id, headers):
        return self._request("GET", f"/weather-events/{we_id}", headers=headers)

    # ---- Invoices ----
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def pay_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/pay", payload, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/void", {}, headers)

    # ---- Logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
