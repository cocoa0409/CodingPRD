"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Studio / inventory ───────────────────────────
    def create_studio(self, payload, headers):
        return self._request("POST", "/studio", payload, headers)

    def get_studio(self, studio_id, headers):
        return self._request("GET", f"/studio/{studio_id}", headers=headers)

    def create_room(self, payload, headers):
        return self._request("POST", "/studio/rooms", payload, headers)

    def get_room(self, room_id, headers):
        return self._request("GET", f"/studio/rooms/{room_id}", headers=headers)

    def list_rooms(self, headers, params=None):
        return self._request("GET", "/studio/rooms", headers=headers, params=params)

    def create_engineer(self, payload, headers):
        return self._request("POST", "/studio/engineers", payload, headers)

    def get_engineer(self, engineer_id, headers):
        return self._request("GET", f"/studio/engineers/{engineer_id}", headers=headers)

    def list_engineers(self, headers, params=None):
        return self._request("GET", "/studio/engineers", headers=headers, params=params)

    def create_gear_item(self, payload, headers):
        return self._request("POST", "/studio/gear-items", payload, headers)

    def get_gear_item(self, gear_item_id, headers):
        return self._request("GET", f"/studio/gear-items/{gear_item_id}", headers=headers)

    def list_gear_items(self, headers, params=None):
        return self._request("GET", "/studio/gear-items", headers=headers, params=params)

    # ─── Clients ──────────────────────────────────────
    def register_client(self, payload, headers):
        return self._request("POST", "/studio/clients/register", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/studio/clients/{client_id}", headers=headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/studio/clients", headers=headers, params=params)

    # ─── Bookings ─────────────────────────────────────
    def create_booking(self, payload, headers):
        return self._request("POST", "/studio/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/studio/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/studio/bookings", headers=headers, params=params)

    def confirm_booking(self, booking_id, headers):
        return self._request("POST", f"/studio/bookings/{booking_id}/confirm", {}, headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/studio/bookings/{booking_id}/cancel", {}, headers)

    def check_in_booking(self, booking_id, headers):
        return self._request("POST", f"/studio/bookings/{booking_id}/check-in", {}, headers)

    def check_out_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/studio/bookings/{booking_id}/check-out", payload, headers)

    # ─── Payments ─────────────────────────────────────
    def create_payment(self, booking_id, payload, headers):
        return self._request("POST", f"/studio/bookings/{booking_id}/payments", payload, headers)

    def list_booking_payments(self, booking_id, headers, params=None):
        return self._request("GET", f"/studio/bookings/{booking_id}/payments", headers=headers, params=params)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/studio/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/studio/payments", headers=headers, params=params)

    # ─── Gear rentals (Booking sub-resource) ──────────
    def create_gear_rental(self, booking_id, payload, headers):
        return self._request("POST", f"/studio/bookings/{booking_id}/gear-rentals", payload, headers)

    def list_booking_gear_rentals(self, booking_id, headers, params=None):
        return self._request("GET", f"/studio/bookings/{booking_id}/gear-rentals", headers=headers, params=params)

    def get_gear_rental(self, rental_id, headers):
        return self._request("GET", f"/studio/gear-rentals/{rental_id}", headers=headers)

    def list_gear_rentals(self, headers, params=None):
        return self._request("GET", "/studio/gear-rentals", headers=headers, params=params)

    def release_gear_rental(self, booking_id, rental_id, headers):
        return self._request("DELETE", f"/studio/bookings/{booking_id}/gear-rentals/{rental_id}", headers=headers)

    # ─── Engineer assignments (Booking sub-resource) ──
    def create_engineer_assignment(self, booking_id, payload, headers):
        return self._request("POST", f"/studio/bookings/{booking_id}/engineer-assignments", payload, headers)

    def list_booking_engineer_assignments(self, booking_id, headers, params=None):
        return self._request("GET", f"/studio/bookings/{booking_id}/engineer-assignments", headers=headers, params=params)

    def get_engineer_assignment(self, assign_id, headers):
        return self._request("GET", f"/studio/engineer-assignments/{assign_id}", headers=headers)

    def list_engineer_assignments(self, headers, params=None):
        return self._request("GET", "/studio/engineer-assignments", headers=headers, params=params)

    def release_engineer_assignment(self, booking_id, assign_id, headers):
        return self._request("DELETE", f"/studio/bookings/{booking_id}/engineer-assignments/{assign_id}", headers=headers)

    # ─── Overtime records ─────────────────────────────
    def list_booking_overtime_records(self, booking_id, headers, params=None):
        return self._request("GET", f"/studio/bookings/{booking_id}/overtime-records", headers=headers, params=params)

    # ─── Lockout contracts ────────────────────────────
    def create_lockout_contract(self, payload, headers):
        return self._request("POST", "/studio/lockout-contracts", payload, headers)

    def get_lockout_contract(self, contract_id, headers):
        return self._request("GET", f"/studio/lockout-contracts/{contract_id}", headers=headers)

    def list_lockout_contracts(self, headers, params=None):
        return self._request("GET", "/studio/lockout-contracts", headers=headers, params=params)

    def activate_lockout_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/studio/lockout-contracts/{contract_id}/activate", payload, headers)

    def terminate_lockout_contract(self, contract_id, headers):
        return self._request("POST", f"/studio/lockout-contracts/{contract_id}/terminate", {}, headers)

    # ─── Session delivery (Booking sub-resource) ──────
    def deliver_session(self, booking_id, payload, headers):
        return self._request("POST", f"/studio/bookings/{booking_id}/delivery/deliver", payload, headers)

    def request_revision(self, booking_id, headers):
        return self._request("POST", f"/studio/bookings/{booking_id}/delivery/request-revision", {}, headers)

    def accept_delivery(self, booking_id, headers):
        return self._request("POST", f"/studio/bookings/{booking_id}/delivery/accept", {}, headers)

    def list_booking_delivery(self, booking_id, headers, params=None):
        return self._request("GET", f"/studio/bookings/{booking_id}/delivery", headers=headers, params=params)

    # ─── Test-driving clock + sweep ───────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def release_expired_holds(self, headers):
        return self._request("POST", "/_sweep/release_expired_holds", {}, headers)


api_client = ApiClient()
