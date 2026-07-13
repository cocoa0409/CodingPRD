"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # --- Attractions ---
    def create_attraction(self, payload, headers):
        return self._request("POST", "/attractions", payload, headers)

    def update_attraction(self, attraction_id, payload, headers):
        return self._request("PATCH", f"/attractions/{attraction_id}", payload, headers)

    def get_attraction(self, attraction_id, headers):
        return self._request("GET", f"/attractions/{attraction_id}", headers=headers)

    # --- Prize items ---
    def create_prize_item(self, payload, headers):
        return self._request("POST", "/prize-items", payload, headers)

    def update_prize_item(self, prize_id, payload, headers):
        return self._request("PATCH", f"/prize-items/{prize_id}", payload, headers)

    def get_prize_item(self, prize_id, headers):
        return self._request("GET", f"/prize-items/{prize_id}", headers=headers)

    # --- Party packages ---
    def create_party_package(self, payload, headers):
        return self._request("POST", "/party-packages", payload, headers)

    # --- Rooms ---
    def create_room(self, payload, headers):
        return self._request("POST", "/rooms", payload, headers)

    def update_room(self, room_id, payload, headers):
        return self._request("PATCH", f"/rooms/{room_id}", payload, headers)

    def get_room(self, room_id, headers):
        return self._request("GET", f"/rooms/{room_id}", headers=headers)

    # --- Members ---
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    # --- Game cards ---
    def create_game_card(self, payload, headers):
        return self._request("POST", "/game-cards", payload, headers)

    def get_game_card(self, card_id, headers):
        return self._request("GET", f"/game-cards/{card_id}", headers=headers)

    def list_game_cards(self, headers, params=None):
        return self._request("GET", "/game-cards", headers=headers, params=params)

    def activate_game_card(self, card_id, headers):
        return self._request("POST", f"/game-cards/{card_id}/activate", {}, headers)

    def reload_game_card(self, card_id, payload, headers):
        return self._request("POST", f"/game-cards/{card_id}/reload", payload, headers)

    def freeze_game_card(self, card_id, headers):
        return self._request("POST", f"/game-cards/{card_id}/freeze", {}, headers)

    def close_game_card(self, card_id, headers):
        return self._request("POST", f"/game-cards/{card_id}/close", {}, headers)

    def get_card_ledger(self, card_id, headers, params=None):
        return self._request("GET", f"/game-cards/{card_id}/ledger", headers=headers, params=params)

    # --- Game plays ---
    def create_game_play(self, payload, headers):
        return self._request("POST", "/game-plays", payload, headers)

    def get_game_play(self, play_id, headers):
        return self._request("GET", f"/game-plays/{play_id}", headers=headers)

    def list_game_plays(self, headers, params=None):
        return self._request("GET", "/game-plays", headers=headers, params=params)

    # --- Redemptions ---
    def create_redemption(self, payload, headers):
        return self._request("POST", "/redemptions", payload, headers)

    def get_redemption(self, redemption_id, headers):
        return self._request("GET", f"/redemptions/{redemption_id}", headers=headers)

    def list_redemptions(self, headers, params=None):
        return self._request("GET", "/redemptions", headers=headers, params=params)

    def fulfill_redemption(self, redemption_id, headers):
        return self._request("POST", f"/redemptions/{redemption_id}/fulfill", {}, headers)

    def cancel_redemption(self, redemption_id, headers):
        return self._request("POST", f"/redemptions/{redemption_id}/cancel", {}, headers)

    # --- Party bookings ---
    def create_party_booking(self, payload, headers):
        return self._request("POST", "/party-bookings", payload, headers)

    def get_party_booking(self, booking_id, headers):
        return self._request("GET", f"/party-bookings/{booking_id}", headers=headers)

    def list_party_bookings(self, headers, params=None):
        return self._request("GET", "/party-bookings", headers=headers, params=params)

    def confirm_party_booking(self, booking_id, headers):
        return self._request("POST", f"/party-bookings/{booking_id}/confirm", {}, headers)

    def revert_party_booking(self, booking_id, headers):
        return self._request("POST", f"/party-bookings/{booking_id}/revert-to-draft", {}, headers)

    def check_in_party_booking(self, booking_id, headers):
        return self._request("POST", f"/party-bookings/{booking_id}/check-in", {}, headers)

    def complete_party_booking(self, booking_id, headers):
        return self._request("POST", f"/party-bookings/{booking_id}/complete", {}, headers)

    def cancel_party_booking(self, booking_id, headers):
        return self._request("POST", f"/party-bookings/{booking_id}/cancel", {}, headers)

    def issue_wristband(self, booking_id, payload, headers):
        return self._request("POST", f"/party-bookings/{booking_id}/wristbands", payload, headers)

    # --- Wristbands ---
    def get_wristband(self, wristband_id, headers):
        return self._request("GET", f"/wristbands/{wristband_id}", headers=headers)

    def list_wristbands(self, headers, params=None):
        return self._request("GET", "/wristbands", headers=headers, params=params)

    def return_wristband(self, wristband_id, headers):
        return self._request("POST", f"/wristbands/{wristband_id}/return", {}, headers)

    # --- Daily reconciliation ---
    def create_reconciliation(self, payload, headers):
        return self._request("POST", "/daily-reconciliations", payload, headers)

    def get_reconciliation(self, reconciliation_id, headers):
        return self._request("GET", f"/daily-reconciliations/{reconciliation_id}", headers=headers)

    def count_reconciliation(self, reconciliation_id, payload, headers):
        return self._request("POST", f"/daily-reconciliations/{reconciliation_id}/count", payload, headers)


api_client = ApiClient()
