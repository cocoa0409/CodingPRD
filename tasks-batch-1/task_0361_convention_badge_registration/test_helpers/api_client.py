"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Convention ──────────────────────────────────────────────────────────
    def create_convention(self, payload, headers):
        return self._request("POST", "/conventions", payload, headers)

    def get_convention(self, convention_id, headers):
        return self._request("GET", f"/conventions/{convention_id}", headers=headers)

    def list_conventions(self, headers, params=None):
        return self._request("GET", "/conventions", headers=headers, params=params)

    def close_convention(self, convention_id, payload, headers):
        return self._request("POST", f"/conventions/{convention_id}/close", payload, headers)

    def run_lottery(self, convention_id, payload, headers):
        return self._request("POST", f"/conventions/{convention_id}/run-lottery", payload, headers)

    # ─── TicketType ──────────────────────────────────────────────────────────
    def create_ticket_type(self, convention_id, payload, headers):
        return self._request("POST", f"/conventions/{convention_id}/ticket-types", payload, headers)

    def list_ticket_types(self, convention_id, headers, params=None):
        return self._request("GET", f"/conventions/{convention_id}/ticket-types", headers=headers, params=params)

    def get_ticket_type(self, ticket_type_id, headers):
        return self._request("GET", f"/ticket-types/{ticket_type_id}", headers=headers)

    # ─── Attendee ────────────────────────────────────────────────────────────
    def create_attendee(self, payload, headers):
        return self._request("POST", "/attendees", payload, headers)

    def get_attendee(self, attendee_id, headers):
        return self._request("GET", f"/attendees/{attendee_id}", headers=headers)

    def ban_attendee(self, attendee_id, payload, headers):
        return self._request("POST", f"/attendees/{attendee_id}/ban", payload, headers)

    # ─── Order ───────────────────────────────────────────────────────────────
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def list_order_line_items(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/line-items", headers=headers, params=params)

    def list_ticket_line_items(self, headers, params=None):
        return self._request("GET", "/ticket-line-items", headers=headers, params=params)

    def get_ticket_line_item(self, line_item_id, headers):
        return self._request("GET", f"/ticket-line-items/{line_item_id}", headers=headers)

    def submit_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/submit", {}, headers)

    def pay_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/pay", payload, headers)

    def get_refund_quote(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}/refund-quote", headers=headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", {}, headers)

    def refund_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/refund", {}, headers)

    # ─── Badge ───────────────────────────────────────────────────────────────
    def get_badge(self, badge_id, headers):
        return self._request("GET", f"/badges/{badge_id}", headers=headers)

    def list_badges(self, headers, params=None):
        return self._request("GET", "/badges", headers=headers, params=params)

    def pickup_badge(self, badge_id, headers):
        return self._request("POST", f"/badges/{badge_id}/pickup", {}, headers)

    def print_badge(self, badge_id, headers):
        return self._request("POST", f"/badges/{badge_id}/print", {}, headers)

    def transfer_badge(self, badge_id, payload, headers):
        return self._request("POST", f"/badges/{badge_id}/transfer", payload, headers)

    def void_badge(self, badge_id, headers):
        return self._request("POST", f"/badges/{badge_id}/void", {}, headers)

    # ─── Session ─────────────────────────────────────────────────────────────
    def create_session(self, convention_id, payload, headers):
        return self._request("POST", f"/conventions/{convention_id}/sessions", payload, headers)

    def list_sessions(self, convention_id, headers, params=None):
        return self._request("GET", f"/conventions/{convention_id}/sessions", headers=headers, params=params)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/sessions/{session_id}", headers=headers)

    # ─── SessionReservation ──────────────────────────────────────────────────
    def create_session_reservation(self, payload, headers):
        return self._request("POST", "/session-reservations", payload, headers)

    def get_session_reservation(self, reservation_id, headers):
        return self._request("GET", f"/session-reservations/{reservation_id}", headers=headers)

    def list_session_reservations(self, headers, params=None):
        return self._request("GET", "/session-reservations", headers=headers, params=params)

    def cancel_session_reservation(self, reservation_id, headers):
        return self._request("POST", f"/session-reservations/{reservation_id}/cancel", {}, headers)

    # ─── WaitlistEntry ───────────────────────────────────────────────────────
    def create_waitlist_entry(self, convention_id, payload, headers):
        return self._request("POST", f"/conventions/{convention_id}/waitlist", payload, headers)

    def list_convention_waitlist(self, convention_id, headers, params=None):
        return self._request("GET", f"/conventions/{convention_id}/waitlist", headers=headers, params=params)

    def list_waitlist_entries(self, headers, params=None):
        return self._request("GET", "/waitlist-entries", headers=headers, params=params)

    def get_waitlist_entry(self, entry_id, headers):
        return self._request("GET", f"/waitlist-entries/{entry_id}", headers=headers)

    # ─── Exhibitor ───────────────────────────────────────────────────────────
    def create_exhibitor(self, payload, headers):
        return self._request("POST", "/exhibitors", payload, headers)

    def get_exhibitor(self, exhibitor_id, headers):
        return self._request("GET", f"/exhibitors/{exhibitor_id}", headers=headers)

    def list_exhibitors(self, headers, params=None):
        return self._request("GET", "/exhibitors", headers=headers, params=params)

    # ─── Booth ───────────────────────────────────────────────────────────────
    def create_booth(self, convention_id, payload, headers):
        return self._request("POST", f"/conventions/{convention_id}/booths", payload, headers)

    def list_booths(self, convention_id, headers, params=None):
        return self._request("GET", f"/conventions/{convention_id}/booths", headers=headers, params=params)

    def get_booth(self, booth_id, headers):
        return self._request("GET", f"/booths/{booth_id}", headers=headers)

    # ─── BoothBooking ────────────────────────────────────────────────────────
    def create_booth_booking(self, payload, headers):
        return self._request("POST", "/booth-bookings", payload, headers)

    def get_booth_booking(self, booking_id, headers):
        return self._request("GET", f"/booth-bookings/{booking_id}", headers=headers)

    def list_booth_bookings(self, headers, params=None):
        return self._request("GET", "/booth-bookings", headers=headers, params=params)

    def check_in_booth_booking(self, booking_id, headers):
        return self._request("POST", f"/booth-bookings/{booking_id}/check-in", {}, headers)

    def release_booth_booking(self, booking_id, headers):
        return self._request("POST", f"/booth-bookings/{booking_id}/release", {}, headers)

    # ─── Test clock control (admin-only test-driving capability, §3.1) ───────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
