"""API client: one method per endpoint defined in the PRD §4 routing contract."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock (PRD §2.5) ---
    def set_current_utc(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- Tours ---
    def create_tour(self, payload, headers):
        return self._request("POST", "/tours", payload, headers)

    def list_tours(self, headers, params=None):
        return self._request("GET", "/tours", headers=headers, params=params)

    def get_tour(self, tour_id, headers):
        return self._request("GET", f"/tours/{tour_id}", headers=headers)

    def start_routing(self, tour_id, headers):
        return self._request("POST", f"/tours/{tour_id}/start-routing", {}, headers)

    def open_on_sale(self, tour_id, headers):
        return self._request("POST", f"/tours/{tour_id}/open-on-sale", {}, headers)

    def enter_settlement_review(self, tour_id, headers):
        return self._request("POST", f"/tours/{tour_id}/enter-settlement-review", {}, headers)

    def close_tour(self, tour_id, headers):
        return self._request("POST", f"/tours/{tour_id}/close", {}, headers)

    def get_tour_pnl(self, tour_id, headers):
        return self._request("GET", f"/tours/{tour_id}/pnl", headers=headers)

    # --- Markets ---
    def create_market(self, tour_id, payload, headers):
        return self._request("POST", f"/tours/{tour_id}/markets", payload, headers)

    def list_markets(self, tour_id, headers, params=None):
        return self._request("GET", f"/tours/{tour_id}/markets", headers=headers, params=params)

    def get_market(self, tour_id, market_id, headers):
        return self._request("GET", f"/tours/{tour_id}/markets/{market_id}", headers=headers)

    def flat_get_market(self, market_id, headers):
        return self._request("GET", f"/tours/markets/{market_id}", headers=headers)

    def flat_list_markets(self, headers, params=None):
        return self._request("GET", "/tours/markets", headers=headers, params=params)

    # --- Venues ---
    def create_venue(self, tour_id, payload, headers):
        return self._request("POST", f"/tours/{tour_id}/venues", payload, headers)

    def list_venues(self, tour_id, headers, params=None):
        return self._request("GET", f"/tours/{tour_id}/venues", headers=headers, params=params)

    def get_venue(self, tour_id, venue_id, headers):
        return self._request("GET", f"/tours/{tour_id}/venues/{venue_id}", headers=headers)

    def flat_get_venue(self, venue_id, headers):
        return self._request("GET", f"/tours/venues/{venue_id}", headers=headers)

    def flat_list_venues(self, headers, params=None):
        return self._request("GET", "/tours/venues", headers=headers, params=params)

    # --- Routing legs ---
    def create_routing_leg(self, tour_id, payload, headers):
        return self._request("POST", f"/tours/{tour_id}/routing-legs", payload, headers)

    def list_routing_legs(self, tour_id, headers, params=None):
        return self._request("GET", f"/tours/{tour_id}/routing-legs", headers=headers, params=params)

    def get_routing_leg(self, tour_id, leg_id, headers):
        return self._request("GET", f"/tours/{tour_id}/routing-legs/{leg_id}", headers=headers)

    def lock_routing_leg(self, tour_id, leg_id, headers):
        return self._request("POST", f"/tours/{tour_id}/routing-legs/{leg_id}/lock", {}, headers)

    def complete_routing_leg(self, tour_id, leg_id, headers):
        return self._request("POST", f"/tours/{tour_id}/routing-legs/{leg_id}/complete", {}, headers)

    def cancel_routing_leg(self, tour_id, leg_id, headers):
        return self._request("POST", f"/tours/{tour_id}/routing-legs/{leg_id}/cancel", {}, headers)

    def flat_get_routing_leg(self, leg_id, headers):
        return self._request("GET", f"/tours/routing-legs/{leg_id}", headers=headers)

    def flat_list_routing_legs(self, headers, params=None):
        return self._request("GET", "/tours/routing-legs", headers=headers, params=params)

    # --- Shows ---
    def create_show(self, tour_id, payload, headers):
        return self._request("POST", f"/tours/{tour_id}/shows", payload, headers)

    def list_shows(self, tour_id, headers, params=None):
        return self._request("GET", f"/tours/{tour_id}/shows", headers=headers, params=params)

    def get_show(self, tour_id, show_id, headers):
        return self._request("GET", f"/tours/{tour_id}/shows/{show_id}", headers=headers)

    def confirm_show(self, tour_id, show_id, payload, headers):
        return self._request("POST", f"/tours/{tour_id}/shows/{show_id}/confirm", payload, headers)

    def advance_show(self, tour_id, show_id, headers):
        return self._request("POST", f"/tours/{tour_id}/shows/{show_id}/advance", {}, headers)

    def mark_show_performed(self, tour_id, show_id, headers):
        return self._request("POST", f"/tours/{tour_id}/shows/{show_id}/mark-performed", {}, headers)

    def cancel_show(self, tour_id, show_id, headers):
        return self._request("POST", f"/tours/{tour_id}/shows/{show_id}/cancel", {}, headers)

    def update_show_tickets(self, tour_id, show_id, payload, headers):
        return self._request("PATCH", f"/tours/{tour_id}/shows/{show_id}/tickets", payload, headers)

    def get_day_sheet(self, tour_id, show_id, headers):
        return self._request("GET", f"/tours/{tour_id}/shows/{show_id}/day-sheet", headers=headers)

    def flat_get_show(self, show_id, headers):
        return self._request("GET", f"/tours/shows/{show_id}", headers=headers)

    def flat_list_shows(self, headers, params=None):
        return self._request("GET", "/tours/shows", headers=headers, params=params)

    # --- Promoter holds ---
    def create_hold(self, tour_id, show_id, payload, headers):
        return self._request("POST", f"/tours/{tour_id}/shows/{show_id}/holds", payload, headers)

    def list_holds(self, tour_id, show_id, headers, params=None):
        return self._request("GET", f"/tours/{tour_id}/shows/{show_id}/holds",
                             headers=headers, params=params)

    def get_hold(self, tour_id, show_id, hold_id, headers):
        return self._request("GET", f"/tours/{tour_id}/shows/{show_id}/holds/{hold_id}",
                             headers=headers)

    def counter_hold(self, tour_id, show_id, hold_id, payload, headers):
        return self._request("POST", f"/tours/{tour_id}/shows/{show_id}/holds/{hold_id}/counter",
                             payload, headers)

    def respond_counter(self, tour_id, show_id, hold_id, payload, headers):
        return self._request("POST",
                             f"/tours/{tour_id}/shows/{show_id}/holds/{hold_id}/respond-counter",
                             payload, headers)

    def accept_hold(self, tour_id, show_id, hold_id, headers):
        return self._request("POST", f"/tours/{tour_id}/shows/{show_id}/holds/{hold_id}/accept",
                             {}, headers)

    def reject_hold(self, tour_id, show_id, hold_id, headers):
        return self._request("POST", f"/tours/{tour_id}/shows/{show_id}/holds/{hold_id}/reject",
                             {}, headers)

    def withdraw_hold(self, tour_id, show_id, hold_id, headers):
        return self._request("POST", f"/tours/{tour_id}/shows/{show_id}/holds/{hold_id}/withdraw",
                             {}, headers)

    def flat_get_hold(self, hold_id, headers):
        return self._request("GET", f"/tours/holds/{hold_id}", headers=headers)

    def flat_list_holds(self, headers, params=None):
        return self._request("GET", "/tours/holds", headers=headers, params=params)

    # --- Advance packet ---
    def get_advance_packet(self, tour_id, show_id, headers):
        return self._request("GET", f"/tours/{tour_id}/shows/{show_id}/advance-packet",
                             headers=headers)

    def submit_packet_section(self, tour_id, show_id, section, headers):
        return self._request(
            "POST",
            f"/tours/{tour_id}/shows/{show_id}/advance-packet/sections/{section}/submit",
            {}, headers)

    def approve_packet_section(self, tour_id, show_id, section, payload, headers):
        return self._request(
            "POST",
            f"/tours/{tour_id}/shows/{show_id}/advance-packet/sections/{section}/approve",
            payload, headers)

    def reject_packet_section(self, tour_id, show_id, section, headers):
        return self._request(
            "POST",
            f"/tours/{tour_id}/shows/{show_id}/advance-packet/sections/{section}/reject",
            {}, headers)

    def flat_get_advance_packet(self, packet_id, headers):
        return self._request("GET", f"/tours/advance-packets/{packet_id}", headers=headers)

    def flat_list_advance_packets(self, headers, params=None):
        return self._request("GET", "/tours/advance-packets", headers=headers, params=params)

    # --- Budget lines ---
    def create_budget_line(self, tour_id, show_id, payload, headers):
        return self._request("POST", f"/tours/{tour_id}/shows/{show_id}/budget-lines",
                             payload, headers)

    def list_budget_lines(self, tour_id, show_id, headers, params=None):
        return self._request("GET", f"/tours/{tour_id}/shows/{show_id}/budget-lines",
                             headers=headers, params=params)

    def get_budget_line(self, tour_id, show_id, line_id, headers):
        return self._request("GET", f"/tours/{tour_id}/shows/{show_id}/budget-lines/{line_id}",
                             headers=headers)

    def update_budget_line(self, tour_id, show_id, line_id, payload, headers):
        return self._request("PATCH", f"/tours/{tour_id}/shows/{show_id}/budget-lines/{line_id}",
                             payload, headers)

    def flat_get_budget_line(self, line_id, headers):
        return self._request("GET", f"/tours/budget-lines/{line_id}", headers=headers)

    def flat_list_budget_lines(self, headers, params=None):
        return self._request("GET", "/tours/budget-lines", headers=headers, params=params)

    # --- Marketing spends ---
    def create_marketing_spend(self, tour_id, show_id, payload, headers):
        return self._request("POST", f"/tours/{tour_id}/shows/{show_id}/marketing-spends",
                             payload, headers)

    def list_marketing_spends(self, tour_id, show_id, headers, params=None):
        return self._request("GET", f"/tours/{tour_id}/shows/{show_id}/marketing-spends",
                             headers=headers, params=params)

    def get_marketing_spend(self, tour_id, show_id, spend_id, headers):
        return self._request("GET",
                             f"/tours/{tour_id}/shows/{show_id}/marketing-spends/{spend_id}",
                             headers=headers)

    def flat_get_marketing_spend(self, spend_id, headers):
        return self._request("GET", f"/tours/marketing-spends/{spend_id}", headers=headers)

    def flat_list_marketing_spends(self, headers, params=None):
        return self._request("GET", "/tours/marketing-spends", headers=headers, params=params)

    # --- Settlements ---
    def get_settlement(self, tour_id, show_id, headers):
        return self._request("GET", f"/tours/{tour_id}/shows/{show_id}/settlement",
                             headers=headers)

    def submit_settlement(self, tour_id, show_id, payload, headers):
        return self._request("POST", f"/tours/{tour_id}/shows/{show_id}/settlement/submit",
                             payload, headers)

    def verify_settlement(self, tour_id, show_id, headers):
        return self._request("POST", f"/tours/{tour_id}/shows/{show_id}/settlement/verify",
                             {}, headers)

    def pay_settlement(self, tour_id, show_id, headers):
        return self._request("POST", f"/tours/{tour_id}/shows/{show_id}/settlement/pay",
                             {}, headers)

    def flat_get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/tours/settlements/{settlement_id}", headers=headers)

    def flat_list_settlements(self, headers, params=None):
        return self._request("GET", "/tours/settlements", headers=headers, params=params)

    # --- Compliance holds ---
    def create_compliance_hold(self, tour_id, payload, headers):
        return self._request("POST", f"/tours/{tour_id}/compliance-holds", payload, headers)

    def list_compliance_holds(self, tour_id, headers, params=None):
        return self._request("GET", f"/tours/{tour_id}/compliance-holds",
                             headers=headers, params=params)

    def get_compliance_hold(self, tour_id, hold_id, headers):
        return self._request("GET", f"/tours/{tour_id}/compliance-holds/{hold_id}",
                             headers=headers)

    def resolve_compliance_hold(self, tour_id, hold_id, headers):
        return self._request("POST", f"/tours/{tour_id}/compliance-holds/{hold_id}/resolve",
                             {}, headers)

    def flat_get_compliance_hold(self, hold_id, headers):
        return self._request("GET", f"/tours/compliance-holds/{hold_id}", headers=headers)

    def flat_list_compliance_holds(self, headers, params=None):
        return self._request("GET", "/tours/compliance-holds", headers=headers, params=params)


api_client = ApiClient()
