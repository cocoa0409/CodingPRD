"""API client: one method per endpoint defined in the PRD (Section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- MembershipPlan ----
    def create_plan(self, payload, headers):
        return self._request("POST", "/v1/plans", payload, headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/v1/plans", headers=headers, params=params)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/v1/plans/{plan_id}", headers=headers)

    # ---- Member ----
    def create_member(self, payload, headers):
        return self._request("POST", "/v1/members", payload, headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/v1/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/v1/members/{member_id}", headers=headers)

    def change_member_plan(self, member_id, payload, headers):
        return self._request("POST", f"/v1/members/{member_id}/plan-change", payload, headers)

    def renew_member(self, member_id, payload, headers):
        return self._request("POST", f"/v1/members/{member_id}/renew", payload, headers)

    def adjust_member_wallet(self, member_id, payload, headers):
        return self._request("POST", f"/v1/members/{member_id}/wallet/adjustments", payload, headers)

    # ---- PoolTable ----
    def create_table(self, payload, headers):
        return self._request("POST", "/v1/tables", payload, headers)

    def list_tables(self, headers, params=None):
        return self._request("GET", "/v1/tables", headers=headers, params=params)

    def get_table(self, table_id, headers):
        return self._request("GET", f"/v1/tables/{table_id}", headers=headers)

    def table_maintenance(self, table_id, headers):
        return self._request("POST", f"/v1/tables/{table_id}/maintenance", {}, headers)

    def table_activate(self, table_id, headers):
        return self._request("POST", f"/v1/tables/{table_id}/activate", {}, headers)

    def table_retire(self, table_id, headers):
        return self._request("POST", f"/v1/tables/{table_id}/retire", {}, headers)

    # ---- Reservation ----
    def create_reservation(self, payload, headers):
        return self._request("POST", "/v1/reservations", payload, headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/v1/reservations", headers=headers, params=params)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/v1/reservations/{reservation_id}", headers=headers)

    def confirm_reservation(self, reservation_id, headers):
        return self._request("POST", f"/v1/reservations/{reservation_id}/confirm", {}, headers)

    def reschedule_reservation(self, reservation_id, payload, headers):
        return self._request("POST", f"/v1/reservations/{reservation_id}/reschedule", payload, headers)

    def cancel_reservation(self, reservation_id, headers):
        return self._request("POST", f"/v1/reservations/{reservation_id}/cancel", {}, headers)

    def checkin_reservation(self, reservation_id, headers):
        return self._request("POST", f"/v1/reservations/{reservation_id}/check-in", {}, headers)

    def noshow_reservation(self, reservation_id, headers):
        return self._request("POST", f"/v1/reservations/{reservation_id}/no-show", {}, headers)

    # ---- TableSession ----
    def create_session(self, payload, headers):
        return self._request("POST", "/v1/sessions", payload, headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/v1/sessions", headers=headers, params=params)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/v1/sessions/{session_id}", headers=headers)

    def close_session(self, session_id, headers):
        return self._request("POST", f"/v1/sessions/{session_id}/close", {}, headers)

    def void_session(self, session_id, headers):
        return self._request("POST", f"/v1/sessions/{session_id}/void", {}, headers)

    # ---- FnbOrder ----
    def create_fnb_order(self, payload, headers):
        return self._request("POST", "/v1/fnb-orders", payload, headers)

    def list_fnb_orders(self, headers, params=None):
        return self._request("GET", "/v1/fnb-orders", headers=headers, params=params)

    def get_fnb_order(self, order_id, headers):
        return self._request("GET", f"/v1/fnb-orders/{order_id}", headers=headers)

    def submit_fnb_order(self, order_id, headers):
        return self._request("POST", f"/v1/fnb-orders/{order_id}/submit", {}, headers)

    def void_fnb_order(self, order_id, headers):
        return self._request("POST", f"/v1/fnb-orders/{order_id}/void", {}, headers)

    # ---- Tournament ----
    def create_tournament(self, payload, headers):
        return self._request("POST", "/v1/tournaments", payload, headers)

    def list_tournaments(self, headers, params=None):
        return self._request("GET", "/v1/tournaments", headers=headers, params=params)

    def get_tournament(self, tournament_id, headers):
        return self._request("GET", f"/v1/tournaments/{tournament_id}", headers=headers)

    def open_tournament(self, tournament_id, headers):
        return self._request("POST", f"/v1/tournaments/{tournament_id}/open", {}, headers)

    def seed_tournament(self, tournament_id, headers):
        return self._request("POST", f"/v1/tournaments/{tournament_id}/seed", {}, headers)

    def start_tournament(self, tournament_id, headers):
        return self._request("POST", f"/v1/tournaments/{tournament_id}/start", {}, headers)

    def complete_tournament(self, tournament_id, headers):
        return self._request("POST", f"/v1/tournaments/{tournament_id}/complete", {}, headers)

    def cancel_tournament(self, tournament_id, headers):
        return self._request("POST", f"/v1/tournaments/{tournament_id}/cancel", {}, headers)

    # ---- TournamentEntry ----
    def create_tournament_entry(self, payload, headers):
        return self._request("POST", "/v1/tournament-entries", payload, headers)

    def list_tournament_entries(self, headers, params=None):
        return self._request("GET", "/v1/tournament-entries", headers=headers, params=params)

    def get_tournament_entry(self, entry_id, headers):
        return self._request("GET", f"/v1/tournament-entries/{entry_id}", headers=headers)

    def checkin_entry(self, entry_id, headers):
        return self._request("POST", f"/v1/tournament-entries/{entry_id}/check-in", {}, headers)

    def withdraw_entry(self, entry_id, headers):
        return self._request("POST", f"/v1/tournament-entries/{entry_id}/withdraw", {}, headers)

    # ---- ProShopProduct ----
    def create_product(self, payload, headers):
        return self._request("POST", "/v1/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/v1/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/v1/products/{product_id}", headers=headers)

    def restock_product(self, product_id, payload, headers):
        return self._request("POST", f"/v1/products/{product_id}/restock", payload, headers)

    def sell_product(self, product_id, payload, headers):
        return self._request("POST", f"/v1/products/{product_id}/sell", payload, headers)

    # ---- RepairOrder ----
    def create_repair_order(self, payload, headers):
        return self._request("POST", "/v1/repair-orders", payload, headers)

    def list_repair_orders(self, headers, params=None):
        return self._request("GET", "/v1/repair-orders", headers=headers, params=params)

    def get_repair_order(self, order_id, headers):
        return self._request("GET", f"/v1/repair-orders/{order_id}", headers=headers)

    def start_repair(self, order_id, headers):
        return self._request("POST", f"/v1/repair-orders/{order_id}/start", {}, headers)

    def ready_repair(self, order_id, headers):
        return self._request("POST", f"/v1/repair-orders/{order_id}/ready", {}, headers)

    def pickup_repair(self, order_id, headers):
        return self._request("POST", f"/v1/repair-orders/{order_id}/pickup", {}, headers)

    def cancel_repair(self, order_id, headers):
        return self._request("POST", f"/v1/repair-orders/{order_id}/cancel", {}, headers)

    # ---- Event ----
    def create_event(self, payload, headers):
        return self._request("POST", "/v1/events", payload, headers)

    def list_events(self, headers, params=None):
        return self._request("GET", "/v1/events", headers=headers, params=params)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/v1/events/{event_id}", headers=headers)

    def quote_event(self, event_id, headers):
        return self._request("POST", f"/v1/events/{event_id}/quote", {}, headers)

    def pay_deposit_event(self, event_id, headers):
        return self._request("POST", f"/v1/events/{event_id}/pay-deposit", {}, headers)

    def book_event(self, event_id, headers):
        return self._request("POST", f"/v1/events/{event_id}/book", {}, headers)

    def confirm_event(self, event_id, headers):
        return self._request("POST", f"/v1/events/{event_id}/confirm", {}, headers)

    def complete_event(self, event_id, headers):
        return self._request("POST", f"/v1/events/{event_id}/complete", {}, headers)

    def cancel_event(self, event_id, headers):
        return self._request("POST", f"/v1/events/{event_id}/cancel", {}, headers)

    # ---- Logical clock (test-driving) ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/v1/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
