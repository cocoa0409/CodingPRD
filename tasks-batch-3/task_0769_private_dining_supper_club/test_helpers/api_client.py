"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Series ---
    def create_series(self, payload, headers):
        return self._request("POST", "/series", payload, headers)

    def get_series(self, series_id, headers):
        return self._request("GET", f"/series/{series_id}", headers=headers)

    # --- Venues ---
    def create_venue(self, payload, headers):
        return self._request("POST", "/venues", payload, headers)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/venues/{venue_id}", headers=headers)

    # --- Chefs ---
    def create_chef(self, payload, headers):
        return self._request("POST", "/chefs", payload, headers)

    def get_chef(self, chef_id, headers):
        return self._request("GET", f"/chefs/{chef_id}", headers=headers)

    def set_chef_availability(self, chef_id, payload, headers):
        return self._request("POST", f"/chefs/{chef_id}/set-availability", payload, headers)

    # --- Guests ---
    def create_guest(self, payload, headers):
        return self._request("POST", "/guests", payload, headers)

    def get_guest(self, guest_id, headers):
        return self._request("GET", f"/guests/{guest_id}", headers=headers)

    # --- Events ---
    def create_event(self, payload, headers):
        return self._request("POST", "/events", payload, headers)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/events/{event_id}", headers=headers)

    def list_events(self, headers, params=None):
        return self._request("GET", "/events", headers=headers, params=params)

    def schedule_event(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/schedule", payload, headers)

    def open_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/open", {}, headers)

    def suspend_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/suspend", {}, headers)

    def resume_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/resume", {}, headers)

    def complete_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/complete", {}, headers)

    def cancel_event(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/cancel", payload, headers)

    def reprice_event(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/reprice", payload, headers)

    def list_event_seats(self, event_id, headers, params=None):
        return self._request("GET", f"/events/{event_id}/seats", headers=headers, params=params)

    def list_event_menu(self, event_id, headers):
        return self._request("GET", f"/events/{event_id}/menu", headers=headers)

    def list_event_waitlist(self, event_id, headers, params=None):
        return self._request("GET", f"/events/{event_id}/waitlist", headers=headers, params=params)

    def create_menu_course(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/menu-courses", payload, headers)

    def join_waitlist(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/waitlist", payload, headers)

    # --- Waitlist ---
    def get_waitlist_entry(self, entry_id, headers):
        return self._request("GET", f"/waitlist/{entry_id}", headers=headers)

    def list_waitlist(self, headers, params=None):
        return self._request("GET", "/waitlist", headers=headers, params=params)

    def withdraw_waitlist(self, entry_id, headers):
        return self._request("POST", f"/waitlist/{entry_id}/withdraw", {}, headers)

    # --- Bookings ---
    def create_booking(self, payload, headers):
        return self._request("POST", "/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/bookings", headers=headers, params=params)

    def pay_deposit(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/pay-deposit", payload, headers)

    def check_in_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/check-in", {}, headers)

    def cancel_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/cancel", payload, headers)

    def list_booking_seats(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}/seats", headers=headers)

    def list_booking_payments(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}/payments", headers=headers)


api_client = ApiClient()
