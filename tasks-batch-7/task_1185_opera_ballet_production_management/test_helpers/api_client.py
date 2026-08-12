"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock (PRD §2.5) ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- partner companies (PRD §3.1) ---
    def create_partner_company(self, payload, headers):
        return self._request("POST", "/opera/partner-companies", payload, headers)

    def list_partner_companies(self, headers, params=None):
        return self._request("GET", "/opera/partner-companies", headers=headers, params=params)

    def get_partner_company(self, company_id, headers):
        return self._request("GET", f"/opera/partner-companies/{company_id}", headers=headers)

    def transition_partner_company(self, company_id, to_state, headers):
        return self._request(
            "POST", f"/opera/partner-companies/{company_id}/transition",
            {"to_state": to_state}, headers,
        )

    # --- productions (PRD §3.2) ---
    def create_production(self, payload, headers):
        return self._request("POST", "/opera/productions", payload, headers)

    def list_productions(self, headers, params=None):
        return self._request("GET", "/opera/productions", headers=headers, params=params)

    def get_production(self, production_id, headers):
        return self._request("GET", f"/opera/productions/{production_id}", headers=headers)

    def transition_production(self, production_id, to_state, headers):
        return self._request(
            "POST", f"/opera/productions/{production_id}/transition",
            {"to_state": to_state}, headers,
        )

    # --- build items (PRD §3.2) ---
    def create_build_item(self, payload, headers):
        return self._request("POST", "/opera/build-items", payload, headers)

    def list_build_items(self, headers, params=None):
        return self._request("GET", "/opera/build-items", headers=headers, params=params)

    def get_build_item(self, item_id, headers):
        return self._request("GET", f"/opera/build-items/{item_id}", headers=headers)

    def transition_build_item(self, item_id, to_state, headers, actual_cost_cents=None):
        payload = {"to_state": to_state}
        if actual_cost_cents is not None:
            payload["actual_cost_cents"] = actual_cost_cents
        return self._request(
            "POST", f"/opera/build-items/{item_id}/transition", payload, headers
        )

    # --- co-production shares (PRD §3.3) ---
    def create_co_production_share(self, payload, headers):
        return self._request("POST", "/opera/co-production-shares", payload, headers)

    def list_co_production_shares(self, headers, params=None):
        return self._request("GET", "/opera/co-production-shares", headers=headers, params=params)

    def get_co_production_share(self, share_id, headers):
        return self._request("GET", f"/opera/co-production-shares/{share_id}", headers=headers)

    def transition_co_production_share(self, share_id, to_state, headers):
        return self._request(
            "POST", f"/opera/co-production-shares/{share_id}/transition",
            {"to_state": to_state}, headers,
        )

    # --- artists (PRD §3.4) ---
    def create_artist(self, payload, headers):
        return self._request("POST", "/opera/artists", payload, headers)

    def list_artists(self, headers, params=None):
        return self._request("GET", "/opera/artists", headers=headers, params=params)

    def get_artist(self, artist_id, headers):
        return self._request("GET", f"/opera/artists/{artist_id}", headers=headers)

    # --- contracts (PRD §3.4) ---
    def create_contract(self, payload, headers):
        return self._request("POST", "/opera/contracts", payload, headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/opera/contracts", headers=headers, params=params)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/opera/contracts/{contract_id}", headers=headers)

    def transition_contract(self, contract_id, to_state, headers):
        return self._request(
            "POST", f"/opera/contracts/{contract_id}/transition",
            {"to_state": to_state}, headers,
        )

    def get_pay_quote(self, contract_id, headers, week_start, mode=None):
        params = {"week_start": week_start}
        if mode is not None:
            params["mode"] = mode
        return self._request(
            "GET", f"/opera/contracts/{contract_id}/pay-quote", headers=headers, params=params
        )

    # --- roles (PRD §3.5) ---
    def create_role(self, payload, headers):
        return self._request("POST", "/opera/roles", payload, headers)

    def list_roles(self, headers, params=None):
        return self._request("GET", "/opera/roles", headers=headers, params=params)

    def get_role(self, role_id, headers):
        return self._request("GET", f"/opera/roles/{role_id}", headers=headers)

    # --- cast assignments (PRD §3.5) ---
    def create_cast_assignment(self, payload, headers):
        return self._request("POST", "/opera/cast-assignments", payload, headers)

    def list_cast_assignments(self, headers, params=None):
        return self._request("GET", "/opera/cast-assignments", headers=headers, params=params)

    def get_cast_assignment(self, assignment_id, headers):
        return self._request("GET", f"/opera/cast-assignments/{assignment_id}", headers=headers)

    def confirm_cast_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/opera/cast-assignments/{assignment_id}/confirm", {}, headers
        )

    def release_cast_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/opera/cast-assignments/{assignment_id}/release", {}, headers
        )

    # --- rehearsal rooms (PRD §3.6) ---
    def create_rehearsal_room(self, payload, headers):
        return self._request("POST", "/opera/rehearsal-rooms", payload, headers)

    def list_rehearsal_rooms(self, headers, params=None):
        return self._request("GET", "/opera/rehearsal-rooms", headers=headers, params=params)

    def get_rehearsal_room(self, room_id, headers):
        return self._request("GET", f"/opera/rehearsal-rooms/{room_id}", headers=headers)

    # --- rehearsal calls (PRD §3.6) ---
    def create_rehearsal_call(self, payload, headers):
        return self._request("POST", "/opera/rehearsal-calls", payload, headers)

    def list_rehearsal_calls(self, headers, params=None):
        return self._request("GET", "/opera/rehearsal-calls", headers=headers, params=params)

    def get_rehearsal_call(self, call_id, headers):
        return self._request("GET", f"/opera/rehearsal-calls/{call_id}", headers=headers)

    def transition_rehearsal_call(self, call_id, to_state, headers):
        return self._request(
            "POST", f"/opera/rehearsal-calls/{call_id}/transition",
            {"to_state": to_state}, headers,
        )

    # --- call participants (PRD §3.6) ---
    def create_call_participant(self, payload, headers):
        return self._request("POST", "/opera/call-participants", payload, headers)

    def list_call_participants(self, headers, params=None):
        return self._request("GET", "/opera/call-participants", headers=headers, params=params)

    def get_call_participant(self, participant_id, headers):
        return self._request("GET", f"/opera/call-participants/{participant_id}", headers=headers)

    def transition_call_participant(self, participant_id, to_state, headers):
        return self._request(
            "POST", f"/opera/call-participants/{participant_id}/transition",
            {"to_state": to_state}, headers,
        )

    def approve_waiver(self, participant_id, headers):
        return self._request(
            "POST", f"/opera/call-participants/{participant_id}/approve-waiver", {}, headers
        )

    # --- stage slots (PRD §3.7) ---
    def create_stage_slot(self, payload, headers):
        return self._request("POST", "/opera/stage-slots", payload, headers)

    def list_stage_slots(self, headers, params=None):
        return self._request("GET", "/opera/stage-slots", headers=headers, params=params)

    def get_stage_slot(self, slot_id, headers):
        return self._request("GET", f"/opera/stage-slots/{slot_id}", headers=headers)

    def transition_stage_slot(self, slot_id, to_state, headers):
        return self._request(
            "POST", f"/opera/stage-slots/{slot_id}/transition",
            {"to_state": to_state}, headers,
        )

    # --- performances (PRD §3.8) ---
    def create_performance(self, payload, headers):
        return self._request("POST", "/opera/performances", payload, headers)

    def list_performances(self, headers, params=None):
        return self._request("GET", "/opera/performances", headers=headers, params=params)

    def get_performance(self, performance_id, headers):
        return self._request("GET", f"/opera/performances/{performance_id}", headers=headers)

    def list_performance_seat_inventories(self, performance_id, headers, params=None):
        return self._request(
            "GET", f"/opera/performances/{performance_id}/seat-inventories",
            headers=headers, params=params,
        )

    def open_sales(self, performance_id, headers):
        return self._request(
            "POST", f"/opera/performances/{performance_id}/open-sales", {}, headers
        )

    def suspend_sales(self, performance_id, headers):
        return self._request(
            "POST", f"/opera/performances/{performance_id}/suspend-sales", {}, headers
        )

    def close_sales(self, performance_id, headers):
        return self._request(
            "POST", f"/opera/performances/{performance_id}/close-sales", {}, headers
        )

    def mark_tech_ready(self, performance_id, headers):
        return self._request(
            "POST", f"/opera/performances/{performance_id}/tech-ready", {}, headers
        )

    def clear_for_audience(self, performance_id, headers):
        return self._request(
            "POST", f"/opera/performances/{performance_id}/clear", {}, headers
        )

    def complete_performance(self, performance_id, headers):
        return self._request(
            "POST", f"/opera/performances/{performance_id}/complete", {}, headers
        )

    def cancel_performance(self, performance_id, headers):
        return self._request(
            "POST", f"/opera/performances/{performance_id}/cancel", {}, headers
        )

    # --- seat inventories (PRD §3.8) ---
    def list_seat_inventories(self, headers, params=None):
        return self._request("GET", "/opera/seat-inventories", headers=headers, params=params)

    def get_seat_inventory(self, inventory_id, headers):
        return self._request("GET", f"/opera/seat-inventories/{inventory_id}", headers=headers)

    def get_price_quote(self, inventory_id, headers, quantity=None):
        params = {}
        if quantity is not None:
            params["quantity"] = quantity
        return self._request(
            "GET", f"/opera/seat-inventories/{inventory_id}/price-quote",
            headers=headers, params=params,
        )

    def hold_seats(self, inventory_id, quantity, headers):
        return self._request(
            "POST", f"/opera/seat-inventories/{inventory_id}/hold",
            {"quantity": quantity}, headers,
        )

    def release_seats(self, inventory_id, quantity, headers):
        return self._request(
            "POST", f"/opera/seat-inventories/{inventory_id}/release",
            {"quantity": quantity}, headers,
        )

    def purchase_seats(self, inventory_id, quantity, headers):
        return self._request(
            "POST", f"/opera/seat-inventories/{inventory_id}/purchase",
            {"quantity": quantity}, headers,
        )

    # --- surtitle tracks (PRD §3.7) ---
    def create_surtitle_track(self, payload, headers):
        return self._request("POST", "/opera/surtitle-tracks", payload, headers)

    def list_surtitle_tracks(self, headers, params=None):
        return self._request("GET", "/opera/surtitle-tracks", headers=headers, params=params)

    def get_surtitle_track(self, track_id, headers):
        return self._request("GET", f"/opera/surtitle-tracks/{track_id}", headers=headers)

    def transition_surtitle_track(self, track_id, to_state, headers):
        return self._request(
            "POST", f"/opera/surtitle-tracks/{track_id}/transition",
            {"to_state": to_state}, headers,
        )

    # --- rental offers (PRD §3.9) ---
    def create_rental_offer(self, payload, headers):
        return self._request("POST", "/opera/rental-offers", payload, headers)

    def list_rental_offers(self, headers, params=None):
        return self._request("GET", "/opera/rental-offers", headers=headers, params=params)

    def get_rental_offer(self, offer_id, headers):
        return self._request("GET", f"/opera/rental-offers/{offer_id}", headers=headers)

    def send_rental_offer(self, offer_id, headers):
        return self._request("POST", f"/opera/rental-offers/{offer_id}/send", {}, headers)

    def revise_rental_offer(self, offer_id, per_performance_fee_cents, headers):
        return self._request(
            "POST", f"/opera/rental-offers/{offer_id}/revise",
            {"per_performance_fee_cents": per_performance_fee_cents}, headers,
        )

    def withdraw_rental_offer(self, offer_id, headers):
        return self._request("POST", f"/opera/rental-offers/{offer_id}/withdraw", {}, headers)

    def settle_rental_offer(self, offer_id, headers):
        return self._request("POST", f"/opera/rental-offers/{offer_id}/settle", {}, headers)

    def counter_rental_offer(self, offer_id, countered_fee_cents, headers):
        return self._request(
            "POST", f"/opera/rental-offers/{offer_id}/counter",
            {"countered_fee_cents": countered_fee_cents}, headers,
        )

    def accept_rental_offer(self, offer_id, headers):
        return self._request("POST", f"/opera/rental-offers/{offer_id}/accept", {}, headers)

    def decline_rental_offer(self, offer_id, headers):
        return self._request("POST", f"/opera/rental-offers/{offer_id}/decline", {}, headers)


api_client = ApiClient()
