"""API client: one method per endpoint defined in the PRD (Section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Venue ──────────────────────────────────────────
    def create_venue(self, payload, headers):
        return self._request("POST", "/venues", payload, headers)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/venues/{venue_id}", headers=headers)

    # ─── Room ───────────────────────────────────────────
    def create_room(self, payload, headers):
        return self._request("POST", "/rooms", payload, headers)

    def get_room(self, room_id, headers):
        return self._request("GET", f"/rooms/{room_id}", headers=headers)

    def list_rooms(self, headers, params=None):
        return self._request("GET", "/rooms", headers=headers, params=params)

    def retire_room(self, room_id, payload, headers):
        return self._request("POST", f"/rooms/{room_id}/retire", payload, headers)

    # ─── PricingRule ────────────────────────────────────
    def create_pricing_rule(self, payload, headers):
        return self._request("POST", "/pricing-rules", payload, headers)

    def get_pricing_rule(self, pricing_rule_id, headers):
        return self._request("GET", f"/pricing-rules/{pricing_rule_id}", headers=headers)

    def list_pricing_rules(self, headers, params=None):
        return self._request("GET", "/pricing-rules", headers=headers, params=params)

    # ─── GameMaster ─────────────────────────────────────
    def create_game_master(self, payload, headers):
        return self._request("POST", "/game-masters", payload, headers)

    def get_game_master(self, game_master_id, headers):
        return self._request("GET", f"/game-masters/{game_master_id}", headers=headers)

    def list_game_masters(self, headers, params=None):
        return self._request("GET", "/game-masters", headers=headers, params=params)

    def set_game_master_status(self, game_master_id, payload, headers):
        return self._request("POST", f"/game-masters/{game_master_id}/set-status", payload, headers)

    # ─── TimeSlot ───────────────────────────────────────
    def create_time_slot(self, payload, headers):
        return self._request("POST", "/time-slots", payload, headers)

    def get_time_slot(self, slot_id, headers):
        return self._request("GET", f"/time-slots/{slot_id}", headers=headers)

    def list_time_slots(self, headers, params=None):
        return self._request("GET", "/time-slots", headers=headers, params=params)

    def block_time_slot(self, slot_id, payload, headers):
        return self._request("POST", f"/time-slots/{slot_id}/block", payload, headers)

    def unblock_time_slot(self, slot_id, payload, headers):
        return self._request("POST", f"/time-slots/{slot_id}/unblock", payload, headers)

    def close_time_slot(self, slot_id, payload, headers):
        return self._request("POST", f"/time-slots/{slot_id}/close", payload, headers)

    # ─── Customer ───────────────────────────────────────
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # ─── Booking ────────────────────────────────────────
    def create_booking(self, payload, headers):
        return self._request("POST", "/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/bookings", headers=headers, params=params)

    def add_participant(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/participants", payload, headers)

    def confirm_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/confirm", payload, headers)

    def reschedule_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/reschedule", payload, headers)

    def check_in_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/check-in", payload, headers)

    def complete_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/complete", payload, headers)

    def no_show_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/no-show", payload, headers)

    def cancel_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/cancel", payload, headers)

    # ─── Participant ────────────────────────────────────
    def get_participant(self, participant_id, headers):
        return self._request("GET", f"/participants/{participant_id}", headers=headers)

    def list_participants(self, headers, params=None):
        return self._request("GET", "/participants", headers=headers, params=params)

    def sign_waiver(self, participant_id, payload, headers):
        return self._request("POST", f"/participants/{participant_id}/sign-waiver", payload, headers)

    def revoke_waiver(self, participant_id, payload, headers):
        return self._request("POST", f"/participants/{participant_id}/revoke-waiver", payload, headers)

    def mark_present(self, participant_id, payload, headers):
        return self._request("POST", f"/participants/{participant_id}/mark-present", payload, headers)

    # ─── GiftCard ───────────────────────────────────────
    def create_gift_card(self, payload, headers):
        return self._request("POST", "/gift-cards", payload, headers)

    def get_gift_card(self, gift_card_id, headers):
        return self._request("GET", f"/gift-cards/{gift_card_id}", headers=headers)

    def list_gift_cards(self, headers, params=None):
        return self._request("GET", "/gift-cards", headers=headers, params=params)

    def top_up_gift_card(self, gift_card_id, payload, headers):
        return self._request("POST", f"/gift-cards/{gift_card_id}/top-up", payload, headers)

    def void_gift_card(self, gift_card_id, payload, headers):
        return self._request("POST", f"/gift-cards/{gift_card_id}/void", payload, headers)

    # ─── GiftCardEntry (append-only ledger) ─────────────
    def get_gift_card_entry(self, entry_id, headers):
        return self._request("GET", f"/gift-card-entries/{entry_id}", headers=headers)

    def list_gift_card_entries(self, headers, params=None):
        return self._request("GET", "/gift-card-entries", headers=headers, params=params)


api_client = ApiClient()
