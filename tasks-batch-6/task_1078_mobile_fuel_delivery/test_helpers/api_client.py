"""API client: one method per endpoint defined in the Mobile Fuel Delivery PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Customers ───────────────────────────────────────────────
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # ─── Memberships ─────────────────────────────────────────────
    def create_membership(self, payload, headers):
        return self._request("POST", "/memberships", payload, headers=headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", "/memberships", headers=headers, params=params)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/memberships/{membership_id}", headers=headers)

    def pause_membership(self, membership_id, headers):
        return self._request("POST", f"/memberships/{membership_id}/pause", {}, headers=headers)

    def resume_membership(self, membership_id, headers):
        return self._request("POST", f"/memberships/{membership_id}/resume", {}, headers=headers)

    def cancel_membership(self, membership_id, headers):
        return self._request("POST", f"/memberships/{membership_id}/cancel", {}, headers=headers)

    def renew_charge_membership(self, membership_id, payload, headers):
        return self._request("POST", f"/memberships/{membership_id}/renew-charge", payload, headers=headers)

    # ─── Fleet Accounts ──────────────────────────────────────────
    def create_fleet_account(self, payload, headers):
        return self._request("POST", "/fleet-accounts", payload, headers=headers)

    def list_fleet_accounts(self, headers, params=None):
        return self._request("GET", "/fleet-accounts", headers=headers, params=params)

    def get_fleet_account(self, fleet_account_id, headers):
        return self._request("GET", f"/fleet-accounts/{fleet_account_id}", headers=headers)

    def update_fleet_account(self, fleet_account_id, payload, headers):
        return self._request("PATCH", f"/fleet-accounts/{fleet_account_id}", payload, headers=headers)

    def suspend_fleet_account(self, fleet_account_id, headers):
        return self._request("POST", f"/fleet-accounts/{fleet_account_id}/suspend", {}, headers=headers)

    def reactivate_fleet_account(self, fleet_account_id, headers):
        return self._request("POST", f"/fleet-accounts/{fleet_account_id}/reactivate", {}, headers=headers)

    def close_fleet_account(self, fleet_account_id, headers):
        return self._request("POST", f"/fleet-accounts/{fleet_account_id}/close", {}, headers=headers)

    # ─── Vehicles ────────────────────────────────────────────────
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/vehicles", payload, headers=headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/vehicles", headers=headers, params=params)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/vehicles/{vehicle_id}", headers=headers)

    def suspend_vehicle(self, vehicle_id, headers):
        return self._request("POST", f"/vehicles/{vehicle_id}/suspend", {}, headers=headers)

    def reactivate_vehicle(self, vehicle_id, headers):
        return self._request("POST", f"/vehicles/{vehicle_id}/reactivate", {}, headers=headers)

    # ─── Trucks & Compartments ───────────────────────────────────
    def create_truck(self, payload, headers):
        return self._request("POST", "/trucks", payload, headers=headers)

    def list_trucks(self, headers, params=None):
        return self._request("GET", "/trucks", headers=headers, params=params)

    def get_truck(self, truck_id, headers):
        return self._request("GET", f"/trucks/{truck_id}", headers=headers)

    def set_truck_maintenance(self, truck_id, payload, headers):
        return self._request("POST", f"/trucks/{truck_id}/maintenance", payload, headers=headers)

    def create_compartment(self, truck_id, payload, headers):
        return self._request("POST", f"/trucks/{truck_id}/compartments", payload, headers=headers)

    def list_compartments(self, truck_id, headers, params=None):
        return self._request("GET", f"/trucks/{truck_id}/compartments", headers=headers, params=params)

    def restock_truck(self, truck_id, payload, headers):
        return self._request("POST", f"/trucks/{truck_id}/restock", payload, headers=headers)

    # ─── Routes ──────────────────────────────────────────────────
    def create_route(self, payload, headers):
        return self._request("POST", "/routes", payload, headers=headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/routes", headers=headers, params=params)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/routes/{route_id}", headers=headers)

    def dispatch_route(self, route_id, headers):
        return self._request("POST", f"/routes/{route_id}/dispatch", {}, headers=headers)

    def complete_route(self, route_id, headers):
        return self._request("POST", f"/routes/{route_id}/complete", {}, headers=headers)

    def cancel_route(self, route_id, headers):
        return self._request("POST", f"/routes/{route_id}/cancel", {}, headers=headers)

    # ─── Orders ──────────────────────────────────────────────────
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def assign_route(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/assign-route", payload, headers=headers)

    def arrive_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/arrive", {}, headers=headers)

    def deliver_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/deliver", payload, headers=headers)

    def report_unable_access(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/report-unable-access", {}, headers=headers)

    def reschedule_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/reschedule", payload, headers=headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", {}, headers=headers)

    def add_addon(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/addons", payload, headers=headers)

    def list_addons(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/addons", headers=headers, params=params)

    # ─── Fuel Prices ─────────────────────────────────────────────
    def create_fuel_price(self, payload, headers):
        return self._request("POST", "/fuel-prices", payload, headers=headers)

    def list_fuel_prices(self, headers, params=None):
        return self._request("GET", "/fuel-prices", headers=headers, params=params)

    # ─── Logical clock ───────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers=headers)


api_client = ApiClient()
