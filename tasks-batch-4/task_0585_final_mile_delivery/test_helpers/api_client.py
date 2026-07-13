"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Depot ---
    def create_depot(self, payload, headers):
        return self._request("POST", "/depots", payload, headers)

    def list_depots(self, headers, params=None):
        return self._request("GET", "/depots", headers=headers, params=params)

    # --- Dock ---
    def create_dock(self, payload, headers):
        return self._request("POST", "/docks", payload, headers)

    def list_docks(self, headers, params=None):
        return self._request("GET", "/docks", headers=headers, params=params)

    def get_dock(self, dock_id, headers):
        return self._request("GET", f"/docks/{dock_id}", headers=headers)

    def close_dock(self, dock_id, headers):
        return self._request("POST", f"/docks/{dock_id}/close", {}, headers)

    # --- DeliveryTeam ---
    def create_team(self, payload, headers):
        return self._request("POST", "/delivery-teams", payload, headers)

    def list_teams(self, headers, params=None):
        return self._request("GET", "/delivery-teams", headers=headers, params=params)

    def get_team(self, team_id, headers):
        return self._request("GET", f"/delivery-teams/{team_id}", headers=headers)

    # --- Customer ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # --- DeliveryOrder ---
    def create_order(self, payload, headers):
        return self._request("POST", "/delivery-orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/delivery-orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/delivery-orders/{order_id}", headers=headers)

    def reserve_window(self, order_id, payload, headers):
        return self._request("POST", f"/delivery-orders/{order_id}/windows", payload, headers)

    def list_order_attempts(self, order_id, headers, params=None):
        return self._request("GET", f"/delivery-orders/{order_id}/attempts", headers=headers, params=params)

    def record_attempt(self, order_id, payload, headers):
        return self._request("POST", f"/delivery-orders/{order_id}/attempts", payload, headers)

    def settle_order(self, order_id, headers):
        return self._request("POST", f"/delivery-orders/{order_id}/settle", {}, headers)

    def void_delivery(self, order_id, headers):
        return self._request("POST", f"/delivery-orders/{order_id}/void-delivery", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/delivery-orders/{order_id}/cancel", {}, headers)

    # --- DeliveryWindow ---
    def list_windows(self, headers, params=None):
        return self._request("GET", "/delivery-windows", headers=headers, params=params)

    def get_window(self, window_id, headers):
        return self._request("GET", f"/delivery-windows/{window_id}", headers=headers)

    def confirm_window(self, window_id, headers):
        return self._request("POST", f"/delivery-windows/{window_id}/confirm", {}, headers)

    # --- Route ---
    def create_route(self, payload, headers):
        return self._request("POST", "/routes", payload, headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/routes", headers=headers, params=params)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/routes/{route_id}", headers=headers)

    def add_stop(self, route_id, payload, headers):
        return self._request("POST", f"/routes/{route_id}/stops", payload, headers)

    def list_route_stops(self, route_id, headers, params=None):
        return self._request("GET", f"/routes/{route_id}/stops", headers=headers, params=params)

    def remove_stop(self, route_id, stop_id, headers):
        return self._request("POST", f"/routes/{route_id}/stops/{stop_id}/remove", {}, headers)

    def dispatch_route(self, route_id, headers):
        return self._request("POST", f"/routes/{route_id}/dispatch", {}, headers)

    def close_route(self, route_id, headers):
        return self._request("POST", f"/routes/{route_id}/close", {}, headers)

    # --- RouteStop reads ---
    def get_route_stop(self, stop_id, headers):
        return self._request("GET", f"/route-stops/{stop_id}", headers=headers)

    def list_stops(self, headers, params=None):
        return self._request("GET", "/route-stops", headers=headers, params=params)

    # --- DockAppointment ---
    def book_dock_appointment(self, route_id, payload, headers):
        return self._request("POST", f"/routes/{route_id}/dock-appointments", payload, headers)

    def get_dock_appointment(self, appt_id, headers):
        return self._request("GET", f"/dock-appointments/{appt_id}", headers=headers)

    def list_dock_appointments(self, headers, params=None):
        return self._request("GET", "/dock-appointments", headers=headers, params=params)

    # --- DeliveryAttempt reads ---
    def get_delivery_attempt(self, attempt_id, headers):
        return self._request("GET", f"/delivery-attempts/{attempt_id}", headers=headers)

    def list_delivery_attempts(self, headers, params=None):
        return self._request("GET", "/delivery-attempts", headers=headers, params=params)


api_client = ApiClient()
