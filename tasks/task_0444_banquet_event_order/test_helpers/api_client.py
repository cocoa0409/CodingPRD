"""API client: one method per endpoint defined in the Banquet Event Order PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock (administrative) ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- Function rooms (shared resource) ----
    def create_function_room(self, payload, headers):
        return self._request("POST", "/function-rooms", payload, headers)

    def get_function_room(self, room_id, headers):
        return self._request("GET", f"/function-rooms/{room_id}", headers=headers)

    def list_function_rooms(self, headers, params=None):
        return self._request("GET", "/function-rooms", headers=headers, params=params)

    def list_function_room_bookings(self, room_id, headers, params=None):
        return self._request("GET", f"/function-rooms/{room_id}/bookings", headers=headers, params=params)

    # ---- Hotel room blocks (shared resource) ----
    def create_hotel_room_block(self, payload, headers):
        return self._request("POST", "/hotel-room-blocks", payload, headers)

    def get_hotel_room_block(self, block_id, headers):
        return self._request("GET", f"/hotel-room-blocks/{block_id}", headers=headers)

    def list_hotel_room_blocks(self, headers, params=None):
        return self._request("GET", "/hotel-room-blocks", headers=headers, params=params)

    def list_block_room_block_links(self, block_id, headers, params=None):
        return self._request("GET", f"/hotel-room-blocks/{block_id}/room-block-links", headers=headers, params=params)

    # ---- Event lifecycle ----
    def create_event(self, payload, headers):
        return self._request("POST", "/events", payload, headers)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/events/{event_id}", headers=headers)

    def list_events(self, headers, params=None):
        return self._request("GET", "/events", headers=headers, params=params)

    def hold_event(self, event_id, headers, payload=None):
        return self._request("POST", f"/events/{event_id}/hold", payload or {}, headers)

    def confirm_space(self, event_id, headers, payload=None):
        return self._request("POST", f"/events/{event_id}/confirm-space", payload or {}, headers)

    def reopen_event(self, event_id, headers, payload=None):
        return self._request("POST", f"/events/{event_id}/reopen", payload or {}, headers)

    def lock_guarantee(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/lock-guarantee", payload, headers)

    def actualize_event(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/actualize", payload, headers)

    def cancel_event(self, event_id, headers, payload=None):
        return self._request("POST", f"/events/{event_id}/cancel", payload or {}, headers)

    # ---- Function-room bookings ----
    def create_booking(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/bookings", payload, headers)

    def list_event_bookings(self, event_id, headers, params=None):
        return self._request("GET", f"/events/{event_id}/bookings", headers=headers, params=params)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/bookings", headers=headers, params=params)

    def get_booking(self, event_id, booking_id, headers):
        return self._request("GET", f"/events/{event_id}/bookings/{booking_id}", headers=headers)

    def make_definite(self, event_id, booking_id, headers, payload=None):
        return self._request("POST", f"/events/{event_id}/bookings/{booking_id}/make-definite", payload or {}, headers)

    def soften_booking(self, event_id, booking_id, headers, payload=None):
        return self._request("POST", f"/events/{event_id}/bookings/{booking_id}/soften", payload or {}, headers)

    def release_booking(self, event_id, booking_id, headers, payload=None):
        return self._request("POST", f"/events/{event_id}/bookings/{booking_id}/release", payload or {}, headers)

    # ---- Menu lines ----
    def create_menu_line(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/menu-lines", payload, headers)

    def list_menu_lines(self, event_id, headers, params=None):
        return self._request("GET", f"/events/{event_id}/menu-lines", headers=headers, params=params)

    def delete_menu_line(self, event_id, menu_line_id, headers):
        return self._request("DELETE", f"/events/{event_id}/menu-lines/{menu_line_id}", headers=headers)

    # ---- Service lines ----
    def create_service_line(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/service-lines", payload, headers)

    def list_service_lines(self, event_id, headers, params=None):
        return self._request("GET", f"/events/{event_id}/service-lines", headers=headers, params=params)

    def delete_service_line(self, event_id, service_line_id, headers):
        return self._request("DELETE", f"/events/{event_id}/service-lines/{service_line_id}", headers=headers)

    # ---- Room-block links ----
    def create_room_block_link(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/room-block-links", payload, headers)

    def list_event_room_block_links(self, event_id, headers, params=None):
        return self._request("GET", f"/events/{event_id}/room-block-links", headers=headers, params=params)

    def list_room_block_links(self, headers, params=None):
        return self._request("GET", "/room-block-links", headers=headers, params=params)

    def record_pickup(self, event_id, link_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/room-block-links/{link_id}/record-pickup", payload, headers)

    def release_link(self, event_id, link_id, headers, payload=None):
        return self._request("POST", f"/events/{event_id}/room-block-links/{link_id}/release", payload or {}, headers)

    # ---- Payment-schedule items ----
    def create_payment_schedule_item(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/payment-schedule-items", payload, headers)

    def list_payment_schedule_items(self, event_id, headers, params=None):
        return self._request("GET", f"/events/{event_id}/payment-schedule-items", headers=headers, params=params)

    # ---- Payments (event log) ----
    def create_payment(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/payments", payload, headers)

    def list_payments(self, event_id, headers, params=None):
        return self._request("GET", f"/events/{event_id}/payments", headers=headers, params=params)

    def void_payment(self, event_id, payment_id, headers, payload=None):
        return self._request("POST", f"/events/{event_id}/payments/{payment_id}/void", payload or {}, headers)


api_client = ApiClient()
