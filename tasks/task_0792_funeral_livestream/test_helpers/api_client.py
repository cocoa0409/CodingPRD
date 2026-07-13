"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- FuneralHome ----
    def create_funeral_home(self, payload, headers):
        return self._request("POST", "/funeral-homes", payload, headers=headers)

    def get_funeral_home(self, home_id, headers):
        return self._request("GET", f"/funeral-homes/{home_id}", headers=headers)

    def grant_credits(self, home_id, payload, headers):
        return self._request("POST", f"/funeral-homes/{home_id}/credit-grants", payload, headers=headers)

    # ---- Venue ----
    def create_venue(self, payload, headers):
        return self._request("POST", "/venues", payload, headers=headers)

    def list_venues(self, headers, params=None):
        return self._request("GET", "/venues", headers=headers, params=params)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/venues/{venue_id}", headers=headers)

    # ---- Operator ----
    def create_operator(self, payload, headers):
        return self._request("POST", "/operators", payload, headers=headers)

    def list_operators(self, headers, params=None):
        return self._request("GET", "/operators", headers=headers, params=params)

    def get_operator(self, operator_id, headers):
        return self._request("GET", f"/operators/{operator_id}", headers=headers)

    def set_duty(self, operator_id, payload, headers):
        return self._request("POST", f"/operators/{operator_id}/duty", payload, headers=headers)

    # ---- ServiceOrder ----
    def create_service_order(self, payload, headers):
        return self._request("POST", "/service-orders", payload, headers=headers)

    def list_service_orders(self, headers, params=None):
        return self._request("GET", "/service-orders", headers=headers, params=params)

    def get_service_order(self, order_id, headers):
        return self._request("GET", f"/service-orders/{order_id}", headers=headers)

    def transition_service_order(self, order_id, payload, headers):
        return self._request("POST", f"/service-orders/{order_id}/transitions", payload, headers=headers)

    def access_service_order(self, order_id, payload, headers):
        return self._request("POST", f"/service-orders/{order_id}/access", payload, headers=headers)

    # ---- VenueBooking ----
    def create_venue_booking(self, payload, headers):
        return self._request("POST", "/venue-bookings", payload, headers=headers)

    def list_venue_bookings(self, headers, params=None):
        return self._request("GET", "/venue-bookings", headers=headers, params=params)

    def get_venue_booking(self, booking_id, headers):
        return self._request("GET", f"/venue-bookings/{booking_id}", headers=headers)

    def confirm_venue_booking(self, booking_id, headers):
        return self._request("POST", f"/venue-bookings/{booking_id}/confirm", {}, headers=headers)

    # ---- CameraAssignment ----
    def create_camera_assignment(self, payload, headers):
        return self._request("POST", "/camera-assignments", payload, headers=headers)

    def list_camera_assignments(self, headers, params=None):
        return self._request("GET", "/camera-assignments", headers=headers, params=params)

    def get_camera_assignment(self, assignment_id, headers):
        return self._request("GET", f"/camera-assignments/{assignment_id}", headers=headers)

    # ---- GuestbookEntry ----
    def create_guestbook_entry(self, payload, headers):
        return self._request("POST", "/guestbook-entries", payload, headers=headers)

    def list_guestbook_entries(self, headers, params=None):
        return self._request("GET", "/guestbook-entries", headers=headers, params=params)

    def get_guestbook_entry(self, entry_id, headers):
        return self._request("GET", f"/guestbook-entries/{entry_id}", headers=headers)

    def moderate_guestbook_entry(self, entry_id, payload, headers):
        return self._request("POST", f"/guestbook-entries/{entry_id}/moderation", payload, headers=headers)

    # ---- Donation ----
    def create_donation(self, payload, headers):
        return self._request("POST", "/donations", payload, headers=headers)

    def list_donations(self, headers, params=None):
        return self._request("GET", "/donations", headers=headers, params=params)

    def get_donation(self, donation_id, headers):
        return self._request("GET", f"/donations/{donation_id}", headers=headers)

    def transition_donation(self, donation_id, payload, headers):
        return self._request("POST", f"/donations/{donation_id}/transitions", payload, headers=headers)

    # ---- TributeVideo ----
    def create_tribute_video(self, payload, headers):
        return self._request("POST", "/tribute-videos", payload, headers=headers)

    def list_tribute_videos(self, headers, params=None):
        return self._request("GET", "/tribute-videos", headers=headers, params=params)

    def get_tribute_video(self, tribute_id, headers):
        return self._request("GET", f"/tribute-videos/{tribute_id}", headers=headers)

    def transition_tribute_video(self, tribute_id, payload, headers):
        return self._request("POST", f"/tribute-videos/{tribute_id}/transitions", payload, headers=headers)

    # ---- Test-driving: logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers=headers)


api_client = ApiClient()
