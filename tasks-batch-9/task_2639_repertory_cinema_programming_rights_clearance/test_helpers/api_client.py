"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed access to every endpoint of the repertory cinema service."""

    # ─── The auditorium ───────────────────────────────────────────────────

    def create_venue(self, payload, headers):
        return self._request("POST", "/venues", payload, headers)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/venues/{venue_id}", headers=headers)

    # ─── Distributors and licensors ───────────────────────────────────────

    def create_distributor(self, payload, headers):
        return self._request("POST", "/distributors", payload, headers)

    def get_distributor(self, distributor_id, headers):
        return self._request("GET", f"/distributors/{distributor_id}", headers=headers)

    # ─── The catalogue ────────────────────────────────────────────────────

    def create_title(self, payload, headers):
        return self._request("POST", "/titles", payload, headers)

    def get_title(self, title_id, headers):
        return self._request("GET", f"/titles/{title_id}", headers=headers)

    def list_titles(self, headers, params=None):
        return self._request("GET", "/titles", headers=headers, params=params)

    # ─── Engagements and their negotiation log ────────────────────────────

    def create_booking(self, payload, headers):
        return self._request("POST", "/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/bookings", headers=headers, params=params)

    def list_booking_offers(self, booking_id, headers, params=None):
        return self._request(
            "GET", f"/bookings/{booking_id}/offers", headers=headers, params=params
        )

    def counter_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/counter", payload, headers)

    def offer_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/offer", payload, headers)

    def confirm_booking(self, booking_id, headers, payload=None):
        return self._request(
            "POST", f"/bookings/{booking_id}/confirm", payload or {}, headers
        )

    def close_booking(self, booking_id, headers, payload=None):
        return self._request(
            "POST", f"/bookings/{booking_id}/close", payload or {}, headers
        )

    def withdraw_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/withdraw", payload, headers)

    # ─── Rights clearances ────────────────────────────────────────────────

    def create_clearance(self, payload, headers):
        return self._request("POST", "/clearances", payload, headers)

    def get_clearance(self, clearance_id, headers):
        return self._request("GET", f"/clearances/{clearance_id}", headers=headers)

    def list_clearances(self, headers, params=None):
        return self._request("GET", "/clearances", headers=headers, params=params)

    def submit_clearance(self, clearance_id, headers, payload=None):
        return self._request(
            "POST", f"/clearances/{clearance_id}/submit", payload or {}, headers
        )

    def clear_clearance(self, clearance_id, headers, payload=None):
        return self._request(
            "POST", f"/clearances/{clearance_id}/clear", payload or {}, headers
        )

    def request_clearance_changes(self, clearance_id, payload, headers):
        return self._request(
            "POST", f"/clearances/{clearance_id}/request-changes", payload, headers
        )

    def revoke_clearance(self, clearance_id, payload, headers):
        return self._request(
            "POST", f"/clearances/{clearance_id}/revoke", payload, headers
        )

    # ─── Print traffic and packages ───────────────────────────────────────

    def create_dcp_asset(self, payload, headers):
        return self._request("POST", "/dcp-assets", payload, headers)

    def get_dcp_asset(self, asset_id, headers):
        return self._request("GET", f"/dcp-assets/{asset_id}", headers=headers)

    def list_dcp_assets(self, headers, params=None):
        return self._request("GET", "/dcp-assets", headers=headers, params=params)

    def traffic_update_dcp_asset(self, asset_id, payload, headers):
        return self._request(
            "POST", f"/dcp-assets/{asset_id}/traffic-update", payload, headers
        )

    # ─── KDM keys ─────────────────────────────────────────────────────────

    def create_kdm_key(self, payload, headers):
        return self._request("POST", "/kdm-keys", payload, headers)

    def get_kdm_key(self, key_id, headers):
        return self._request("GET", f"/kdm-keys/{key_id}", headers=headers)

    def list_kdm_keys(self, headers, params=None):
        return self._request("GET", "/kdm-keys", headers=headers, params=params)

    def revoke_kdm_key(self, key_id, payload, headers):
        return self._request("POST", f"/kdm-keys/{key_id}/revoke", payload, headers)

    # ─── Screenings ───────────────────────────────────────────────────────

    def create_showtime(self, payload, headers):
        return self._request("POST", "/showtimes", payload, headers)

    def auto_schedule_showtime(self, payload, headers):
        return self._request("POST", "/showtimes/auto-schedule", payload, headers)

    def get_showtime(self, showtime_id, headers):
        return self._request("GET", f"/showtimes/{showtime_id}", headers=headers)

    def list_showtimes(self, headers, params=None):
        return self._request("GET", "/showtimes", headers=headers, params=params)

    def verify_playback(self, showtime_id, payload, headers):
        return self._request(
            "POST", f"/showtimes/{showtime_id}/verify-playback", payload, headers
        )

    def open_sales(self, showtime_id, headers, payload=None):
        return self._request(
            "POST", f"/showtimes/{showtime_id}/open-sales", payload or {}, headers
        )

    def close_sales(self, showtime_id, headers, payload=None):
        return self._request(
            "POST", f"/showtimes/{showtime_id}/close-sales", payload or {}, headers
        )

    def cancel_showtime(self, showtime_id, payload, headers):
        return self._request(
            "POST", f"/showtimes/{showtime_id}/cancel", payload, headers
        )

    def complete_showtime(self, showtime_id, headers, payload=None):
        return self._request(
            "POST", f"/showtimes/{showtime_id}/complete", payload or {}, headers
        )

    # ─── Special events ───────────────────────────────────────────────────

    def create_special_event(self, payload, headers):
        return self._request("POST", "/special-events", payload, headers)

    def get_special_event(self, event_id, headers):
        return self._request("GET", f"/special-events/{event_id}", headers=headers)

    def list_special_events(self, headers, params=None):
        return self._request("GET", "/special-events", headers=headers, params=params)

    def confirm_special_event(self, event_id, payload, headers):
        return self._request(
            "POST", f"/special-events/{event_id}/confirm", payload, headers
        )

    def cancel_special_event(self, event_id, payload, headers):
        return self._request(
            "POST", f"/special-events/{event_id}/cancel", payload, headers
        )

    # ─── Box office ───────────────────────────────────────────────────────

    def create_ticket_order(self, payload, headers):
        return self._request("POST", "/ticket-orders", payload, headers)

    def get_ticket_order(self, order_id, headers):
        return self._request("GET", f"/ticket-orders/{order_id}", headers=headers)

    def list_ticket_orders(self, headers, params=None):
        return self._request("GET", "/ticket-orders", headers=headers, params=params)

    def pay_ticket_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"/ticket-orders/{order_id}/pay", payload or {}, headers
        )

    def refund_ticket_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/ticket-orders/{order_id}/refund", payload, headers
        )

    # ─── Membership ───────────────────────────────────────────────────────

    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def create_donation(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/donations", payload, headers)

    def run_membership_sweep(self, headers, payload=None):
        return self._request("POST", "/membership-sweeps", payload or {}, headers)

    # ─── Settlement ───────────────────────────────────────────────────────

    def create_settlement(self, payload, headers):
        return self._request("POST", "/settlements", payload, headers)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/settlements/{settlement_id}", headers=headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", "/settlements", headers=headers, params=params)

    def submit_settlement(self, settlement_id, headers, payload=None):
        return self._request(
            "POST", f"/settlements/{settlement_id}/submit", payload or {}, headers
        )

    def finalize_settlement(self, settlement_id, headers, payload=None):
        return self._request(
            "POST", f"/settlements/{settlement_id}/finalize", payload or {}, headers
        )

    def resolve_settlement(self, settlement_id, payload, headers):
        return self._request(
            "POST", f"/settlements/{settlement_id}/resolve", payload, headers
        )

    # ─── The logical clock ────────────────────────────────────────────────

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
