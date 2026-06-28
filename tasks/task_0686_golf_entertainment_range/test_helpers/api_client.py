"""API client: one method per endpoint defined in the PRD.

The API is mounted under the /golf prefix (PRD §2), so every path below
carries that prefix explicitly. The base _request() method is inherited from
the framework's GenericApiClient.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock (test-driving, PRD §2.9) ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/golf/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ---- Venue ----
    def create_venue(self, payload, headers):
        return self._request("POST", "/golf/venues", payload, headers)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/golf/venues/{venue_id}", headers=headers)

    def list_venues(self, headers, params=None):
        return self._request("GET", "/golf/venues", headers=headers, params=params)

    def seat_next(self, venue_id, payload, headers):
        return self._request(
            "POST", f"/golf/venues/{venue_id}/seat_next", payload, headers)

    def sweep_holds(self, venue_id, headers):
        return self._request(
            "POST", f"/golf/venues/{venue_id}/sweep_holds", {}, headers)

    # ---- Bay ----
    def create_bay(self, payload, headers):
        return self._request("POST", "/golf/bays", payload, headers)

    def get_bay(self, bay_id, headers):
        return self._request("GET", f"/golf/bays/{bay_id}", headers=headers)

    def list_bays(self, headers, params=None):
        return self._request("GET", "/golf/bays", headers=headers, params=params)

    def bay_out_of_service(self, bay_id, payload, headers):
        return self._request(
            "POST", f"/golf/bays/{bay_id}/out_of_service", payload, headers)

    # ---- Member ----
    def create_member(self, payload, headers):
        return self._request("POST", "/golf/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/golf/members/{member_id}", headers=headers)

    def wallet_topup(self, member_id, payload, headers):
        return self._request(
            "POST", f"/golf/members/{member_id}/wallet/topup", payload, headers)

    # ---- GameCard ----
    def create_game_card(self, payload, headers):
        return self._request("POST", "/golf/game-cards", payload, headers)

    def get_game_card(self, card_id, headers):
        return self._request("GET", f"/golf/game-cards/{card_id}", headers=headers)

    def list_game_cards(self, headers, params=None):
        return self._request("GET", "/golf/game-cards", headers=headers, params=params)

    # ---- GiftCard ----
    def create_gift_card(self, payload, headers):
        return self._request("POST", "/golf/gift-cards", payload, headers)

    def get_gift_card(self, gift_card_id, headers):
        return self._request("GET", f"/golf/gift-cards/{gift_card_id}", headers=headers)

    def redeem_gift_card(self, gift_card_id, payload, headers):
        return self._request(
            "POST", f"/golf/gift-cards/{gift_card_id}/redeem", payload, headers)

    # ---- Reservation ----
    def create_reservation(self, payload, headers):
        return self._request("POST", "/golf/reservations", payload, headers)

    def get_reservation(self, reservation_id, headers):
        return self._request(
            "GET", f"/golf/reservations/{reservation_id}", headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request(
            "GET", "/golf/reservations", headers=headers, params=params)

    def confirm_reservation(self, reservation_id, payload, headers):
        return self._request(
            "POST", f"/golf/reservations/{reservation_id}/confirm", payload, headers)

    def cancel_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/golf/reservations/{reservation_id}/cancel", {}, headers)

    # ---- GameSession ----
    def create_session(self, payload, headers):
        return self._request("POST", "/golf/sessions", payload, headers)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/golf/sessions/{session_id}", headers=headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/golf/sessions", headers=headers, params=params)

    def record_shot(self, session_id, payload, headers):
        return self._request(
            "POST", f"/golf/sessions/{session_id}/shots", payload, headers)

    def end_session(self, session_id, headers):
        return self._request(
            "POST", f"/golf/sessions/{session_id}/end", {}, headers)

    def settle_session(self, session_id, payload, headers):
        return self._request(
            "POST", f"/golf/sessions/{session_id}/settle", payload, headers)

    def void_session(self, session_id, headers):
        return self._request(
            "POST", f"/golf/sessions/{session_id}/void", {}, headers)

    # ---- EventPackage ----
    def create_event_package(self, payload, headers):
        return self._request("POST", "/golf/event-packages", payload, headers)

    def get_event_package(self, event_package_id, headers):
        return self._request(
            "GET", f"/golf/event-packages/{event_package_id}", headers=headers)

    def list_event_packages(self, headers, params=None):
        return self._request(
            "GET", "/golf/event-packages", headers=headers, params=params)

    def revise_event_package(self, event_package_id, payload, headers):
        return self._request(
            "PATCH", f"/golf/event-packages/{event_package_id}", payload, headers)

    def negotiate_event_package(self, event_package_id, headers):
        return self._request(
            "POST", f"/golf/event-packages/{event_package_id}/negotiate", {}, headers)

    def confirm_event_package(self, event_package_id, headers):
        return self._request(
            "POST", f"/golf/event-packages/{event_package_id}/confirm", {}, headers)

    def settle_event_package(self, event_package_id, payload, headers):
        return self._request(
            "POST", f"/golf/event-packages/{event_package_id}/settle", payload, headers)

    def cancel_event_package(self, event_package_id, headers):
        return self._request(
            "POST", f"/golf/event-packages/{event_package_id}/cancel", {}, headers)

    # ---- FBTab ----
    def create_fb_tab(self, payload, headers):
        return self._request("POST", "/golf/fb-tabs", payload, headers)

    def get_fb_tab(self, fb_tab_id, headers):
        return self._request("GET", f"/golf/fb-tabs/{fb_tab_id}", headers=headers)

    def list_fb_tabs(self, headers, params=None):
        return self._request("GET", "/golf/fb-tabs", headers=headers, params=params)

    def add_fb_item(self, fb_tab_id, payload, headers):
        return self._request(
            "POST", f"/golf/fb-tabs/{fb_tab_id}/items", payload, headers)

    def close_fb_tab(self, fb_tab_id, headers):
        return self._request(
            "POST", f"/golf/fb-tabs/{fb_tab_id}/close", {}, headers)

    # ---- QueueTicket ----
    def create_queue_ticket(self, payload, headers):
        return self._request("POST", "/golf/queue-tickets", payload, headers)

    def get_queue_ticket(self, queue_ticket_id, headers):
        return self._request(
            "GET", f"/golf/queue-tickets/{queue_ticket_id}", headers=headers)

    def list_queue_tickets(self, headers, params=None):
        return self._request(
            "GET", "/golf/queue-tickets", headers=headers, params=params)

    def cancel_queue_ticket(self, queue_ticket_id, headers):
        return self._request(
            "POST", f"/golf/queue-tickets/{queue_ticket_id}/cancel", {}, headers)

    # ---- Lesson ----
    def create_lesson(self, payload, headers):
        return self._request("POST", "/golf/lessons", payload, headers)

    def get_lesson(self, lesson_id, headers):
        return self._request("GET", f"/golf/lessons/{lesson_id}", headers=headers)

    def list_lessons(self, headers, params=None):
        return self._request("GET", "/golf/lessons", headers=headers, params=params)

    def complete_lesson(self, lesson_id, headers):
        return self._request(
            "POST", f"/golf/lessons/{lesson_id}/complete", {}, headers)

    def cancel_lesson(self, lesson_id, headers):
        return self._request(
            "POST", f"/golf/lessons/{lesson_id}/cancel", {}, headers)

    # ---- Charge (read) ----
    def get_charge(self, charge_id, headers):
        return self._request("GET", f"/golf/charges/{charge_id}", headers=headers)

    def list_charges(self, headers, params=None):
        return self._request("GET", "/golf/charges", headers=headers, params=params)


api_client = ApiClient()
