"""API client: one method per endpoint defined in the Catering Event Management PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clients ----
    def create_client(self, payload, headers):
        return self._request("POST", "/catering/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/catering/clients/{client_id}", headers=headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/catering/clients", headers=headers, params=params)

    # ---- Packages ----
    def create_package(self, payload, headers):
        return self._request("POST", "/catering/packages", payload, headers)

    def get_package(self, package_id, headers):
        return self._request("GET", f"/catering/packages/{package_id}", headers=headers)

    def list_packages(self, headers, params=None):
        return self._request("GET", "/catering/packages", headers=headers, params=params)

    def retire_package(self, package_id, payload, headers):
        return self._request("POST", f"/catering/packages/{package_id}/retire", payload, headers)

    # ---- Venues ----
    def create_venue(self, payload, headers):
        return self._request("POST", "/catering/venues", payload, headers)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/catering/venues/{venue_id}", headers=headers)

    # ---- Service Routes ----
    def create_route(self, payload, headers):
        return self._request("POST", "/catering/routes", payload, headers)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/catering/routes/{route_id}", headers=headers)

    def list_route_delivery_legs(self, route_id, headers, params=None):
        return self._request("GET", f"/catering/routes/{route_id}/delivery-legs", headers=headers, params=params)

    # ---- Orders ----
    def create_order(self, payload, headers):
        return self._request("POST", "/catering/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/catering/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/catering/orders", headers=headers, params=params)

    def patch_order(self, order_id, payload, headers):
        return self._request("PATCH", f"/catering/orders/{order_id}", payload, headers)

    def confirm_order(self, order_id, payload, headers):
        return self._request("POST", f"/catering/orders/{order_id}/confirm", payload, headers)

    def guarantee_order(self, order_id, payload, headers):
        return self._request("POST", f"/catering/orders/{order_id}/guarantee", payload, headers)

    def invoice_order(self, order_id, payload, headers):
        return self._request("POST", f"/catering/orders/{order_id}/invoice", payload, headers)

    def pay_order(self, order_id, payload, headers):
        return self._request("POST", f"/catering/orders/{order_id}/payments", payload, headers)

    def settle_order(self, order_id, payload, headers):
        return self._request("POST", f"/catering/orders/{order_id}/settle", payload, headers)

    def fulfill_order(self, order_id, payload, headers):
        return self._request("POST", f"/catering/orders/{order_id}/fulfill", payload, headers)

    def cancel_order(self, order_id, payload, headers):
        return self._request("POST", f"/catering/orders/{order_id}/cancel", payload, headers)

    # ---- Order sub-resources (reverse-reachability) ----
    def list_order_add_ons(self, order_id, headers, params=None):
        return self._request("GET", f"/catering/orders/{order_id}/add-ons", headers=headers, params=params)

    def list_order_delivery_legs(self, order_id, headers, params=None):
        return self._request("GET", f"/catering/orders/{order_id}/delivery-legs", headers=headers, params=params)

    def list_order_change_requests(self, order_id, headers, params=None):
        return self._request("GET", f"/catering/orders/{order_id}/change-requests", headers=headers, params=params)

    def list_order_ledger(self, order_id, headers, params=None):
        return self._request("GET", f"/catering/orders/{order_id}/ledger", headers=headers, params=params)

    def list_order_staffing_reservation(self, order_id, headers, params=None):
        return self._request("GET", f"/catering/orders/{order_id}/staffing-reservation", headers=headers, params=params)

    # ---- Add-on lines ----
    def create_add_on(self, order_id, payload, headers):
        return self._request("POST", f"/catering/orders/{order_id}/add-ons", payload, headers)

    def get_add_on(self, add_on_id, headers):
        return self._request("GET", f"/catering/add-ons/{add_on_id}", headers=headers)

    # ---- Delivery legs ----
    def create_delivery_leg(self, payload, headers):
        return self._request("POST", "/catering/delivery-legs", payload, headers)

    def get_delivery_leg(self, leg_id, headers):
        return self._request("GET", f"/catering/delivery-legs/{leg_id}", headers=headers)

    def list_delivery_legs(self, headers, params=None):
        return self._request("GET", "/catering/delivery-legs", headers=headers, params=params)

    def dispatch_delivery_leg(self, leg_id, payload, headers):
        return self._request("POST", f"/catering/delivery-legs/{leg_id}/dispatch", payload, headers)

    def deliver_delivery_leg(self, leg_id, payload, headers):
        return self._request("POST", f"/catering/delivery-legs/{leg_id}/deliver", payload, headers)

    def fail_delivery_leg(self, leg_id, payload, headers):
        return self._request("POST", f"/catering/delivery-legs/{leg_id}/fail", payload, headers)

    # ---- Change requests ----
    def create_change_request(self, payload, headers):
        return self._request("POST", "/catering/change-requests", payload, headers)

    def get_change_request(self, cr_id, headers):
        return self._request("GET", f"/catering/change-requests/{cr_id}", headers=headers)

    def counter_change_request(self, cr_id, payload, headers):
        return self._request("POST", f"/catering/change-requests/{cr_id}/counter", payload, headers)

    def revise_change_request(self, cr_id, payload, headers):
        return self._request("POST", f"/catering/change-requests/{cr_id}/revise", payload, headers)

    def accept_change_request(self, cr_id, payload, headers):
        return self._request("POST", f"/catering/change-requests/{cr_id}/accept", payload, headers)

    def reject_change_request(self, cr_id, payload, headers):
        return self._request("POST", f"/catering/change-requests/{cr_id}/reject", payload, headers)

    # ---- Test-driving clock & staff pool ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/catering/_clock/set_current_utc", payload, headers)

    def set_staff_pool(self, payload, headers):
        return self._request("POST", "/catering/_staff-pool/set_capacity", payload, headers)


api_client = ApiClient()
