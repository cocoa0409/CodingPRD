"""API client: one method per endpoint defined in the PRD (§4 endpoint table).

All paths are mounted under the /coffee-cart prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/coffee-cart"


class ApiClient(GenericApiClient):
    # ─── Clients ──────────────────────────────────────────────────────────
    def create_client(self, payload, headers):
        return self._request("POST", f"{PREFIX}/clients", payload, headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/clients", headers=headers, params=params)

    def get_client(self, client_id, headers):
        return self._request("GET", f"{PREFIX}/clients/{client_id}", headers=headers)

    # ─── Coffee carts ─────────────────────────────────────────────────────
    def create_cart(self, payload, headers):
        return self._request("POST", f"{PREFIX}/carts", payload, headers)

    def list_carts(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/carts", headers=headers, params=params)

    def get_cart(self, cart_id, headers):
        return self._request("GET", f"{PREFIX}/carts/{cart_id}", headers=headers)

    # ─── Baristas ─────────────────────────────────────────────────────────
    def create_barista(self, payload, headers):
        return self._request("POST", f"{PREFIX}/baristas", payload, headers)

    def list_baristas(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/baristas", headers=headers, params=params)

    def get_barista(self, barista_id, headers):
        return self._request("GET", f"{PREFIX}/baristas/{barista_id}", headers=headers)

    def list_barista_assignments(self, barista_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/baristas/{barista_id}/assignments",
                             headers=headers, params=params)

    # ─── Packages ─────────────────────────────────────────────────────────
    def create_package(self, payload, headers):
        return self._request("POST", f"{PREFIX}/packages", payload, headers)

    def list_packages(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/packages", headers=headers, params=params)

    def get_package(self, package_id, headers):
        return self._request("GET", f"{PREFIX}/packages/{package_id}", headers=headers)

    # ─── Add-ons ──────────────────────────────────────────────────────────
    def create_addon(self, payload, headers):
        return self._request("POST", f"{PREFIX}/addons", payload, headers)

    def list_addons(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/addons", headers=headers, params=params)

    def get_addon(self, addon_id, headers):
        return self._request("GET", f"{PREFIX}/addons/{addon_id}", headers=headers)

    def list_addon_booking_addons(self, addon_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/addons/{addon_id}/booking-addons",
                             headers=headers, params=params)

    # ─── Travel zones ─────────────────────────────────────────────────────
    def create_travel_zone(self, payload, headers):
        return self._request("POST", f"{PREFIX}/travel-zones", payload, headers)

    def list_travel_zones(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/travel-zones", headers=headers, params=params)

    def get_travel_zone(self, zone_id, headers):
        return self._request("GET", f"{PREFIX}/travel-zones/{zone_id}", headers=headers)

    # ─── Inventory items ──────────────────────────────────────────────────
    def create_inventory_item(self, payload, headers):
        return self._request("POST", f"{PREFIX}/inventory-items", payload, headers)

    def list_inventory_items(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/inventory-items", headers=headers, params=params)

    def get_inventory_item(self, item_id, headers):
        return self._request("GET", f"{PREFIX}/inventory-items/{item_id}", headers=headers)

    def list_item_reservations(self, item_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/inventory-items/{item_id}/reservations",
                             headers=headers, params=params)

    # ─── Cancellation policy tiers ────────────────────────────────────────
    def create_cancellation_tier(self, payload, headers):
        return self._request("POST", f"{PREFIX}/cancellation-tiers", payload, headers)

    def list_cancellation_tiers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/cancellation-tiers", headers=headers, params=params)

    # ─── Bookings ─────────────────────────────────────────────────────────
    def create_booking(self, payload, headers):
        return self._request("POST", f"{PREFIX}/bookings", payload, headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/bookings", headers=headers, params=params)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"{PREFIX}/bookings/{booking_id}", headers=headers)

    def attach_addon(self, booking_id, payload, headers):
        return self._request("POST", f"{PREFIX}/bookings/{booking_id}/addons", payload, headers)

    def list_booking_addons(self, booking_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/bookings/{booking_id}/addons",
                             headers=headers, params=params)

    def offer_assignment(self, booking_id, payload, headers):
        return self._request("POST", f"{PREFIX}/bookings/{booking_id}/assignments",
                             payload, headers)

    def list_booking_assignments(self, booking_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/bookings/{booking_id}/assignments",
                             headers=headers, params=params)

    def create_reservation(self, booking_id, payload, headers):
        return self._request("POST", f"{PREFIX}/bookings/{booking_id}/reservations",
                             payload, headers)

    def list_booking_reservations(self, booking_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/bookings/{booking_id}/reservations",
                             headers=headers, params=params)

    # ─── Booking lifecycle actions ────────────────────────────────────────
    def submit_booking(self, booking_id, payload, headers):
        return self._request("POST", f"{PREFIX}/bookings/{booking_id}/submit",
                             payload, headers)

    def reopen_booking(self, booking_id, headers):
        return self._request("POST", f"{PREFIX}/bookings/{booking_id}/reopen", {}, headers)

    def amend_booking(self, booking_id, payload, headers):
        return self._request("POST", f"{PREFIX}/bookings/{booking_id}/amend", payload, headers)

    def cancel_booking(self, booking_id, payload, headers):
        return self._request("POST", f"{PREFIX}/bookings/{booking_id}/cancel",
                             payload, headers)

    def complete_booking(self, booking_id, headers):
        return self._request("POST", f"{PREFIX}/bookings/{booking_id}/complete", {}, headers)

    # ─── Assignment actions ───────────────────────────────────────────────
    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"{PREFIX}/assignments/{assignment_id}", headers=headers)

    def accept_assignment(self, assignment_id, headers):
        return self._request("POST", f"{PREFIX}/assignments/{assignment_id}/accept",
                             {}, headers)

    def decline_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"{PREFIX}/assignments/{assignment_id}/decline",
                             payload, headers)

    def withdraw_assignment(self, assignment_id, headers):
        return self._request("POST", f"{PREFIX}/assignments/{assignment_id}/withdraw",
                             {}, headers)

    def resolve_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"{PREFIX}/assignments/{assignment_id}/resolve",
                             payload, headers)

    # ─── Reservation actions ──────────────────────────────────────────────
    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"{PREFIX}/reservations/{reservation_id}", headers=headers)

    def record_consumption(self, reservation_id, payload, headers):
        return self._request("POST",
                             f"{PREFIX}/reservations/{reservation_id}/record-consumption",
                             payload, headers)

    def reconcile_reservation(self, reservation_id, headers):
        return self._request("POST", f"{PREFIX}/reservations/{reservation_id}/reconcile",
                             {}, headers)

    # ─── Payments ─────────────────────────────────────────────────────────
    def create_payment(self, booking_id, payload, headers):
        return self._request("POST", f"{PREFIX}/bookings/{booking_id}/payments",
                             payload, headers)

    def list_booking_payments(self, booking_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/bookings/{booking_id}/payments",
                             headers=headers, params=params)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"{PREFIX}/payments/{payment_id}", headers=headers)

    def mark_payment_succeeded(self, payment_id, headers):
        return self._request("POST", f"{PREFIX}/payments/{payment_id}/mark-succeeded",
                             {}, headers)

    def mark_payment_failed(self, payment_id, headers):
        return self._request("POST", f"{PREFIX}/payments/{payment_id}/mark-failed",
                             {}, headers)

    # ─── Logical clock (test-driving) ─────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
