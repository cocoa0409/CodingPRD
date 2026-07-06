"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ---- Venue ----
    def create_venue(self, payload, headers):
        return self._request("POST", "/venues", payload, headers)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/venues/{venue_id}", headers=headers)

    def close_venue(self, venue_id, headers):
        return self._request("POST", f"/venues/{venue_id}/close", {}, headers)

    # ---- Show ----
    def create_show(self, venue_id, payload, headers):
        return self._request("POST", f"/venues/{venue_id}/shows", payload, headers)

    def get_show(self, show_id, headers):
        return self._request("GET", f"/shows/{show_id}", headers=headers)

    def list_shows(self, headers, params=None):
        return self._request("GET", "/shows", headers=headers, params=params)

    def publish_show(self, venue_id, show_id, headers):
        return self._request(
            "POST", f"/venues/{venue_id}/shows/{show_id}/publish", {}, headers,
        )

    def cancel_show(self, venue_id, show_id, headers):
        return self._request(
            "POST", f"/venues/{venue_id}/shows/{show_id}/cancel", {}, headers,
        )

    # ---- Sections ----
    def create_section(self, venue_id, show_id, payload, headers):
        return self._request(
            "POST", f"/venues/{venue_id}/shows/{show_id}/sections", payload, headers,
        )

    def get_section(self, section_id, headers):
        return self._request("GET", f"/sections/{section_id}", headers=headers)

    def list_sections(self, headers, params=None):
        return self._request("GET", "/sections", headers=headers, params=params)

    # ---- Tables ----
    def create_table(self, venue_id, show_id, section_id, payload, headers):
        return self._request(
            "POST",
            f"/venues/{venue_id}/shows/{show_id}/sections/{section_id}/tables",
            payload, headers,
        )

    def get_table(self, table_id, headers):
        return self._request("GET", f"/tables/{table_id}", headers=headers)

    def list_tables(self, headers, params=None):
        return self._request("GET", "/tables", headers=headers, params=params)

    def assign_server(self, table_id, payload, headers):
        return self._request(
            "POST", f"/tables/{table_id}/assign-server", payload, headers,
        )

    def retire_table(self, table_id, headers):
        return self._request("POST", f"/tables/{table_id}/retire", {}, headers)

    # ---- Ticket tiers ----
    def create_tier(self, venue_id, show_id, payload, headers):
        return self._request(
            "POST", f"/venues/{venue_id}/shows/{show_id}/tiers", payload, headers,
        )

    def get_tier(self, tier_id, headers):
        return self._request("GET", f"/tiers/{tier_id}", headers=headers)

    def list_tiers(self, headers, params=None):
        return self._request("GET", "/tiers", headers=headers, params=params)

    # ---- Performers ----
    def create_performer(self, payload, headers):
        return self._request("POST", "/performers", payload, headers)

    def get_performer(self, performer_id, headers):
        return self._request("GET", f"/performers/{performer_id}", headers=headers)

    # ---- Lineup slots / contracts ----
    def create_lineup_slot(self, payload, headers):
        return self._request("POST", "/lineup-slots", payload, headers)

    def get_lineup_slot(self, lineup_slot_id, headers):
        return self._request(
            "GET", f"/lineup-slots/{lineup_slot_id}", headers=headers,
        )

    def list_lineup_slots(self, headers, params=None):
        return self._request("GET", "/lineup-slots", headers=headers, params=params)

    def counter_lineup_slot(self, lineup_slot_id, payload, headers):
        return self._request(
            "POST", f"/lineup-slots/{lineup_slot_id}/counter", payload, headers,
        )

    def revise_offer(self, lineup_slot_id, payload, headers):
        return self._request(
            "POST", f"/lineup-slots/{lineup_slot_id}/revise-offer", payload, headers,
        )

    def sign_lineup_slot(self, lineup_slot_id, payload, headers):
        return self._request(
            "POST", f"/lineup-slots/{lineup_slot_id}/sign", payload, headers,
        )

    def drop_lineup_slot(self, lineup_slot_id, headers):
        return self._request(
            "POST", f"/lineup-slots/{lineup_slot_id}/drop", {}, headers,
        )

    # ---- Reservations ----
    def create_reservation(self, payload, headers):
        return self._request("POST", "/reservations", payload, headers)

    def get_reservation(self, reservation_id, headers):
        return self._request(
            "GET", f"/reservations/{reservation_id}", headers=headers,
        )

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/reservations", headers=headers, params=params)

    def collect_ticket(self, reservation_id, headers):
        return self._request(
            "POST", f"/reservations/{reservation_id}/collect-ticket", {}, headers,
        )

    def assign_table(self, reservation_id, payload, headers):
        return self._request(
            "POST", f"/reservations/{reservation_id}/assign-table", payload, headers,
        )

    def seat_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/reservations/{reservation_id}/seat", {}, headers,
        )

    def check_in(self, reservation_id, headers):
        return self._request(
            "POST", f"/reservations/{reservation_id}/check-in", {}, headers,
        )

    def record_consumption(self, reservation_id, payload, headers):
        return self._request(
            "POST", f"/reservations/{reservation_id}/record-consumption",
            payload, headers,
        )

    def cancel_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/reservations/{reservation_id}/cancel", {}, headers,
        )

    def exchange_reservation(self, reservation_id, payload, headers):
        return self._request(
            "POST", f"/reservations/{reservation_id}/exchange", payload, headers,
        )

    def no_show(self, reservation_id, headers):
        return self._request(
            "POST", f"/reservations/{reservation_id}/no-show", {}, headers,
        )

    # ---- Tickets ----
    def get_ticket(self, ticket_id, headers):
        return self._request("GET", f"/tickets/{ticket_id}", headers=headers)

    def list_tickets(self, headers, params=None):
        return self._request("GET", "/tickets", headers=headers, params=params)

    # ---- Guest list ----
    def create_guest_list_entry(self, payload, headers):
        return self._request("POST", "/guest-list-entries", payload, headers)

    def get_guest_list_entry(self, guest_list_entry_id, headers):
        return self._request(
            "GET", f"/guest-list-entries/{guest_list_entry_id}", headers=headers,
        )

    def list_guest_list_entries(self, headers, params=None):
        return self._request(
            "GET", "/guest-list-entries", headers=headers, params=params,
        )

    def convert_guest_list_entry(self, guest_list_entry_id, payload, headers):
        return self._request(
            "POST", f"/guest-list-entries/{guest_list_entry_id}/convert",
            payload, headers,
        )

    def revoke_guest_list_entry(self, guest_list_entry_id, headers):
        return self._request(
            "POST", f"/guest-list-entries/{guest_list_entry_id}/revoke", {}, headers,
        )

    # ---- Servers ----
    def create_server(self, payload, headers):
        return self._request("POST", "/servers", payload, headers)

    def get_server(self, server_id, headers):
        return self._request("GET", f"/servers/{server_id}", headers=headers)

    # ---- Private events ----
    def create_private_event(self, payload, headers):
        return self._request("POST", "/private-events", payload, headers)

    def get_private_event(self, private_event_id, headers):
        return self._request(
            "GET", f"/private-events/{private_event_id}", headers=headers,
        )

    def list_private_events(self, headers, params=None):
        return self._request(
            "GET", "/private-events", headers=headers, params=params,
        )

    def confirm_private_event(self, private_event_id, headers):
        return self._request(
            "POST", f"/private-events/{private_event_id}/confirm", {}, headers,
        )

    def cancel_private_event(self, private_event_id, headers):
        return self._request(
            "POST", f"/private-events/{private_event_id}/cancel", {}, headers,
        )

    # ---- Settlements ----
    def create_settlement(self, payload, headers):
        return self._request("POST", "/settlements", payload, headers)

    def get_settlement(self, settlement_id, headers):
        return self._request(
            "GET", f"/settlements/{settlement_id}", headers=headers,
        )

    def list_settlements(self, headers, params=None):
        return self._request("GET", "/settlements", headers=headers, params=params)

    def finalize_settlement(self, settlement_id, headers):
        return self._request(
            "POST", f"/settlements/{settlement_id}/finalize", {}, headers,
        )


api_client = ApiClient()
