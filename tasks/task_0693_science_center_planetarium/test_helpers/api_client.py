"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Venues ---
    def create_venue(self, payload, headers):
        return self._request("POST", "/venues", payload, headers)

    def list_venues(self, headers, params=None):
        return self._request("GET", "/venues", headers=headers, params=params)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/venues/{venue_id}", headers=headers)

    def list_venue_shows(self, venue_id, headers, params=None):
        return self._request("GET", f"/venues/{venue_id}/shows", headers=headers, params=params)

    def list_venue_programs(self, venue_id, headers, params=None):
        return self._request("GET", f"/venues/{venue_id}/programs", headers=headers, params=params)

    def list_venue_rentals(self, venue_id, headers, params=None):
        return self._request("GET", f"/venues/{venue_id}/rentals", headers=headers, params=params)

    # --- Memberships ---
    def create_membership(self, payload, headers):
        return self._request("POST", "/memberships", payload, headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", "/memberships", headers=headers, params=params)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/memberships/{membership_id}", headers=headers)

    def activate_membership(self, membership_id, payload, headers):
        return self._request("POST", f"/memberships/{membership_id}/activate", payload, headers)

    def cancel_membership(self, membership_id, headers):
        return self._request("POST", f"/memberships/{membership_id}/cancel", {}, headers)

    def get_membership_astc_status(self, membership_id, headers):
        return self._request("GET", f"/memberships/{membership_id}/astc-status", headers=headers)

    # --- Shows ---
    def create_show(self, payload, headers):
        return self._request("POST", "/shows", payload, headers)

    def list_shows(self, headers, params=None):
        return self._request("GET", "/shows", headers=headers, params=params)

    def get_show(self, show_id, headers):
        return self._request("GET", f"/shows/{show_id}", headers=headers)

    def open_show(self, show_id, headers):
        return self._request("POST", f"/shows/{show_id}/open", {}, headers)

    def cancel_show(self, show_id, headers):
        return self._request("POST", f"/shows/{show_id}/cancel", {}, headers)

    def complete_show(self, show_id, headers):
        return self._request("POST", f"/shows/{show_id}/complete", {}, headers)

    # --- Show Bookings ---
    def create_show_booking(self, payload, headers):
        return self._request("POST", "/show-bookings", payload, headers)

    def list_show_bookings(self, headers, params=None):
        return self._request("GET", "/show-bookings", headers=headers, params=params)

    def get_show_booking(self, booking_id, headers):
        return self._request("GET", f"/show-bookings/{booking_id}", headers=headers)

    def confirm_show_booking(self, booking_id, headers):
        return self._request("POST", f"/show-bookings/{booking_id}/confirm", {}, headers)

    def cancel_show_booking(self, booking_id, headers):
        return self._request("POST", f"/show-bookings/{booking_id}/cancel", {}, headers)

    def refund_show_booking(self, booking_id, headers):
        return self._request("POST", f"/show-bookings/{booking_id}/refund", {}, headers)

    # --- Group Bookings ---
    def create_group_booking(self, payload, headers):
        return self._request("POST", "/group-bookings", payload, headers)

    def list_group_bookings(self, headers, params=None):
        return self._request("GET", "/group-bookings", headers=headers, params=params)

    def get_group_booking(self, gb_id, headers):
        return self._request("GET", f"/group-bookings/{gb_id}", headers=headers)

    def pay_group_deposit(self, gb_id, headers):
        return self._request("POST", f"/group-bookings/{gb_id}/pay-deposit", {}, headers)

    def confirm_group_booking(self, gb_id, payload, headers):
        return self._request("POST", f"/group-bookings/{gb_id}/confirm", payload, headers)

    def cancel_group_booking(self, gb_id, headers):
        return self._request("POST", f"/group-bookings/{gb_id}/cancel", {}, headers)

    # --- Programs ---
    def create_program(self, payload, headers):
        return self._request("POST", "/programs", payload, headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/programs", headers=headers, params=params)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/programs/{program_id}", headers=headers)

    def start_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/start", {}, headers)

    def cancel_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/cancel", {}, headers)

    # --- Registrations ---
    def create_registration(self, payload, headers):
        return self._request("POST", "/registrations", payload, headers)

    def list_registrations(self, headers, params=None):
        return self._request("GET", "/registrations", headers=headers, params=params)

    def get_registration(self, registration_id, headers):
        return self._request("GET", f"/registrations/{registration_id}", headers=headers)

    def cancel_registration(self, registration_id, headers):
        return self._request("POST", f"/registrations/{registration_id}/cancel", {}, headers)

    # --- Rentals ---
    def create_rental(self, payload, headers):
        return self._request("POST", "/rentals", payload, headers)

    def list_rentals(self, headers, params=None):
        return self._request("GET", "/rentals", headers=headers, params=params)

    def get_rental(self, rental_id, headers):
        return self._request("GET", f"/rentals/{rental_id}", headers=headers)

    def hold_rental(self, rental_id, headers):
        return self._request("POST", f"/rentals/{rental_id}/hold", {}, headers)

    def confirm_rental(self, rental_id, payload, headers):
        return self._request("POST", f"/rentals/{rental_id}/confirm", payload, headers)

    def cancel_rental(self, rental_id, headers):
        return self._request("POST", f"/rentals/{rental_id}/cancel", {}, headers)

    # --- Sponsors / Contributions ---
    def create_sponsor(self, payload, headers):
        return self._request("POST", "/sponsors", payload, headers)

    def list_sponsors(self, headers, params=None):
        return self._request("GET", "/sponsors", headers=headers, params=params)

    def get_sponsor(self, sponsor_id, headers):
        return self._request("GET", f"/sponsors/{sponsor_id}", headers=headers)

    def create_contribution(self, sponsor_id, payload, headers):
        return self._request("POST", f"/sponsors/{sponsor_id}/contributions", payload, headers)

    def list_contributions(self, sponsor_id, headers, params=None):
        return self._request("GET", f"/sponsors/{sponsor_id}/contributions", headers=headers, params=params)

    def lapse_sponsor(self, sponsor_id, headers):
        return self._request("POST", f"/sponsors/{sponsor_id}/lapse", {}, headers)

    # --- Accommodations ---
    def create_accommodation(self, payload, headers):
        return self._request("POST", "/accommodations", payload, headers)

    def list_accommodations(self, headers, params=None):
        return self._request("GET", "/accommodations", headers=headers, params=params)

    def get_accommodation(self, accommodation_id, headers):
        return self._request("GET", f"/accommodations/{accommodation_id}", headers=headers)

    def approve_accommodation(self, accommodation_id, headers):
        return self._request("POST", f"/accommodations/{accommodation_id}/approve", {}, headers)

    def deny_accommodation(self, accommodation_id, headers):
        return self._request("POST", f"/accommodations/{accommodation_id}/deny", {}, headers)

    def fulfill_accommodation(self, accommodation_id, headers):
        return self._request("POST", f"/accommodations/{accommodation_id}/fulfill", {}, headers)

    # --- System: logical clock and sweeps ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    def run_sweeps(self, headers):
        return self._request("POST", "/_sweeps/run", {}, headers)


api_client = ApiClient()
