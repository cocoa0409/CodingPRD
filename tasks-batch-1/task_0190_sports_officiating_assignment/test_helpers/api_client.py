"""API client: one method per endpoint defined in the PRD (§4).

Subclasses the framework's GenericApiClient; the base _request() is inherited.
GET helpers accept an optional `params` dict for filtering/pagination.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ─── League ──────────────────────────────────────────────────────────
    def create_league(self, payload, headers):
        return self._request("POST", "/leagues", payload, headers)

    def list_leagues(self, headers, params=None):
        return self._request("GET", "/leagues", headers=headers, params=params)

    def get_league(self, league_id, headers):
        return self._request("GET", f"/leagues/{league_id}", headers=headers)

    def list_league_season_ledgers(self, league_id, headers, params=None):
        return self._request("GET", f"/leagues/{league_id}/season-ledgers",
                             headers=headers, params=params)

    def activate_league(self, league_id, headers):
        return self._request("POST", f"/leagues/{league_id}/activate", headers=headers)

    def start_postseason(self, league_id, headers):
        return self._request("POST", f"/leagues/{league_id}/start-postseason", headers=headers)

    def archive_league(self, league_id, headers):
        return self._request("POST", f"/leagues/{league_id}/archive", headers=headers)

    # ─── Official ────────────────────────────────────────────────────────
    def create_official(self, payload, headers):
        return self._request("POST", "/officials", payload, headers)

    def list_officials(self, headers, params=None):
        return self._request("GET", "/officials", headers=headers, params=params)

    def get_official(self, official_id, headers):
        return self._request("GET", f"/officials/{official_id}", headers=headers)

    def update_official(self, official_id, payload, headers):
        return self._request("PATCH", f"/officials/{official_id}", payload, headers)

    def get_official_eligibility(self, official_id, headers):
        return self._request("GET", f"/officials/{official_id}/eligibility", headers=headers)

    def list_official_assignments(self, official_id, headers, params=None):
        return self._request("GET", f"/officials/{official_id}/assignments",
                             headers=headers, params=params)

    def list_official_ledger(self, official_id, headers, params=None):
        return self._request("GET", f"/officials/{official_id}/ledger",
                             headers=headers, params=params)

    # ─── Availability ────────────────────────────────────────────────────
    def create_availability(self, payload, headers):
        return self._request("POST", "/availabilities", payload, headers)

    def list_availabilities(self, headers, params=None):
        return self._request("GET", "/availabilities", headers=headers, params=params)

    def get_availability(self, availability_id, headers):
        return self._request("GET", f"/availabilities/{availability_id}", headers=headers)

    def withdraw_availability(self, availability_id, headers):
        return self._request("POST", f"/availabilities/{availability_id}/withdraw",
                             headers=headers)

    # ─── ConflictDeclaration ─────────────────────────────────────────────
    def create_conflict_declaration(self, payload, headers):
        return self._request("POST", "/conflict-declarations", payload, headers)

    def get_conflict_declaration(self, declaration_id, headers):
        return self._request("GET", f"/conflict-declarations/{declaration_id}", headers=headers)

    def list_conflict_declarations(self, headers, params=None):
        return self._request("GET", "/conflict-declarations", headers=headers, params=params)

    # ─── Game ────────────────────────────────────────────────────────────
    def create_game(self, payload, headers):
        return self._request("POST", "/games", payload, headers)

    def list_games(self, headers, params=None):
        return self._request("GET", "/games", headers=headers, params=params)

    def get_game(self, game_id, headers):
        return self._request("GET", f"/games/{game_id}", headers=headers)

    def create_crew_slot(self, game_id, payload, headers):
        return self._request("POST", f"/games/{game_id}/crew-slots", payload, headers)

    def list_game_crew_slots(self, game_id, headers, params=None):
        return self._request("GET", f"/games/{game_id}/crew-slots",
                             headers=headers, params=params)

    def open_game(self, game_id, headers):
        return self._request("POST", f"/games/{game_id}/open", headers=headers)

    def lock_game(self, game_id, payload, headers):
        return self._request("POST", f"/games/{game_id}/lock", payload, headers)

    def settle_game(self, game_id, payload, headers):
        return self._request("POST", f"/games/{game_id}/settle", payload, headers)

    def cancel_game(self, game_id, headers):
        return self._request("POST", f"/games/{game_id}/cancel", headers=headers)

    # ─── CrewSlot / Assignment ───────────────────────────────────────────
    def get_crew_slot(self, slot_id, headers):
        return self._request("GET", f"/crew-slots/{slot_id}", headers=headers)

    def list_crew_slot_assignments(self, slot_id, headers, params=None):
        return self._request("GET", f"/crew-slots/{slot_id}/assignments",
                             headers=headers, params=params)

    def offer_crew_slot(self, slot_id, payload, headers):
        return self._request("POST", f"/crew-slots/{slot_id}/offer", payload, headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}", headers=headers)

    def accept_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/assignments/{assignment_id}/accept", payload, headers)

    def decline_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/decline", headers=headers)

    def withdraw_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/withdraw", headers=headers)

    def no_show_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/no-show", headers=headers)

    def create_evaluation(self, assignment_id, payload, headers):
        return self._request("POST", f"/assignments/{assignment_id}/evaluations",
                             payload, headers)

    def list_assignment_evaluations(self, assignment_id, headers, params=None):
        return self._request("GET", f"/assignments/{assignment_id}/evaluations",
                             headers=headers, params=params)

    # ─── PenaltyAppeal ───────────────────────────────────────────────────
    def create_appeal(self, assignment_id, payload, headers):
        return self._request("POST", f"/assignments/{assignment_id}/appeals", payload, headers)

    def list_assignment_appeals(self, assignment_id, headers, params=None):
        return self._request("GET", f"/assignments/{assignment_id}/appeals",
                             headers=headers, params=params)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/penalty-appeals/{appeal_id}", headers=headers)

    def uphold_appeal(self, appeal_id, headers):
        return self._request("POST", f"/penalty-appeals/{appeal_id}/uphold", headers=headers)

    def deny_appeal(self, appeal_id, headers):
        return self._request("POST", f"/penalty-appeals/{appeal_id}/deny", headers=headers)

    # ─── Test clock ──────────────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
