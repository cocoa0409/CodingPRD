"""API client: one method per endpoint defined in the PRD (Section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- DrawingGame ----
    def create_game(self, payload, headers):
        return self._request("POST", "/games", payload, headers)

    def get_game(self, game_id, headers):
        return self._request("GET", f"/games/{game_id}", headers=headers)

    def list_games(self, headers, params=None):
        return self._request("GET", "/games", headers=headers, params=params)

    # ---- Retailer ----
    def create_retailer(self, payload, headers):
        return self._request("POST", "/retailers", payload, headers)

    def get_retailer(self, retailer_id, headers):
        return self._request("GET", f"/retailers/{retailer_id}", headers=headers)

    def list_retailers(self, headers, params=None):
        return self._request("GET", "/retailers", headers=headers, params=params)

    def activate_license(self, retailer_id, headers):
        return self._request("POST", f"/retailers/{retailer_id}/license/activate", {}, headers)

    def suspend_license(self, retailer_id, headers):
        return self._request("POST", f"/retailers/{retailer_id}/license/suspend", {}, headers)

    def revoke_license(self, retailer_id, headers):
        return self._request("POST", f"/retailers/{retailer_id}/license/revoke", {}, headers)

    # ---- Terminal ----
    def create_terminal(self, payload, headers):
        return self._request("POST", "/terminals", payload, headers)

    def get_terminal(self, terminal_id, headers):
        return self._request("GET", f"/terminals/{terminal_id}", headers=headers)

    def list_terminals(self, headers, params=None):
        return self._request("GET", "/terminals", headers=headers, params=params)

    def activate_terminal(self, terminal_id, headers):
        return self._request("POST", f"/terminals/{terminal_id}/activate", {}, headers)

    def deactivate_terminal(self, terminal_id, headers):
        return self._request("POST", f"/terminals/{terminal_id}/deactivate", {}, headers)

    # ---- Player ----
    def create_player(self, payload, headers):
        return self._request("POST", "/players", payload, headers)

    def get_player(self, player_id, headers):
        return self._request("GET", f"/players/{player_id}", headers=headers)

    def self_exclude_player(self, player_id, payload, headers):
        return self._request("POST", f"/players/{player_id}/self-exclude", payload, headers)

    def reinstate_player(self, player_id, headers):
        return self._request("POST", f"/players/{player_id}/reinstate", {}, headers)

    # ---- Ticket ----
    def create_ticket(self, payload, headers):
        return self._request("POST", "/tickets", payload, headers)

    def get_ticket(self, ticket_id, headers):
        return self._request("GET", f"/tickets/{ticket_id}", headers=headers)

    def list_tickets(self, headers, params=None):
        return self._request("GET", "/tickets", headers=headers, params=params)

    def validate_ticket(self, ticket_id, headers):
        return self._request("POST", f"/tickets/{ticket_id}/validate", {}, headers)

    def reverse_counter_pay(self, ticket_id, headers):
        return self._request("POST", f"/tickets/{ticket_id}/reverse-counter-pay", {}, headers)

    # ---- PrizeClaim ----
    def create_prize_claim(self, payload, headers):
        return self._request("POST", "/prize-claims", payload, headers)

    def get_prize_claim(self, claim_id, headers):
        return self._request("GET", f"/prize-claims/{claim_id}", headers=headers)

    def list_prize_claims(self, headers, params=None):
        return self._request("GET", "/prize-claims", headers=headers, params=params)

    def begin_adjudication(self, claim_id, headers):
        return self._request("POST", f"/prize-claims/{claim_id}/begin-adjudication", {}, headers)

    def approve_claim(self, claim_id, headers):
        return self._request("POST", f"/prize-claims/{claim_id}/approve", {}, headers)

    def reject_claim(self, claim_id, headers):
        return self._request("POST", f"/prize-claims/{claim_id}/reject", {}, headers)

    def disburse_claim(self, claim_id, headers):
        return self._request("POST", f"/prize-claims/{claim_id}/disburse", {}, headers)

    def void_claim(self, claim_id, headers):
        return self._request("POST", f"/prize-claims/{claim_id}/void", {}, headers)

    # ---- SecondChanceDrawing ----
    def create_drawing(self, payload, headers):
        return self._request("POST", "/second-chance-drawings", payload, headers)

    def get_drawing(self, drawing_id, headers):
        return self._request("GET", f"/second-chance-drawings/{drawing_id}", headers=headers)

    def list_drawings(self, headers, params=None):
        return self._request("GET", "/second-chance-drawings", headers=headers, params=params)

    def run_drawing(self, drawing_id, payload, headers):
        return self._request("POST", f"/second-chance-drawings/{drawing_id}/run", payload, headers)

    def cancel_drawing(self, drawing_id, headers):
        return self._request("POST", f"/second-chance-drawings/{drawing_id}/cancel", {}, headers)

    # ---- SecondChanceEntry ----
    def create_entry(self, payload, headers):
        return self._request("POST", "/second-chance-entries", payload, headers)

    def get_entry(self, entry_id, headers):
        return self._request("GET", f"/second-chance-entries/{entry_id}", headers=headers)

    def list_entries(self, headers, params=None):
        return self._request("GET", "/second-chance-entries", headers=headers, params=params)

    # ---- CommissionSettlement ----
    def create_settlement(self, payload, headers):
        return self._request("POST", "/commission-settlements", payload, headers)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/commission-settlements/{settlement_id}", headers=headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", "/commission-settlements", headers=headers, params=params)

    def finalize_settlement(self, settlement_id, headers):
        return self._request("POST", f"/commission-settlements/{settlement_id}/finalize", {}, headers)

    def void_settlement(self, settlement_id, headers):
        return self._request("POST", f"/commission-settlements/{settlement_id}/void", {}, headers)

    # ---- EscheatRecord ----
    def get_escheat_record(self, record_id, headers):
        return self._request("GET", f"/escheat-records/{record_id}", headers=headers)

    def list_escheat_records(self, headers, params=None):
        return self._request("GET", "/escheat-records", headers=headers, params=params)

    # ---- Clock / sweep ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    def run_escheat_sweep(self, headers):
        return self._request("POST", "/_clock/run_escheat_sweep", {}, headers)


api_client = ApiClient()
