"""API client: one method per endpoint defined in the PRD (§4 index)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Zones ---
    def create_zone(self, payload, headers):
        return self._request("POST", "/v1/zones", payload, headers)

    def get_zone(self, zone_id, headers):
        return self._request("GET", f"/v1/zones/{zone_id}", headers=headers)

    # --- Customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/v1/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/v1/customers/{customer_id}", headers=headers)

    def list_customer_bikes(self, customer_id, headers, params=None):
        return self._request("GET", f"/v1/customers/{customer_id}/bikes", headers=headers, params=params)

    def create_credit_adjustment(self, customer_id, payload, headers):
        return self._request("POST", f"/v1/customers/{customer_id}/credit-adjustments", payload, headers)

    # --- Bikes ---
    def create_bike(self, payload, headers):
        return self._request("POST", "/v1/bikes", payload, headers)

    def get_bike(self, bike_id, headers):
        return self._request("GET", f"/v1/bikes/{bike_id}", headers=headers)

    # --- Mechanics ---
    def create_mechanic(self, payload, headers):
        return self._request("POST", "/v1/mechanics", payload, headers)

    def get_mechanic(self, mechanic_id, headers):
        return self._request("GET", f"/v1/mechanics/{mechanic_id}", headers=headers)

    def list_mechanics(self, headers, params=None):
        return self._request("GET", "/v1/mechanics", headers=headers, params=params)

    def mechanic_event(self, mechanic_id, payload, headers):
        return self._request("POST", f"/v1/mechanics/{mechanic_id}/events", payload, headers)

    # --- Vans ---
    def create_van(self, payload, headers):
        return self._request("POST", "/v1/vans", payload, headers)

    def get_van(self, van_id, headers):
        return self._request("GET", f"/v1/vans/{van_id}", headers=headers)

    def list_vans(self, headers, params=None):
        return self._request("GET", "/v1/vans", headers=headers, params=params)

    def van_event(self, van_id, payload, headers):
        return self._request("POST", f"/v1/vans/{van_id}/events", payload, headers)

    # --- Parts & truck stock ---
    def create_part(self, payload, headers):
        return self._request("POST", "/v1/parts", payload, headers)

    def get_part(self, part_id, headers):
        return self._request("GET", f"/v1/parts/{part_id}", headers=headers)

    def list_part_stock(self, part_id, headers):
        return self._request("GET", f"/v1/parts/{part_id}/stock", headers=headers)

    def create_stock_movement(self, van_id, payload, headers):
        return self._request("POST", f"/v1/vans/{van_id}/stock-movements", payload, headers)

    def get_stock_movement(self, movement_id, headers):
        return self._request("GET", f"/v1/stock-movements/{movement_id}", headers=headers)

    def list_stock_movements(self, headers, params=None):
        return self._request("GET", "/v1/stock-movements", headers=headers, params=params)

    def list_van_stock(self, van_id, headers):
        return self._request("GET", f"/v1/vans/{van_id}/stock", headers=headers)

    # --- Service tiers ---
    def create_service_tier(self, payload, headers):
        return self._request("POST", "/v1/service-tiers", payload, headers)

    def get_service_tier(self, tier_id, headers):
        return self._request("GET", f"/v1/service-tiers/{tier_id}", headers=headers)

    # --- Subscriptions ---
    def create_subscription(self, payload, headers):
        return self._request("POST", "/v1/subscriptions", payload, headers)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/v1/subscriptions/{subscription_id}", headers=headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/v1/subscriptions", headers=headers, params=params)

    def subscription_event(self, subscription_id, payload, headers):
        return self._request("POST", f"/v1/subscriptions/{subscription_id}/events", payload, headers)

    # --- Service requests ---
    def create_service_request(self, payload, headers):
        return self._request("POST", "/v1/service-requests", payload, headers)

    def get_service_request(self, request_id, headers):
        return self._request("GET", f"/v1/service-requests/{request_id}", headers=headers)

    def list_service_requests(self, headers, params=None):
        return self._request("GET", "/v1/service-requests", headers=headers, params=params)

    def service_request_event(self, request_id, payload, headers):
        return self._request("POST", f"/v1/service-requests/{request_id}/events", payload, headers)

    def reschedule_service_request(self, request_id, payload, headers):
        return self._request("POST", f"/v1/service-requests/{request_id}/reschedule", payload, headers)

    def create_callback(self, request_id, payload, headers):
        return self._request("POST", f"/v1/service-requests/{request_id}/callbacks", payload, headers)

    def create_part_usage(self, request_id, payload, headers):
        return self._request("POST", f"/v1/service-requests/{request_id}/part-usages", payload, headers)

    # --- Route days & stops ---
    def create_route_day(self, payload, headers):
        return self._request("POST", "/v1/route-days", payload, headers)

    def get_route_day(self, route_day_id, headers):
        return self._request("GET", f"/v1/route-days/{route_day_id}", headers=headers)

    def list_route_days(self, headers, params=None):
        return self._request("GET", "/v1/route-days", headers=headers, params=params)

    def route_day_event(self, route_day_id, payload, headers):
        return self._request("POST", f"/v1/route-days/{route_day_id}/events", payload, headers)

    def create_route_stop(self, route_day_id, payload, headers):
        return self._request("POST", f"/v1/route-days/{route_day_id}/stops", payload, headers)

    def list_route_day_stops(self, route_day_id, headers):
        return self._request("GET", f"/v1/route-days/{route_day_id}/stops", headers=headers)

    def resequence_route_day(self, route_day_id, payload, headers):
        return self._request("POST", f"/v1/route-days/{route_day_id}/resequence", payload, headers)

    def get_route_stop(self, stop_id, headers):
        return self._request("GET", f"/v1/route-stops/{stop_id}", headers=headers)

    def list_route_stops(self, headers, params=None):
        return self._request("GET", "/v1/route-stops", headers=headers, params=params)

    def route_stop_event(self, stop_id, payload, headers):
        return self._request("POST", f"/v1/route-stops/{stop_id}/events", payload, headers)

    # --- Invoices ---
    def create_invoice(self, request_id, headers):
        return self._request("POST", f"/v1/service-requests/{request_id}/invoices", {}, headers)

    def list_request_invoices(self, request_id, headers):
        return self._request("GET", f"/v1/service-requests/{request_id}/invoices", headers=headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/v1/invoices/{invoice_id}", headers=headers)

    def invoice_event(self, invoice_id, payload, headers):
        return self._request("POST", f"/v1/invoices/{invoice_id}/events", payload, headers)

    # --- Test-driving clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/v1/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
