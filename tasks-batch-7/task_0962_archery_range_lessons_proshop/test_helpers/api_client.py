"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- Members ----
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def add_safety_strike(self, member_id, payload, headers):
        return self._request(
            "POST", f"/members/{member_id}/safety-strikes", payload, headers
        )

    def reinstate_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/reinstate", {}, headers)

    def adjust_wallet(self, member_id, payload, headers):
        return self._request(
            "POST", f"/members/{member_id}/wallet/adjustments", payload, headers
        )

    # ---- Waivers ----
    def sign_waiver(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/waivers", {}, headers)

    def list_waivers(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/members/{member_id}/waivers", headers=headers, params=params
        )

    def revoke_waiver(self, waiver_id, headers):
        return self._request("POST", f"/waivers/{waiver_id}/revoke", {}, headers)

    # ---- Lanes ----
    def create_lane(self, payload, headers):
        return self._request("POST", "/lanes", payload, headers)

    def list_lanes(self, headers, params=None):
        return self._request("GET", "/lanes", headers=headers, params=params)

    def get_lane(self, lane_id, headers):
        return self._request("GET", f"/lanes/{lane_id}", headers=headers)

    def list_lane_sessions(self, lane_id, headers, params=None):
        return self._request(
            "GET", f"/lanes/{lane_id}/sessions", headers=headers, params=params
        )

    # ---- Range sessions & participants ----
    def create_range_session(self, payload, headers):
        return self._request("POST", "/range-sessions", payload, headers)

    def list_range_sessions(self, headers, params=None):
        return self._request("GET", "/range-sessions", headers=headers, params=params)

    def get_range_session(self, session_id, headers):
        return self._request("GET", f"/range-sessions/{session_id}", headers=headers)

    def add_participant(self, session_id, payload, headers):
        return self._request(
            "POST", f"/range-sessions/{session_id}/participants", payload, headers
        )

    def list_participants(self, headers, params=None):
        return self._request(
            "GET", "/session-participants", headers=headers, params=params
        )

    def get_participant(self, participant_id, headers):
        return self._request(
            "GET", f"/session-participants/{participant_id}", headers=headers
        )

    def check_in_session(self, session_id, headers):
        return self._request(
            "POST", f"/range-sessions/{session_id}/check-in", {}, headers
        )

    def close_session(self, session_id, headers):
        return self._request("POST", f"/range-sessions/{session_id}/close", {}, headers)

    def cancel_session(self, session_id, headers):
        return self._request(
            "POST", f"/range-sessions/{session_id}/cancel", {}, headers
        )

    # ---- Punch cards ----
    def purchase_punch_card(self, member_id, payload, headers):
        return self._request(
            "POST", f"/members/{member_id}/punch-cards", payload, headers
        )

    def list_punch_cards(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/members/{member_id}/punch-cards", headers=headers, params=params
        )

    def get_punch_card(self, punch_card_id, headers):
        return self._request("GET", f"/punch-cards/{punch_card_id}", headers=headers)

    # ---- Rental items & agreements ----
    def create_rental_item(self, payload, headers):
        return self._request("POST", "/rental-items", payload, headers)

    def list_rental_items(self, headers, params=None):
        return self._request("GET", "/rental-items", headers=headers, params=params)

    def create_rental_agreement(self, payload, headers):
        return self._request("POST", "/rental-agreements", payload, headers)

    def list_rental_agreements(self, headers, params=None):
        return self._request("GET", "/rental-agreements", headers=headers, params=params)

    def get_rental_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"/rental-agreements/{agreement_id}", headers=headers
        )

    def return_rental_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/rental-agreements/{agreement_id}/return", payload, headers
        )

    def settle_rental_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/rental-agreements/{agreement_id}/settle", {}, headers
        )

    # ---- Coaches ----
    def create_coach(self, payload, headers):
        return self._request("POST", "/coaches", payload, headers)

    def list_coaches(self, headers, params=None):
        return self._request("GET", "/coaches", headers=headers, params=params)

    def deactivate_coach(self, coach_id, headers):
        return self._request("POST", f"/coaches/{coach_id}/deactivate", {}, headers)

    def activate_coach(self, coach_id, headers):
        return self._request("POST", f"/coaches/{coach_id}/activate", {}, headers)

    # ---- Lessons ----
    def create_lesson(self, payload, headers):
        return self._request("POST", "/lessons", payload, headers)

    def list_lessons(self, headers, params=None):
        return self._request("GET", "/lessons", headers=headers, params=params)

    def get_lesson(self, lesson_id, headers):
        return self._request("GET", f"/lessons/{lesson_id}", headers=headers)

    def confirm_lesson(self, lesson_id, headers):
        return self._request("POST", f"/lessons/{lesson_id}/confirm", {}, headers)

    def counter_lesson(self, lesson_id, payload, headers):
        return self._request("POST", f"/lessons/{lesson_id}/counter", payload, headers)

    def accept_lesson(self, lesson_id, headers):
        return self._request("POST", f"/lessons/{lesson_id}/accept", {}, headers)

    def cancel_lesson(self, lesson_id, headers):
        return self._request("POST", f"/lessons/{lesson_id}/cancel", {}, headers)

    def complete_lesson(self, lesson_id, headers):
        return self._request("POST", f"/lessons/{lesson_id}/complete", {}, headers)

    # ---- Leagues, entries, scorecards ----
    def create_league(self, payload, headers):
        return self._request("POST", "/leagues", payload, headers)

    def get_league(self, league_id, headers):
        return self._request("GET", f"/leagues/{league_id}", headers=headers)

    def enter_league(self, league_id, headers):
        return self._request("POST", f"/leagues/{league_id}/entries", {}, headers)

    def list_league_entries(self, headers, params=None):
        return self._request("GET", "/league-entries", headers=headers, params=params)

    def get_league_entry(self, entry_id, headers):
        return self._request("GET", f"/league-entries/{entry_id}", headers=headers)

    def close_league(self, league_id, headers):
        return self._request("POST", f"/leagues/{league_id}/close", {}, headers)

    def cancel_league(self, league_id, headers):
        return self._request("POST", f"/leagues/{league_id}/cancel", {}, headers)

    def get_standings(self, league_id, headers, params=None):
        return self._request(
            "GET", f"/leagues/{league_id}/standings", headers=headers, params=params
        )

    def submit_scorecard(self, entry_id, payload, headers):
        return self._request(
            "POST", f"/league-entries/{entry_id}/scorecards", payload, headers
        )

    def list_scorecards(self, entry_id, headers, params=None):
        return self._request(
            "GET", f"/league-entries/{entry_id}/scorecards", headers=headers,
            params=params,
        )

    def update_scorecard(self, scorecard_id, payload, headers):
        return self._request("PUT", f"/scorecards/{scorecard_id}", payload, headers)

    def verify_scorecard(self, scorecard_id, headers):
        return self._request("POST", f"/scorecards/{scorecard_id}/verify", {}, headers)

    def dispute_scorecard(self, scorecard_id, headers):
        return self._request("POST", f"/scorecards/{scorecard_id}/dispute", {}, headers)

    def lock_scorecard(self, scorecard_id, headers):
        return self._request("POST", f"/scorecards/{scorecard_id}/lock", {}, headers)

    # ---- Pro-shop products & sales ----
    def create_shop_product(self, payload, headers):
        return self._request("POST", "/shop-products", payload, headers)

    def list_shop_products(self, headers, params=None):
        return self._request("GET", "/shop-products", headers=headers, params=params)

    def create_sale(self, payload, headers):
        return self._request("POST", "/sales", payload, headers)

    def list_sales(self, headers, params=None):
        return self._request("GET", "/sales", headers=headers, params=params)

    def get_sale(self, sale_id, headers):
        return self._request("GET", f"/sales/{sale_id}", headers=headers)

    # ---- Repair orders ----
    def create_repair_order(self, payload, headers):
        return self._request("POST", "/repair-orders", payload, headers)

    def list_repair_orders(self, headers, params=None):
        return self._request("GET", "/repair-orders", headers=headers, params=params)

    def get_repair_order(self, order_id, headers):
        return self._request("GET", f"/repair-orders/{order_id}", headers=headers)

    def quote_repair_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/repair-orders/{order_id}/quote", payload, headers
        )

    def approve_repair_order(self, order_id, headers):
        return self._request("POST", f"/repair-orders/{order_id}/approve", {}, headers)

    def decline_repair_order(self, order_id, headers):
        return self._request("POST", f"/repair-orders/{order_id}/decline", {}, headers)

    def complete_repair_order(self, order_id, headers):
        return self._request("POST", f"/repair-orders/{order_id}/complete", {}, headers)

    def pickup_repair_order(self, order_id, headers):
        return self._request("POST", f"/repair-orders/{order_id}/pickup", {}, headers)


api_client = ApiClient()
