"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # ---- accounts & KYC ----
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/accounts", headers=headers, params=params)

    def kyc_decision(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/kyc-decision", payload, headers)

    def create_rg_control(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/rg-controls", payload, headers)

    def list_rg_controls(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/rg-controls", headers=headers, params=params)

    # ---- money ----
    def create_deposit(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/deposits", payload, headers)

    def create_withdrawal(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/withdrawals", payload, headers)

    def list_account_ledger(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/ledger", headers=headers, params=params)

    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/ledger-entries", headers=headers, params=params)

    def get_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/ledger-entries/{entry_id}", headers=headers)

    # ---- geolocation ----
    def create_geo_check(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/geo-checks", payload, headers)

    def list_geo_checks(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/geo-checks", headers=headers, params=params)

    # ---- events / markets / selections ----
    def create_event(self, payload, headers):
        return self._request("POST", "/events", payload, headers)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/events/{event_id}", headers=headers)

    def set_event_status(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/status", payload, headers)

    def post_event_result(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/result", payload, headers)

    def create_market(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/markets", payload, headers)

    def list_markets(self, event_id, headers, params=None):
        return self._request("GET", f"/events/{event_id}/markets", headers=headers, params=params)

    def get_market(self, market_id, headers):
        return self._request("GET", f"/markets/{market_id}", headers=headers)

    def set_market_status(self, market_id, payload, headers):
        return self._request("POST", f"/markets/{market_id}/status", payload, headers)

    def create_selection(self, market_id, payload, headers):
        return self._request("POST", f"/markets/{market_id}/selections", payload, headers)

    def list_selections(self, market_id, headers, params=None):
        return self._request("GET", f"/markets/{market_id}/selections", headers=headers, params=params)

    def get_selection(self, selection_id, headers):
        return self._request("GET", f"/selections/{selection_id}", headers=headers)

    def reprice_selection(self, selection_id, payload, headers):
        return self._request("PATCH", f"/selections/{selection_id}", payload, headers)

    # ---- bets ----
    def create_bet(self, payload, headers):
        return self._request("POST", "/bets", payload, headers)

    def get_bet(self, bet_id, headers):
        return self._request("GET", f"/bets/{bet_id}", headers=headers)

    def list_bets(self, headers, params=None):
        return self._request("GET", "/bets", headers=headers, params=params)

    def list_bet_legs_of_bet(self, bet_id, headers, params=None):
        return self._request("GET", f"/bets/{bet_id}/legs", headers=headers, params=params)

    def list_bet_legs(self, headers, params=None):
        return self._request("GET", "/bet-legs", headers=headers, params=params)

    def get_bet_leg(self, leg_id, headers):
        return self._request("GET", f"/bet-legs/{leg_id}", headers=headers)

    def cash_out_bet(self, bet_id, payload, headers):
        return self._request("POST", f"/bets/{bet_id}/cash-out", payload, headers)

    # ---- promotions & bonuses ----
    def create_promotion(self, payload, headers):
        return self._request("POST", "/promotions", payload, headers)

    def get_promotion(self, promotion_id, headers):
        return self._request("GET", f"/promotions/{promotion_id}", headers=headers)

    def list_promotions(self, headers, params=None):
        return self._request("GET", "/promotions", headers=headers, params=params)

    def claim_bonus(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/bonus-claims", payload, headers)

    def get_bonus_grant(self, grant_id, headers):
        return self._request("GET", f"/bonus-grants/{grant_id}", headers=headers)

    def list_bonus_grants(self, headers, params=None):
        return self._request("GET", "/bonus-grants", headers=headers, params=params)


api_client = ApiClient()
