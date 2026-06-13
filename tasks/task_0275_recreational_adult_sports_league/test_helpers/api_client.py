"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Seasons ----
    def create_season(self, payload, headers):
        return self._request("POST", "/seasons", payload, headers)

    def get_season(self, season_id, headers):
        return self._request("GET", f"/seasons/{season_id}", headers=headers)

    def transition_season(self, season_id, payload, headers):
        return self._request("POST", f"/seasons/{season_id}/transition", payload, headers)

    # ---- Divisions ----
    def create_division(self, season_id, payload, headers):
        return self._request("POST", f"/seasons/{season_id}/divisions", payload, headers)

    def list_divisions(self, season_id, headers, params=None):
        return self._request("GET", f"/seasons/{season_id}/divisions", headers=headers, params=params)

    def get_division(self, division_id, headers):
        return self._request("GET", f"/divisions/{division_id}", headers=headers)

    def get_standings(self, division_id, headers):
        return self._request("GET", f"/divisions/{division_id}/standings", headers=headers)

    def create_game(self, division_id, payload, headers):
        return self._request("POST", f"/divisions/{division_id}/games", payload, headers)

    def list_division_games(self, division_id, headers, params=None):
        return self._request("GET", f"/divisions/{division_id}/games", headers=headers, params=params)

    # ---- Teams ----
    def create_team(self, division_id, payload, headers):
        return self._request("POST", f"/divisions/{division_id}/teams", payload, headers)

    def list_division_teams(self, division_id, headers, params=None):
        return self._request("GET", f"/divisions/{division_id}/teams", headers=headers, params=params)

    def get_team(self, team_id, headers):
        return self._request("GET", f"/teams/{team_id}", headers=headers)

    def list_teams(self, headers, params=None):
        return self._request("GET", "/teams", headers=headers, params=params)

    def pay_fee(self, team_id, payload, headers):
        return self._request("POST", f"/teams/{team_id}/pay-fee", payload, headers)

    def confirm_team(self, team_id, headers):
        return self._request("POST", f"/teams/{team_id}/confirm", {}, headers)

    def withdraw_team(self, team_id, headers):
        return self._request("POST", f"/teams/{team_id}/withdraw", {}, headers)

    def refund_adjustment(self, team_id, payload, headers):
        return self._request("POST", f"/teams/{team_id}/refund-adjustment", payload, headers)

    def list_payments(self, team_id, headers, params=None):
        return self._request("GET", f"/teams/{team_id}/payments", headers=headers, params=params)

    # ---- Roster ----
    def add_roster(self, team_id, payload, headers):
        return self._request("POST", f"/teams/{team_id}/roster", payload, headers)

    def list_roster(self, team_id, headers, params=None):
        return self._request("GET", f"/teams/{team_id}/roster", headers=headers, params=params)

    def release_roster(self, team_id, roster_entry_id, headers):
        return self._request("DELETE", f"/teams/{team_id}/roster/{roster_entry_id}", headers=headers)

    # ---- Players ----
    def create_player(self, payload, headers):
        return self._request("POST", "/players", payload, headers)

    def get_player(self, player_id, headers):
        return self._request("GET", f"/players/{player_id}", headers=headers)

    def list_player_roster_entries(self, player_id, headers, params=None):
        return self._request("GET", f"/players/{player_id}/roster-entries", headers=headers, params=params)

    # ---- Venues ----
    def create_venue(self, payload, headers):
        return self._request("POST", "/venues", payload, headers)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/venues/{venue_id}", headers=headers)

    # ---- Referees ----
    def create_referee(self, payload, headers):
        return self._request("POST", "/referees", payload, headers)

    def get_referee(self, referee_id, headers):
        return self._request("GET", f"/referees/{referee_id}", headers=headers)

    def list_referee_assignments(self, referee_id, headers, params=None):
        return self._request("GET", f"/referees/{referee_id}/assignments", headers=headers, params=params)

    # ---- Games ----
    def get_game(self, game_id, headers):
        return self._request("GET", f"/games/{game_id}", headers=headers)

    def list_games(self, headers, params=None):
        return self._request("GET", "/games", headers=headers, params=params)

    def request_reschedule(self, game_id, headers):
        return self._request("POST", f"/games/{game_id}/request-reschedule", {}, headers)

    def reschedule_game(self, game_id, payload, headers):
        return self._request("POST", f"/games/{game_id}/reschedule", payload, headers)

    def forfeit_game(self, game_id, payload, headers):
        return self._request("POST", f"/games/{game_id}/forfeit", payload, headers)

    def submit_score(self, game_id, payload, headers):
        return self._request("POST", f"/games/{game_id}/submit-score", payload, headers)

    def confirm_score(self, game_id, headers):
        return self._request("POST", f"/games/{game_id}/confirm-score", {}, headers)

    def dispute_score(self, game_id, headers):
        return self._request("POST", f"/games/{game_id}/dispute-score", {}, headers)

    # ---- Referee Assignments ----
    def create_referee_assignment(self, game_id, payload, headers):
        return self._request("POST", f"/games/{game_id}/referee-assignments", payload, headers)

    def list_game_assignments(self, game_id, headers, params=None):
        return self._request("GET", f"/games/{game_id}/referee-assignments", headers=headers, params=params)

    def release_referee_assignment(self, game_id, assignment_id, headers):
        return self._request("DELETE", f"/games/{game_id}/referee-assignments/{assignment_id}", headers=headers)

    # ---- Conduct ----
    def create_conduct_report(self, payload, headers):
        return self._request("POST", "/conduct-reports", payload, headers)

    def get_conduct_report(self, report_id, headers):
        return self._request("GET", f"/conduct-reports/{report_id}", headers=headers)

    def list_conduct_reports(self, headers, params=None):
        return self._request("GET", "/conduct-reports", headers=headers, params=params)

    def transition_conduct_report(self, report_id, payload, headers):
        return self._request("POST", f"/conduct-reports/{report_id}/transition", payload, headers)

    # ---- Test-driving clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
