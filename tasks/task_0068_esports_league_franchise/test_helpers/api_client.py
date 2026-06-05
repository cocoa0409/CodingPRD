"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Season ----
    def create_season(self, payload, headers):
        return self._request("POST", "/seasons", payload, headers)

    def get_season(self, season_id, headers):
        return self._request("GET", f"/seasons/{season_id}", headers=headers)

    def start_regular(self, season_id, headers, payload=None):
        return self._request("POST", f"/seasons/{season_id}/start-regular", payload, headers)

    def set_trade_window(self, season_id, payload, headers):
        return self._request("POST", f"/seasons/{season_id}/trade-window", payload, headers)

    def start_playoffs(self, season_id, headers, payload=None):
        return self._request("POST", f"/seasons/{season_id}/start-playoffs", payload, headers)

    def complete_season(self, season_id, headers, payload=None):
        return self._request("POST", f"/seasons/{season_id}/complete", payload, headers)

    # ---- Team ----
    def create_team(self, payload, headers):
        return self._request("POST", "/teams", payload, headers)

    def get_team(self, team_id, headers):
        return self._request("GET", f"/teams/{team_id}", headers=headers)

    def list_teams(self, headers, params=None):
        return self._request("GET", "/teams", headers=headers, params=params)

    def get_team_payroll(self, team_id, headers):
        return self._request("GET", f"/teams/{team_id}/payroll", headers=headers)

    def get_team_contracts(self, team_id, headers, params=None):
        return self._request("GET", f"/teams/{team_id}/contracts", headers=headers, params=params)

    def get_team_fines(self, team_id, headers):
        return self._request("GET", f"/teams/{team_id}/fines", headers=headers)

    def get_team_revenue_shares(self, team_id, headers):
        return self._request("GET", f"/teams/{team_id}/revenue-shares", headers=headers)

    def eliminate_team(self, team_id, headers, payload=None):
        return self._request("POST", f"/teams/{team_id}/eliminate", payload, headers)

    # ---- Player ----
    def create_player(self, payload, headers):
        return self._request("POST", "/players", payload, headers)

    def get_player(self, player_id, headers):
        return self._request("GET", f"/players/{player_id}", headers=headers)

    def list_players(self, headers, params=None):
        return self._request("GET", "/players", headers=headers, params=params)

    # ---- Contract ----
    def create_contract(self, payload, headers):
        return self._request("POST", "/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/contracts", headers=headers, params=params)

    def promote_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/promote", payload, headers)

    def waive_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/waive", payload, headers)

    # ---- Stint ----
    def create_stint(self, payload, headers):
        return self._request("POST", "/stints", payload, headers)

    def get_stint(self, stint_id, headers):
        return self._request("GET", f"/stints/{stint_id}", headers=headers)

    def list_stints(self, headers, params=None):
        return self._request("GET", "/stints", headers=headers, params=params)

    # ---- Trade ----
    def create_trade(self, payload, headers):
        return self._request("POST", "/trades", payload, headers)

    def get_trade(self, trade_id, headers):
        return self._request("GET", f"/trades/{trade_id}", headers=headers)

    def list_trades(self, headers, params=None):
        return self._request("GET", "/trades", headers=headers, params=params)

    def accept_trade(self, trade_id, payload, headers):
        return self._request("POST", f"/trades/{trade_id}/accept", payload, headers)

    def reject_trade(self, trade_id, headers, payload=None):
        return self._request("POST", f"/trades/{trade_id}/reject", payload, headers)

    def withdraw_trade(self, trade_id, headers, payload=None):
        return self._request("POST", f"/trades/{trade_id}/withdraw", payload, headers)

    # ---- Fine ----
    def create_fine(self, payload, headers):
        return self._request("POST", "/fines", payload, headers)

    def get_fine(self, fine_id, headers):
        return self._request("GET", f"/fines/{fine_id}", headers=headers)

    def list_fines(self, headers, params=None):
        return self._request("GET", "/fines", headers=headers, params=params)

    def waive_fine(self, fine_id, headers, payload=None):
        return self._request("POST", f"/fines/{fine_id}/waive", payload, headers)

    # ---- Sponsorship ----
    def create_sponsorship(self, payload, headers):
        return self._request("POST", "/sponsorships", payload, headers)

    def get_sponsorship(self, sponsorship_id, headers):
        return self._request("GET", f"/sponsorships/{sponsorship_id}", headers=headers)

    def list_sponsorships(self, headers, params=None):
        return self._request("GET", "/sponsorships", headers=headers, params=params)

    def get_sponsorship_revenue_shares(self, sponsorship_id, headers):
        return self._request("GET", f"/sponsorships/{sponsorship_id}/revenue-shares", headers=headers)

    def distribute_sponsorship(self, sponsorship_id, payload, headers):
        return self._request("POST", f"/sponsorships/{sponsorship_id}/distribute", payload, headers)


api_client = ApiClient()
