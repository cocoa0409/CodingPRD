"""API client: one method per endpoint defined in the Cruise Booking PRD.

Subclasses the framework GenericApiClient; the base _request() handles the
envelope, headers, and JSON serialization.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------- Clock ----------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---------- Sailing ----------
    def create_sailing(self, payload, headers):
        return self._request("POST", "/sailings", payload, headers)

    def get_sailing(self, sailing_id, headers):
        return self._request("GET", f"/sailings/{sailing_id}", headers=headers)

    def list_sailings(self, headers, params=None):
        return self._request("GET", "/sailings", headers=headers, params=params)

    def open_sailing(self, sailing_id, headers):
        return self._request("POST", f"/sailings/{sailing_id}/open", headers=headers)

    def close_sailing(self, sailing_id, headers):
        return self._request("POST", f"/sailings/{sailing_id}/close", headers=headers)

    def depart_sailing(self, sailing_id, headers):
        return self._request("POST", f"/sailings/{sailing_id}/depart", headers=headers)

    def cancel_sailing(self, sailing_id, headers):
        return self._request("POST", f"/sailings/{sailing_id}/cancel", headers=headers)

    # ---------- CabinCategory ----------
    def create_cabin_category(self, payload, headers):
        return self._request("POST", "/cabin-categories", payload, headers)

    def get_cabin_category(self, category_id, headers):
        return self._request("GET", f"/cabin-categories/{category_id}", headers=headers)

    def list_cabin_categories(self, headers, params=None):
        return self._request("GET", "/cabin-categories", headers=headers, params=params)

    # ---------- Cabin ----------
    def create_cabin(self, payload, headers):
        return self._request("POST", "/cabins", payload, headers)

    def get_cabin(self, cabin_id, headers):
        return self._request("GET", f"/cabins/{cabin_id}", headers=headers)

    def list_cabins(self, headers, params=None):
        return self._request("GET", "/cabins", headers=headers, params=params)

    # ---------- GroupBlock ----------
    def create_group_block(self, payload, headers):
        return self._request("POST", "/group-blocks", payload, headers)

    def get_group_block(self, block_id, headers):
        return self._request("GET", f"/group-blocks/{block_id}", headers=headers)

    def list_group_blocks(self, headers, params=None):
        return self._request("GET", "/group-blocks", headers=headers, params=params)

    def update_group_block(self, block_id, payload, headers):
        return self._request("PATCH", f"/group-blocks/{block_id}", payload, headers)

    def hold_group_block(self, block_id, headers):
        return self._request("POST", f"/group-blocks/{block_id}/hold", headers=headers)

    def recall_group_block(self, block_id, headers):
        return self._request("POST", f"/group-blocks/{block_id}/recall", headers=headers)

    def release_group_block(self, block_id, headers):
        return self._request("POST", f"/group-blocks/{block_id}/release", headers=headers)

    # ---------- Booking ----------
    def create_booking(self, payload, headers):
        return self._request("POST", "/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/bookings", headers=headers, params=params)

    def hold_deposit(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/hold-deposit", headers=headers)

    def revise_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/revise", headers=headers)

    def confirm_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/confirm", headers=headers)

    def embark_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/embark", headers=headers)

    def settle_folio(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/settle-folio", headers=headers)

    def cancel_booking(self, booking_id, cancellation_mode, headers):
        return self._request(
            "POST",
            f"/bookings/{booking_id}/cancel",
            {"cancellation_mode": cancellation_mode},
            headers,
        )

    # ---------- Guest ----------
    def create_guest(self, payload, headers):
        return self._request("POST", "/guests", payload, headers)

    def delete_guest(self, guest_id, headers):
        return self._request("DELETE", f"/guests/{guest_id}", headers=headers)

    def get_guest(self, guest_id, headers):
        return self._request("GET", f"/guests/{guest_id}", headers=headers)

    def list_guests(self, headers, params=None):
        return self._request("GET", "/guests", headers=headers, params=params)

    # ---------- AddOn ----------
    def create_add_on(self, payload, headers):
        return self._request("POST", "/add-ons", payload, headers)

    def get_add_on(self, add_on_id, headers):
        return self._request("GET", f"/add-ons/{add_on_id}", headers=headers)

    def list_add_ons(self, headers, params=None):
        return self._request("GET", "/add-ons", headers=headers, params=params)

    def cancel_add_on(self, add_on_id, headers):
        return self._request("POST", f"/add-ons/{add_on_id}/cancel", headers=headers)

    # ---------- DiningReservation ----------
    def create_dining_reservation(self, payload, headers):
        return self._request("POST", "/dining-reservations", payload, headers)

    def get_dining_reservation(self, reservation_id, headers):
        return self._request("GET", f"/dining-reservations/{reservation_id}", headers=headers)

    def list_dining_reservations(self, headers, params=None):
        return self._request("GET", "/dining-reservations", headers=headers, params=params)

    def cancel_dining_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/dining-reservations/{reservation_id}/cancel", headers=headers
        )

    # ---------- Payment ----------
    def create_payment(self, payload, headers):
        return self._request("POST", "/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    def capture_payment(self, payment_id, headers):
        return self._request("POST", f"/payments/{payment_id}/capture", headers=headers)

    def fail_payment(self, payment_id, headers):
        return self._request("POST", f"/payments/{payment_id}/fail", headers=headers)

    def refund_payment(self, payment_id, headers):
        return self._request("POST", f"/payments/{payment_id}/refund", headers=headers)

    # ---------- Folio ----------
    def get_folio(self, folio_id, headers):
        return self._request("GET", f"/folios/{folio_id}", headers=headers)

    def list_folios(self, headers, params=None):
        return self._request("GET", "/folios", headers=headers, params=params)

    def post_folio_charge(self, folio_id, payload, headers):
        return self._request("POST", f"/folios/{folio_id}/charges", payload, headers)

    # ---------- FolioCharge ----------
    def get_folio_charge(self, charge_id, headers):
        return self._request("GET", f"/folio-charges/{charge_id}", headers=headers)

    def list_folio_charges(self, headers, params=None):
        return self._request("GET", "/folio-charges", headers=headers, params=params)

    def reverse_folio_charge(self, charge_id, headers):
        return self._request("POST", f"/folio-charges/{charge_id}/reverse", headers=headers)


api_client = ApiClient()
