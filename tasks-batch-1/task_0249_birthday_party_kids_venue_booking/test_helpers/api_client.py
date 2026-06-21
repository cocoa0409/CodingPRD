"""API client: one method per endpoint defined in the Kids Venue Booking PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Venues ───────────────────────────────────────────────────────────────
    def create_venue(self, payload, headers):
        return self._request("POST", "/venues", payload, headers)

    def list_venues(self, headers, params=None):
        return self._request("GET", "/venues", headers=headers, params=params)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/venues/{venue_id}", headers=headers)

    # ─── Rooms ────────────────────────────────────────────────────────────────
    def create_room(self, payload, headers):
        return self._request("POST", "/rooms", payload, headers)

    def list_rooms(self, headers, params=None):
        return self._request("GET", "/rooms", headers=headers, params=params)

    def get_room(self, room_id, headers):
        return self._request("GET", f"/rooms/{room_id}", headers=headers)

    def close_room(self, room_id, headers):
        return self._request("POST", f"/rooms/{room_id}/close", headers=headers)

    # ─── Packages ─────────────────────────────────────────────────────────────
    def create_package(self, payload, headers):
        return self._request("POST", "/packages", payload, headers)

    def list_packages(self, headers, params=None):
        return self._request("GET", "/packages", headers=headers, params=params)

    def get_package(self, package_id, headers):
        return self._request("GET", f"/packages/{package_id}", headers=headers)

    def retire_package(self, package_id, headers):
        return self._request("POST", f"/packages/{package_id}/retire", headers=headers)

    # ─── Staff members ────────────────────────────────────────────────────────
    def create_staff_member(self, payload, headers):
        return self._request("POST", "/staff-members", payload, headers)

    def list_staff_members(self, headers, params=None):
        return self._request("GET", "/staff-members", headers=headers, params=params)

    def get_staff_member(self, staff_member_id, headers):
        return self._request("GET", f"/staff-members/{staff_member_id}", headers=headers)

    def deactivate_staff_member(self, staff_member_id, headers):
        return self._request("POST", f"/staff-members/{staff_member_id}/deactivate", headers=headers)

    def list_staff_member_assignments(self, staff_member_id, headers, params=None):
        return self._request("GET", f"/staff-members/{staff_member_id}/staff-assignments",
                             headers=headers, params=params)

    # ─── Bookings (core) ──────────────────────────────────────────────────────
    def create_booking(self, payload, headers):
        return self._request("POST", "/bookings", payload, headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/bookings", headers=headers, params=params)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def update_booking(self, booking_id, payload, headers):
        return self._request("PATCH", f"/bookings/{booking_id}", payload, headers)

    def hold_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/hold", headers=headers)

    def release_hold_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/release-hold", headers=headers)

    def confirm_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/confirm", headers=headers)

    def weather_hold_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/weather-hold", headers=headers)

    def reschedule_booking(self, booking_id, payload, headers):
        return self._request("PATCH", f"/bookings/{booking_id}/reschedule", payload, headers)

    def complete_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/complete", headers=headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/cancel", headers=headers)

    # ─── Add-ons ──────────────────────────────────────────────────────────────
    def create_add_on(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/add-ons", payload, headers)

    def list_add_ons(self, booking_id, headers, params=None):
        return self._request("GET", f"/bookings/{booking_id}/add-ons", headers=headers, params=params)

    def delete_add_on(self, booking_id, add_on_id, headers):
        return self._request("DELETE", f"/bookings/{booking_id}/add-ons/{add_on_id}", headers=headers)

    # ─── Guest parties (roster events) ────────────────────────────────────────
    def create_guest_party(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/guest-parties", payload, headers)

    def list_guest_parties(self, booking_id, headers, params=None):
        return self._request("GET", f"/bookings/{booking_id}/guest-parties", headers=headers, params=params)

    # ─── Waivers ──────────────────────────────────────────────────────────────
    def create_waiver(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/waivers", payload, headers)

    def list_waivers(self, booking_id, headers, params=None):
        return self._request("GET", f"/bookings/{booking_id}/waivers", headers=headers, params=params)

    def sign_waiver(self, booking_id, waiver_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/waivers/{waiver_id}/sign", payload, headers)

    def revoke_waiver(self, booking_id, waiver_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/waivers/{waiver_id}/revoke", headers=headers)

    # ─── Staff assignments ────────────────────────────────────────────────────
    def create_staff_assignment(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/staff-assignments", payload, headers)

    def list_staff_assignments(self, booking_id, headers, params=None):
        return self._request("GET", f"/bookings/{booking_id}/staff-assignments", headers=headers, params=params)

    def release_staff_assignment(self, booking_id, assignment_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/staff-assignments/{assignment_id}/release",
                             headers=headers)

    # ─── Payments ─────────────────────────────────────────────────────────────
    def create_payment(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/payments", payload, headers)

    def list_payments(self, booking_id, headers, params=None):
        return self._request("GET", f"/bookings/{booking_id}/payments", headers=headers, params=params)

    def void_payment(self, booking_id, payment_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/payments/{payment_id}/void", headers=headers)

    # ─── Logical clock ────────────────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def get_clock(self, headers):
        return self._request("GET", "/_clock", headers=headers)


api_client = ApiClient()
