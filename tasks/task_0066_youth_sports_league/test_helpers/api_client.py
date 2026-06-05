"""API client: one method per endpoint defined in the PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ─── League (PRD §3.1) ──────────────────────────────
    def create_league(self, payload, headers):
        return self._request("POST", "/leagues", payload, headers)

    def get_league(self, league_id, headers):
        return self._request("GET", f"/leagues/{league_id}", headers=headers)

    def advance_league(self, league_id, payload, headers):
        return self._request(
            "POST", f"/leagues/{league_id}/advance", payload, headers,
        )

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set", payload, headers)

    # ─── Division (PRD §3.1) ────────────────────────────
    def create_division(self, payload, headers):
        return self._request("POST", "/divisions", payload, headers)

    def list_divisions(self, headers, params=None):
        return self._request("GET", "/divisions", headers=headers, params=params)

    def get_division(self, division_id, headers):
        return self._request("GET", f"/divisions/{division_id}", headers=headers)

    # ─── Family (PRD §3.2) ──────────────────────────────
    def create_family(self, payload, headers):
        return self._request("POST", "/families", payload, headers)

    def list_families(self, headers, params=None):
        return self._request("GET", "/families", headers=headers, params=params)

    def get_family(self, family_id, headers):
        return self._request("GET", f"/families/{family_id}", headers=headers)

    # ─── Player (PRD §3.2, §3.3) ────────────────────────
    def create_player(self, payload, headers):
        return self._request("POST", "/players", payload, headers)

    def get_player(self, player_id, headers):
        return self._request("GET", f"/players/{player_id}", headers=headers)

    def list_players(self, headers, params=None):
        return self._request("GET", "/players", headers=headers, params=params)

    def verify_age(self, player_id, headers, payload=None):
        return self._request(
            "POST", f"/players/{player_id}/verify-age", payload or {}, headers,
        )

    def evaluate_player(self, player_id, payload, headers):
        return self._request(
            "POST", f"/players/{player_id}/evaluate", payload, headers,
        )

    def withdraw_player(self, player_id, headers, payload=None):
        return self._request(
            "POST", f"/players/{player_id}/withdraw", payload or {}, headers,
        )

    # ─── Team (PRD §3.1) ────────────────────────────────
    def create_team(self, payload, headers):
        return self._request("POST", "/teams", payload, headers)

    def list_teams(self, headers, params=None):
        return self._request("GET", "/teams", headers=headers, params=params)

    def get_team(self, team_id, headers):
        return self._request("GET", f"/teams/{team_id}", headers=headers)

    # ─── DraftPick (PRD §3.4) ───────────────────────────
    def create_draft_pick(self, payload, headers):
        return self._request("POST", "/draft-picks", payload, headers)

    def list_draft_picks(self, headers, params=None):
        return self._request("GET", "/draft-picks", headers=headers, params=params)

    def get_draft_pick(self, pick_id, headers):
        return self._request("GET", f"/draft-picks/{pick_id}", headers=headers)

    def void_draft_pick(self, pick_id, headers, payload=None):
        return self._request(
            "POST", f"/draft-picks/{pick_id}/void", payload or {}, headers,
        )

    # ─── Field (PRD §3.1) ───────────────────────────────
    def create_field(self, payload, headers):
        return self._request("POST", "/fields", payload, headers)

    def list_fields(self, headers, params=None):
        return self._request("GET", "/fields", headers=headers, params=params)

    def get_field(self, field_id, headers):
        return self._request("GET", f"/fields/{field_id}", headers=headers)

    # ─── Referee (PRD §3.1) ─────────────────────────────
    def create_referee(self, payload, headers):
        return self._request("POST", "/referees", payload, headers)

    def list_referees(self, headers, params=None):
        return self._request("GET", "/referees", headers=headers, params=params)

    def get_referee(self, referee_id, headers):
        return self._request("GET", f"/referees/{referee_id}", headers=headers)

    # ─── Game (PRD §3.5, §3.6) ──────────────────────────
    def create_game(self, payload, headers):
        return self._request("POST", "/games", payload, headers)

    def get_game(self, game_id, headers):
        return self._request("GET", f"/games/{game_id}", headers=headers)

    def list_games(self, headers, params=None):
        return self._request("GET", "/games", headers=headers, params=params)

    def start_game(self, game_id, headers, payload=None):
        return self._request(
            "POST", f"/games/{game_id}/start", payload or {}, headers,
        )

    def finalize_game(self, game_id, payload, headers):
        return self._request(
            "POST", f"/games/{game_id}/finalize", payload, headers,
        )

    def rainout_game(self, game_id, headers, payload=None):
        return self._request(
            "POST", f"/games/{game_id}/rainout", payload or {}, headers,
        )

    def reschedule_game(self, game_id, payload, headers):
        return self._request(
            "POST", f"/games/{game_id}/reschedule", payload, headers,
        )

    def forfeit_game(self, game_id, payload, headers):
        return self._request(
            "POST", f"/games/{game_id}/forfeit", payload, headers,
        )

    # ─── RefereeAssignment (PRD §3.7) ───────────────────
    def create_assignment(self, payload, headers):
        return self._request("POST", "/assignments", payload, headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/assignments/{assignment_id}", headers=headers,
        )

    def confirm_assignment(self, assignment_id, headers, payload=None):
        return self._request(
            "POST", f"/assignments/{assignment_id}/confirm", payload or {}, headers,
        )

    def decline_assignment(self, assignment_id, headers, payload=None):
        return self._request(
            "POST", f"/assignments/{assignment_id}/decline", payload or {}, headers,
        )

    def check_in_assignment(self, assignment_id, headers, payload=None):
        return self._request(
            "POST", f"/assignments/{assignment_id}/check-in", payload or {}, headers,
        )

    def release_assignment(self, assignment_id, headers, payload=None):
        return self._request(
            "POST", f"/assignments/{assignment_id}/release", payload or {}, headers,
        )

    # ─── VolunteerCommitment (PRD §3.8) ─────────────────
    def create_volunteer_commitment(self, payload, headers):
        return self._request("POST", "/volunteer-commitments", payload, headers)

    def list_volunteer_commitments(self, headers, params=None):
        return self._request(
            "GET", "/volunteer-commitments", headers=headers, params=params,
        )

    def get_volunteer_commitment(self, commitment_id, headers):
        return self._request(
            "GET", f"/volunteer-commitments/{commitment_id}", headers=headers,
        )

    def fulfill_commitment(self, commitment_id, headers, payload=None):
        return self._request(
            "POST", f"/volunteer-commitments/{commitment_id}/fulfill",
            payload or {}, headers,
        )

    def mark_no_show_commitment(self, commitment_id, headers, payload=None):
        return self._request(
            "POST", f"/volunteer-commitments/{commitment_id}/mark-no-show",
            payload or {}, headers,
        )

    # ─── Raw helper for header-less (unauthenticated) requests ──
    def raw_get(self, path, headers):
        return self._request("GET", path, headers=headers)


api_client = ApiClient()
