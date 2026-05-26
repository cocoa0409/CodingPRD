"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── League management ─────────────────────────────────────────────
    def create_league(self, payload, headers):
        return self._request("POST", "/leagues", payload, headers)

    def get_league(self, league_id, headers):
        return self._request("GET", f"/leagues/{league_id}", headers=headers)

    def list_leagues(self, headers, params=None):
        return self._request("GET", "/leagues", headers=headers, params=params)

    def start_draft(self, league_id, expected_league_version, headers):
        return self._request(
            "POST", f"/leagues/{league_id}/start-draft",
            {"expected_league_version": expected_league_version}, headers,
        )

    def finalize_draft(self, league_id, expected_league_version, headers):
        return self._request(
            "POST", f"/leagues/{league_id}/finalize-draft",
            {"expected_league_version": expected_league_version}, headers,
        )

    def advance_week(self, league_id, expected_league_version, headers):
        return self._request(
            "POST", f"/leagues/{league_id}/advance-week",
            {"expected_league_version": expected_league_version}, headers,
        )

    def start_playoffs(self, league_id, expected_league_version, headers):
        return self._request(
            "POST", f"/leagues/{league_id}/start-playoffs",
            {"expected_league_version": expected_league_version}, headers,
        )

    def finalize_season(self, league_id, expected_league_version, headers):
        return self._request(
            "POST", f"/leagues/{league_id}/finalize-season",
            {"expected_league_version": expected_league_version}, headers,
        )

    def get_draft_board(self, league_id, headers, params=None):
        return self._request(
            "GET", f"/leagues/{league_id}/draft-board",
            headers=headers, params=params,
        )

    def get_player_draft_value(self, player_id, league_id, headers):
        return self._request(
            "GET", f"/players/{player_id}/draft-value",
            headers=headers, params={"league_id": league_id},
        )

    # ── Team ──────────────────────────────────────────────────────────
    def create_team(self, league_id, payload, headers):
        return self._request("POST", f"/leagues/{league_id}/teams", payload, headers)

    def get_team(self, team_id, headers):
        return self._request("GET", f"/teams/{team_id}", headers=headers)

    def list_teams(self, headers, params=None):
        return self._request("GET", "/teams", headers=headers, params=params)

    def update_keepers(self, team_id, keeper_player_ids, expected_team_version, headers):
        return self._request(
            "PATCH", f"/teams/{team_id}/keepers",
            {
                "keeper_player_ids": keeper_player_ids,
                "expected_team_version": expected_team_version,
            },
            headers,
        )

    def set_lineup(self, team_id, starter_player_ids, expected_team_version, headers):
        return self._request(
            "POST", f"/teams/{team_id}/set-lineup",
            {
                "starter_player_ids": starter_player_ids,
                "expected_team_version": expected_team_version,
            },
            headers,
        )

    def place_on_ir(self, team_id, player_id, expected_team_version, headers):
        return self._request(
            "POST", f"/teams/{team_id}/place-on-ir",
            {"player_id": player_id, "expected_team_version": expected_team_version},
            headers,
        )

    def activate_from_ir(self, team_id, player_id, expected_team_version, headers):
        return self._request(
            "POST", f"/teams/{team_id}/activate-from-ir",
            {"player_id": player_id, "expected_team_version": expected_team_version},
            headers,
        )

    def release_player(self, team_id, player_id, expected_team_version, headers):
        return self._request(
            "POST", f"/teams/{team_id}/release-player",
            {"player_id": player_id, "expected_team_version": expected_team_version},
            headers,
        )

    def list_team_roster_slots(self, team_id, headers, params=None):
        return self._request(
            "GET", f"/teams/{team_id}/roster-slots",
            headers=headers, params=params,
        )

    # ── Player ────────────────────────────────────────────────────────
    def create_player(self, payload, headers):
        return self._request("POST", "/players", payload, headers)

    def get_player(self, player_id, headers):
        return self._request("GET", f"/players/{player_id}", headers=headers)

    def list_players(self, headers, params=None):
        return self._request("GET", "/players", headers=headers, params=params)

    def report_injury(self, player_id, expected_player_version, headers):
        return self._request(
            "POST", f"/players/{player_id}/report-injury",
            {"expected_player_version": expected_player_version}, headers,
        )

    def clear_injury(self, player_id, expected_player_version, headers):
        return self._request(
            "POST", f"/players/{player_id}/clear-injury",
            {"expected_player_version": expected_player_version}, headers,
        )

    # ── DraftPick ─────────────────────────────────────────────────────
    def create_draft_pick(self, payload, headers):
        return self._request("POST", "/draft-picks", payload, headers)

    def get_draft_pick(self, pick_id, headers):
        return self._request("GET", f"/draft-picks/{pick_id}", headers=headers)

    def list_draft_picks(self, headers, params=None):
        return self._request("GET", "/draft-picks", headers=headers, params=params)

    # ── WaiverClaim ──────────────────────────────────────────────────
    def create_waiver_claim(self, payload, headers):
        return self._request("POST", "/waiver-claims", payload, headers)

    def get_waiver_claim(self, claim_id, headers):
        return self._request("GET", f"/waiver-claims/{claim_id}", headers=headers)

    def list_waiver_claims(self, headers, params=None):
        return self._request("GET", "/waiver-claims", headers=headers, params=params)

    def cancel_waiver_claim(self, claim_id, expected_waiverclaim_version, headers):
        return self._request(
            "POST", f"/waiver-claims/{claim_id}/cancel",
            {"expected_waiverclaim_version": expected_waiverclaim_version}, headers,
        )

    # ── Trade ─────────────────────────────────────────────────────────
    def create_trade(self, payload, headers):
        return self._request("POST", "/trades", payload, headers)

    def get_trade(self, trade_id, headers):
        return self._request("GET", f"/trades/{trade_id}", headers=headers)

    def list_trades(self, headers, params=None):
        return self._request("GET", "/trades", headers=headers, params=params)

    def accept_trade(self, trade_id, expected_trade_version, headers):
        return self._request(
            "POST", f"/trades/{trade_id}/accept",
            {"expected_trade_version": expected_trade_version}, headers,
        )

    def reject_trade(self, trade_id, expected_trade_version, headers):
        return self._request(
            "POST", f"/trades/{trade_id}/reject",
            {"expected_trade_version": expected_trade_version}, headers,
        )

    def withdraw_trade(self, trade_id, expected_trade_version, headers):
        return self._request(
            "POST", f"/trades/{trade_id}/withdraw",
            {"expected_trade_version": expected_trade_version}, headers,
        )

    def cast_veto_vote(self, trade_id, voter_team_id, vote, expected_trade_version, headers):
        return self._request(
            "POST", f"/trades/{trade_id}/veto-votes",
            {
                "voter_team_id": voter_team_id,
                "vote": vote,
                "expected_trade_version": expected_trade_version,
            },
            headers,
        )

    def finalize_trade(self, league_id, trade_id, expected_trade_version, headers):
        return self._request(
            "POST", f"/leagues/{league_id}/finalize-trade/{trade_id}",
            {"expected_trade_version": expected_trade_version}, headers,
        )

    def get_trade_fairness(self, trade_id, headers):
        return self._request("GET", f"/trades/{trade_id}/fairness", headers=headers)

    def list_trade_veto_votes(self, trade_id, headers, params=None):
        return self._request(
            "GET", f"/trades/{trade_id}/veto-votes",
            headers=headers, params=params,
        )

    def get_veto_vote(self, vote_id, headers):
        return self._request("GET", f"/veto-votes/{vote_id}", headers=headers)

    def list_veto_votes(self, headers, params=None):
        return self._request("GET", "/veto-votes", headers=headers, params=params)

    # ── RosterSlot reverse-reachability ───────────────────────────────
    def get_roster_slot(self, slot_id, headers):
        return self._request("GET", f"/roster-slots/{slot_id}", headers=headers)

    def list_roster_slots(self, headers, params=None):
        return self._request("GET", "/roster-slots", headers=headers, params=params)

    # ── PlayoffMatchup ────────────────────────────────────────────────
    def create_matchup(self, league_id, payload, headers):
        return self._request("POST", f"/leagues/{league_id}/matchups", payload, headers)

    def get_matchup(self, matchup_id, headers):
        return self._request("GET", f"/matchups/{matchup_id}", headers=headers)

    def list_matchups(self, headers, params=None):
        return self._request("GET", "/matchups", headers=headers, params=params)

    def start_matchup(self, matchup_id, expected_playoffmatchup_version, headers):
        return self._request(
            "POST", f"/matchups/{matchup_id}/start",
            {"expected_playoffmatchup_version": expected_playoffmatchup_version},
            headers,
        )

    def finalize_matchup(self, matchup_id, expected_playoffmatchup_version, headers,
                         home_score=None, away_score=None):
        payload = {"expected_playoffmatchup_version": expected_playoffmatchup_version}
        if home_score is not None:
            payload["home_score"] = home_score
        if away_score is not None:
            payload["away_score"] = away_score
        return self._request(
            "POST", f"/matchups/{matchup_id}/finalize",
            payload, headers,
        )

    # ── Test-driving (clock) ──────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )


api_client = ApiClient()
