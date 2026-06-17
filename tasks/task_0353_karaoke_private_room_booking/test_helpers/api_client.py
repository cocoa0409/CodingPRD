"""API client: one method per endpoint defined in the Karaoke Private Room Booking PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Venue ────────────────────────────────────────
    def create_venue(self, payload, headers):
        return self._request("POST", "/venues", payload, headers)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/venues/{venue_id}", headers=headers)

    def set_clock(self, venue_id, payload, headers):
        return self._request("POST", f"/venues/{venue_id}/_clock/set", payload, headers)

    def run_ops(self, venue_id, headers, payload=None):
        return self._request("POST", f"/venues/{venue_id}/_ops/run", payload or {}, headers)

    # ─── RoomType ─────────────────────────────────────
    def create_room_type(self, payload, headers):
        return self._request("POST", "/room-types", payload, headers)

    def list_room_types(self, headers, params=None):
        return self._request("GET", "/room-types", headers=headers, params=params)

    def get_room_type(self, room_type_id, headers):
        return self._request("GET", f"/room-types/{room_type_id}", headers=headers)

    # ─── Room ─────────────────────────────────────────
    def create_room(self, payload, headers):
        return self._request("POST", "/rooms", payload, headers)

    def list_rooms(self, headers, params=None):
        return self._request("GET", "/rooms", headers=headers, params=params)

    def get_room(self, room_id, headers):
        return self._request("GET", f"/rooms/{room_id}", headers=headers)

    def room_maintenance(self, room_id, payload, headers):
        return self._request("POST", f"/rooms/{room_id}/maintenance", payload, headers)

    # ─── GroupPackage ─────────────────────────────────
    def create_group_package(self, payload, headers):
        return self._request("POST", "/group-packages", payload, headers)

    def list_group_packages(self, headers, params=None):
        return self._request("GET", "/group-packages", headers=headers, params=params)

    def get_group_package(self, group_package_id, headers):
        return self._request("GET", f"/group-packages/{group_package_id}", headers=headers)

    # ─── Customer ─────────────────────────────────────
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # ─── Song ─────────────────────────────────────────
    def create_song(self, payload, headers):
        return self._request("POST", "/songs", payload, headers)

    def list_songs(self, headers, params=None):
        return self._request("GET", "/songs", headers=headers, params=params)

    def get_song(self, song_id, headers):
        return self._request("GET", f"/songs/{song_id}", headers=headers)

    # ─── Reservation ──────────────────────────────────
    def create_reservation(self, payload, headers):
        return self._request("POST", "/reservations", payload, headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/reservations", headers=headers, params=params)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/reservations/{reservation_id}", headers=headers)

    def confirm_reservation(self, reservation_id, headers, payload=None):
        return self._request("POST", f"/reservations/{reservation_id}/confirm", payload or {}, headers)

    def check_in_reservation(self, reservation_id, headers, payload=None):
        return self._request("POST", f"/reservations/{reservation_id}/check-in", payload or {}, headers)

    def close_reservation(self, reservation_id, payload, headers):
        return self._request("POST", f"/reservations/{reservation_id}/close", payload, headers)

    def cancel_reservation(self, reservation_id, headers, payload=None):
        return self._request("POST", f"/reservations/{reservation_id}/cancel", payload or {}, headers)

    # ─── Extension ────────────────────────────────────
    def create_extension(self, reservation_id, payload, headers):
        return self._request("POST", f"/reservations/{reservation_id}/extensions", payload, headers)

    def list_extensions(self, headers, params=None):
        return self._request("GET", "/extensions", headers=headers, params=params)

    def get_extension(self, extension_id, headers):
        return self._request("GET", f"/extensions/{extension_id}", headers=headers)

    # ─── QueueEntry ───────────────────────────────────
    def queue_song(self, reservation_id, payload, headers):
        return self._request("POST", f"/reservations/{reservation_id}/queue", payload, headers)

    def list_queue_entries(self, headers, params=None):
        return self._request("GET", "/queue-entries", headers=headers, params=params)

    def get_queue_entry(self, queue_entry_id, headers):
        return self._request("GET", f"/queue-entries/{queue_entry_id}", headers=headers)

    def play_queue_entry(self, queue_entry_id, headers, payload=None):
        return self._request("POST", f"/queue-entries/{queue_entry_id}/play", payload or {}, headers)

    def skip_queue_entry(self, queue_entry_id, headers, payload=None):
        return self._request("POST", f"/queue-entries/{queue_entry_id}/skip", payload or {}, headers)

    def cancel_queue_entry(self, queue_entry_id, headers):
        return self._request("DELETE", f"/queue-entries/{queue_entry_id}", headers=headers)

    # ─── FbOrder ──────────────────────────────────────
    def create_fb_order(self, reservation_id, payload, headers):
        return self._request("POST", f"/reservations/{reservation_id}/fb-orders", payload, headers)

    def list_fb_orders(self, headers, params=None):
        return self._request("GET", "/fb-orders", headers=headers, params=params)

    def get_fb_order(self, fb_order_id, headers):
        return self._request("GET", f"/fb-orders/{fb_order_id}", headers=headers)

    def void_fb_order(self, fb_order_id, headers, payload=None):
        return self._request("POST", f"/fb-orders/{fb_order_id}/void", payload or {}, headers)

    # ─── Payment (read-only ledger) ───────────────────
    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)


api_client = ApiClient()
