"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the base _request() method handles HTTP
plumbing. Tests pass headers explicitly because PRD §2.1 requires
X-User-ID and X-User-Role on every call.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # =======================================================================
    # League (PRD §3.1, §3.3, §3.8)
    # =======================================================================
    def create_league(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/leagues", payload, headers)

    def get_league(self, league_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/leagues/{league_id}", headers=headers)

    def start_draft(self, league_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/leagues/{league_id}/start-draft", {}, headers,
        )

    def finish_draft(self, league_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/leagues/{league_id}/finish-draft", {}, headers,
        )

    def archive_league(self, league_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/leagues/{league_id}/archive", {}, headers,
        )

    def advance_clock(
        self, league_id: str, target_ts: str, headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/leagues/{league_id}/_clock/advance",
            {"target_ts": target_ts},
            headers,
        )

    def process_waivers(self, league_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/leagues/{league_id}/_waivers/process", {}, headers,
        )

    # =======================================================================
    # Team (PRD §3.1, §3.4)
    # =======================================================================
    def create_team(
        self, league_id: str, payload: Dict[str, Any], headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/leagues/{league_id}/teams", payload, headers,
        )

    def list_teams(
        self,
        league_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"/leagues/{league_id}/teams", headers=headers, params=params,
        )

    def get_team(self, league_id: str, team_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/leagues/{league_id}/teams/{team_id}", headers=headers,
        )

    def patch_roster_slot(
        self,
        team_id: str,
        slot_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "PATCH",
            f"/teams/{team_id}/roster-slots/{slot_id}",
            payload,
            headers,
        )

    # =======================================================================
    # Player (PRD §3.1)
    # =======================================================================
    def create_player(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/players", payload, headers)

    def list_players(
        self,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request("GET", "/players", headers=headers, params=params)

    def update_player_status(
        self,
        player_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/players/{player_id}/status", payload, headers,
        )

    # =======================================================================
    # Draft picks (PRD §3.3)
    # =======================================================================
    def create_draft_pick(
        self,
        league_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/leagues/{league_id}/draft-picks", payload, headers,
        )

    def list_draft_picks(
        self,
        league_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET",
            f"/leagues/{league_id}/draft-picks",
            headers=headers,
            params=params,
        )

    # =======================================================================
    # Keepers (PRD §3.2)
    # =======================================================================
    def create_keeper(
        self, team_id: str, payload: Dict[str, Any], headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/teams/{team_id}/keepers", payload, headers,
        )

    def list_keepers(self, team_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/teams/{team_id}/keepers", headers=headers,
        )

    def revoke_keeper(
        self, team_id: str, keeper_id: str, headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/teams/{team_id}/keepers/{keeper_id}/revoke",
            {},
            headers,
        )

    # =======================================================================
    # Waivers (PRD §3.6)
    # =======================================================================
    def create_waiver(
        self,
        league_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/leagues/{league_id}/waivers", payload, headers,
        )

    def list_waivers(
        self,
        league_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET",
            f"/leagues/{league_id}/waivers",
            headers=headers,
            params=params,
        )

    def cancel_waiver(self, waiver_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/waivers/{waiver_id}/cancel", {}, headers,
        )

    # =======================================================================
    # Trades (PRD §3.7)
    # =======================================================================
    def create_trade(
        self,
        league_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/leagues/{league_id}/trades", payload, headers,
        )

    def list_trades(
        self,
        league_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET",
            f"/leagues/{league_id}/trades",
            headers=headers,
            params=params,
        )

    def accept_trade(self, trade_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/trades/{trade_id}/accept", {}, headers,
        )

    def reject_trade(self, trade_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/trades/{trade_id}/reject", {}, headers,
        )

    def cancel_trade(self, trade_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/trades/{trade_id}/cancel", {}, headers,
        )

    def cast_trade_vote(
        self,
        trade_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/trades/{trade_id}/votes", payload, headers,
        )

    # =======================================================================
    # Matchups (PRD §3.5)
    # =======================================================================
    def list_matchups(
        self,
        league_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET",
            f"/leagues/{league_id}/matchups",
            headers=headers,
            params=params,
        )

    def score_matchup(
        self,
        league_id: str,
        week_number: int,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/leagues/{league_id}/matchups/{week_number}/score",
            payload,
            headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
