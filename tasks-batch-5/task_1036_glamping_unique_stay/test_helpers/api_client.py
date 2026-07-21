"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- Host ----
    def create_host(self, payload, headers):
        return self._request("POST", "/hosts", payload, headers)

    def get_host(self, host_id, headers):
        return self._request("GET", f"/hosts/{host_id}", headers=headers)

    # ---- Guest ----
    def create_guest(self, payload, headers):
        return self._request("POST", "/guests", payload, headers)

    def get_guest(self, guest_id, headers):
        return self._request("GET", f"/guests/{guest_id}", headers=headers)

    # ---- Listing ----
    def create_listing(self, payload, headers):
        return self._request("POST", "/listings", payload, headers)

    def get_listing(self, listing_id, headers):
        return self._request("GET", f"/listings/{listing_id}", headers=headers)

    def list_listings(self, headers, params=None):
        return self._request("GET", "/listings", headers=headers, params=params)

    def publish_listing(self, listing_id, headers):
        return self._request("POST", f"/listings/{listing_id}/publish", {}, headers)

    def suspend_listing(self, listing_id, headers):
        return self._request("POST", f"/listings/{listing_id}/suspend", {}, headers)

    def reinstate_listing(self, listing_id, headers):
        return self._request("POST", f"/listings/{listing_id}/reinstate", {}, headers)

    def delist_listing(self, listing_id, headers):
        return self._request("POST", f"/listings/{listing_id}/delist", {}, headers)

    # ---- Permit ----
    def create_permit(self, listing_id, payload, headers):
        return self._request("POST", f"/listings/{listing_id}/permits", payload, headers)

    def list_permits(self, listing_id, headers, params=None):
        return self._request(
            "GET", f"/listings/{listing_id}/permits", headers=headers, params=params
        )

    def submit_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/submit", {}, headers)

    def decide_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/permits/{permit_id}/decision", payload, headers)

    # ---- SeasonalRate ----
    def create_seasonal_rate(self, listing_id, payload, headers):
        return self._request(
            "POST", f"/listings/{listing_id}/seasonal-rates", payload, headers
        )

    def list_seasonal_rates(self, listing_id, headers, params=None):
        return self._request(
            "GET", f"/listings/{listing_id}/seasonal-rates", headers=headers, params=params
        )

    def reprice_seasonal_rate(self, rate_id, payload, headers):
        return self._request("PATCH", f"/seasonal-rates/{rate_id}", payload, headers)

    # ---- AddOn ----
    def create_add_on(self, listing_id, payload, headers):
        return self._request("POST", f"/listings/{listing_id}/add-ons", payload, headers)

    def list_add_ons(self, listing_id, headers, params=None):
        return self._request(
            "GET", f"/listings/{listing_id}/add-ons", headers=headers, params=params
        )

    def get_add_on(self, add_on_id, headers):
        return self._request("GET", f"/add-ons/{add_on_id}", headers=headers)

    # ---- ExperienceSlot ----
    def create_slot(self, add_on_id, payload, headers):
        return self._request("POST", f"/add-ons/{add_on_id}/slots", payload, headers)

    def list_slots(self, add_on_id, headers, params=None):
        return self._request(
            "GET", f"/add-ons/{add_on_id}/slots", headers=headers, params=params
        )

    # ---- Booking ----
    def create_booking(self, listing_id, payload, headers):
        return self._request("POST", f"/listings/{listing_id}/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/bookings", headers=headers, params=params)

    def attach_add_on(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/add-ons", payload, headers)

    def accept_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/accept", {}, headers)

    def decline_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/decline", {}, headers)

    def check_in_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/check-in", {}, headers)

    def complete_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/complete", {}, headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/cancel", {}, headers)

    # ---- Payout ----
    def get_payout(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}/payout", headers=headers)

    # ---- Review ----
    def create_review(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/reviews", payload, headers)

    def list_reviews(self, booking_id, headers, params=None):
        return self._request(
            "GET", f"/bookings/{booking_id}/reviews", headers=headers, params=params
        )

    # ---- Message ----
    def create_message(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/messages", payload, headers)

    def list_messages(self, booking_id, headers, params=None):
        return self._request(
            "GET", f"/bookings/{booking_id}/messages", headers=headers, params=params
        )


api_client = ApiClient()
