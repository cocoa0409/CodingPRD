"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers=headers
        )

    # --- Tables ---
    def create_table(self, payload, headers):
        return self._request("POST", "/tables", payload, headers=headers)

    def get_table(self, table_id, headers):
        return self._request("GET", f"/tables/{table_id}", headers=headers)

    def list_tables(self, headers, params=None):
        return self._request("GET", "/tables", headers=headers, params=params)

    def update_table(self, table_id, payload, headers):
        return self._request("PATCH", f"/tables/{table_id}", payload, headers=headers)

    # --- Memberships ---
    def create_membership(self, payload, headers):
        return self._request("POST", "/memberships", payload, headers=headers)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/memberships/{membership_id}", headers=headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", "/memberships", headers=headers, params=params)

    def update_membership(self, membership_id, payload, headers):
        return self._request("PATCH", f"/memberships/{membership_id}", payload, headers=headers)

    def loyalty_adjustment(self, membership_id, payload, headers):
        return self._request(
            "POST", f"/memberships/{membership_id}/loyalty-adjustments", payload, headers=headers
        )

    def redeem(self, membership_id, payload, headers):
        return self._request(
            "POST", f"/memberships/{membership_id}/redemptions", payload, headers=headers
        )

    def reverse_redemption(self, membership_id, redemption_id, headers):
        return self._request(
            "POST",
            f"/memberships/{membership_id}/redemptions/{redemption_id}/reverse",
            {},
            headers=headers,
        )

    # --- Reservations ---
    def create_reservation(self, payload, headers):
        return self._request("POST", "/reservations", payload, headers=headers)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/reservations/{reservation_id}", headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/reservations", headers=headers, params=params)

    def seat_reservation(self, reservation_id, headers, payload=None):
        return self._request(
            "POST", f"/reservations/{reservation_id}/seat", payload or {}, headers=headers
        )

    def close_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/reservations/{reservation_id}/close", {}, headers=headers
        )

    def cancel_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/reservations/{reservation_id}/cancel", {}, headers=headers
        )

    def no_show_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/reservations/{reservation_id}/no-show", {}, headers=headers
        )

    # --- F&B orders ---
    def create_fnb_order(self, payload, headers):
        return self._request("POST", "/fnb-orders", payload, headers=headers)

    def get_fnb_order(self, order_id, headers):
        return self._request("GET", f"/fnb-orders/{order_id}", headers=headers)

    def list_fnb_orders(self, headers, params=None):
        return self._request("GET", "/fnb-orders", headers=headers, params=params)

    def void_fnb_order(self, order_id, headers):
        return self._request("POST", f"/fnb-orders/{order_id}/void", {}, headers=headers)

    # --- Game copies ---
    def create_game_copy(self, payload, headers):
        return self._request("POST", "/game-copies", payload, headers=headers)

    def get_game_copy(self, game_copy_id, headers):
        return self._request("GET", f"/game-copies/{game_copy_id}", headers=headers)

    def list_game_copies(self, headers, params=None):
        return self._request("GET", "/game-copies", headers=headers, params=params)

    def update_game_copy(self, game_copy_id, payload, headers):
        return self._request("PATCH", f"/game-copies/{game_copy_id}", payload, headers=headers)

    # --- Checkouts ---
    def create_checkout(self, payload, headers):
        return self._request("POST", "/checkouts", payload, headers=headers)

    def get_checkout(self, checkout_id, headers):
        return self._request("GET", f"/checkouts/{checkout_id}", headers=headers)

    def list_checkouts(self, headers, params=None):
        return self._request("GET", "/checkouts", headers=headers, params=params)

    def return_checkout(self, checkout_id, payload, headers):
        return self._request(
            "POST", f"/checkouts/{checkout_id}/return", payload, headers=headers
        )

    def report_lost_checkout(self, checkout_id, headers):
        return self._request(
            "POST", f"/checkouts/{checkout_id}/report-lost", {}, headers=headers
        )

    # --- Tournaments ---
    def create_tournament(self, payload, headers):
        return self._request("POST", "/tournaments", payload, headers=headers)

    def get_tournament(self, tournament_id, headers):
        return self._request("GET", f"/tournaments/{tournament_id}", headers=headers)

    def list_tournaments(self, headers, params=None):
        return self._request("GET", "/tournaments", headers=headers, params=params)

    def open_tournament(self, tournament_id, headers):
        return self._request("POST", f"/tournaments/{tournament_id}/open", {}, headers=headers)

    def start_tournament(self, tournament_id, headers):
        return self._request("POST", f"/tournaments/{tournament_id}/start", {}, headers=headers)

    def cancel_tournament(self, tournament_id, headers):
        return self._request("POST", f"/tournaments/{tournament_id}/cancel", {}, headers=headers)

    # --- Registrations ---
    def create_registration(self, payload, headers):
        return self._request("POST", "/registrations", payload, headers=headers)

    def get_registration(self, registration_id, headers):
        return self._request("GET", f"/registrations/{registration_id}", headers=headers)

    def list_registrations(self, headers, params=None):
        return self._request("GET", "/registrations", headers=headers, params=params)

    def check_in_registration(self, registration_id, headers):
        return self._request(
            "POST", f"/registrations/{registration_id}/check-in", {}, headers=headers
        )

    def withdraw_registration(self, registration_id, headers):
        return self._request(
            "POST", f"/registrations/{registration_id}/withdraw", {}, headers=headers
        )

    # --- Rooms ---
    def create_room(self, payload, headers):
        return self._request("POST", "/rooms", payload, headers=headers)

    def get_room(self, room_id, headers):
        return self._request("GET", f"/rooms/{room_id}", headers=headers)

    def list_rooms(self, headers, params=None):
        return self._request("GET", "/rooms", headers=headers, params=params)

    def update_room(self, room_id, payload, headers):
        return self._request("PATCH", f"/rooms/{room_id}", payload, headers=headers)

    # --- Private bookings ---
    def create_private_booking(self, payload, headers):
        return self._request("POST", "/private-bookings", payload, headers=headers)

    def get_private_booking(self, booking_id, headers):
        return self._request("GET", f"/private-bookings/{booking_id}", headers=headers)

    def list_private_bookings(self, headers, params=None):
        return self._request("GET", "/private-bookings", headers=headers, params=params)

    def confirm_private_booking(self, booking_id, headers):
        return self._request(
            "POST", f"/private-bookings/{booking_id}/confirm", {}, headers=headers
        )

    def cancel_private_booking(self, booking_id, headers):
        return self._request(
            "POST", f"/private-bookings/{booking_id}/cancel", {}, headers=headers
        )

    # --- Retail orders ---
    def create_retail_order(self, payload, headers):
        return self._request("POST", "/retail-orders", payload, headers=headers)

    def get_retail_order(self, order_id, headers):
        return self._request("GET", f"/retail-orders/{order_id}", headers=headers)

    def list_retail_orders(self, headers, params=None):
        return self._request("GET", "/retail-orders", headers=headers, params=params)

    def fulfill_retail_order(self, order_id, headers):
        return self._request("POST", f"/retail-orders/{order_id}/fulfill", {}, headers=headers)

    def cancel_retail_order(self, order_id, headers):
        return self._request("POST", f"/retail-orders/{order_id}/cancel", {}, headers=headers)


api_client = ApiClient()
