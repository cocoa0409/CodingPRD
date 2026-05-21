"""API client — one method per endpoint defined in PRD §4.

Subclasses `GenericApiClient`; the base `_request()` handles HTTP
plumbing (envelope parsing, URL joining, auth header pass-through).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ======================================================================
    # Seasons — PRD §3.1
    # ======================================================================
    def create_season(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/league/seasons", payload, headers)

    def get_season(self, season_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/league/seasons/{season_id}", headers=headers,
        )

    def start_regular_season(self, season_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/league/seasons/{season_id}/start-regular-season",
            payload, headers,
        )

    def start_playoffs(self, season_id: str,
                       headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/league/seasons/{season_id}/start-playoffs",
            payload, headers,
        )

    def close_season(self, season_id: str,
                     headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/league/seasons/{season_id}/close",
            payload, headers,
        )

    # ======================================================================
    # Players — PRD §3.2
    # ======================================================================
    def create_player(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/league/players", payload, headers)

    def get_player(self, player_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/league/players/{player_id}", headers=headers,
        )

    def list_players(self, headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/league/players", headers=headers, params=params,
        )

    def verify_age(self, player_id: str, headers: Dict[str, str],
                   payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/league/players/{player_id}/verify-age",
            payload, headers,
        )

    def record_evaluation(self, player_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/league/players/{player_id}/record-evaluation",
            payload, headers,
        )

    def withdraw_player(self, player_id: str,
                        headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/league/players/{player_id}/withdraw",
            payload, headers,
        )

    # ======================================================================
    # Teams — PRD §3.3
    # ======================================================================
    def create_team(self, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request("POST", "/league/teams", payload, headers)

    def get_team(self, team_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/league/teams/{team_id}", headers=headers,
        )

    def draft_pick(self, team_id: str,
                   payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request(
            "POST", f"/league/teams/{team_id}/draft-pick",
            payload, headers,
        )

    # ======================================================================
    # Coaches — PRD §3.3
    # ======================================================================
    def create_coach(self, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request("POST", "/league/coaches", payload, headers)

    # ======================================================================
    # Referees — PRD §2.8
    # ======================================================================
    def create_referee(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/league/referees", payload, headers)

    # ======================================================================
    # Guardians — PRD §3.2
    # ======================================================================
    def create_guardian(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/league/guardians", payload, headers)

    def get_guardian(self, guardian_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/league/guardians/{guardian_id}", headers=headers,
        )

    # ======================================================================
    # Games — PRD §3.4, §3.5
    # ======================================================================
    def create_game(self, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request("POST", "/league/games", payload, headers)

    def get_game(self, game_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/league/games/{game_id}", headers=headers,
        )

    def list_games(self, headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/league/games", headers=headers, params=params,
        )

    def assign_referee(self, game_id: str,
                       payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/league/games/{game_id}/assign-referee",
            payload, headers,
        )

    def postpone_game(self, game_id: str,
                      payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/league/games/{game_id}/postpone",
            payload, headers,
        )

    def reschedule_game(self, game_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/league/games/{game_id}/reschedule",
            payload, headers,
        )

    def cancel_game(self, game_id: str,
                    headers: Dict[str, str],
                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/league/games/{game_id}/cancel",
            payload, headers,
        )

    def record_result(self, game_id: str,
                      payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/league/games/{game_id}/record-result",
            payload, headers,
        )

    def forfeit_game(self, game_id: str,
                     payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/league/games/{game_id}/forfeit",
            payload, headers,
        )

    # ======================================================================
    # Volunteer shifts — PRD §3.7
    # ======================================================================
    def create_volunteer_shift(self, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST", "/league/volunteer-shifts", payload, headers,
        )

    def get_volunteer_shift(self, shift_id: str,
                            headers: Dict[str, str]):
        return self._request(
            "GET", f"/league/volunteer-shifts/{shift_id}",
            headers=headers,
        )

    def check_in_shift(self, shift_id: str,
                       headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/league/volunteer-shifts/{shift_id}/check-in",
            payload, headers,
        )

    def approve_shift(self, shift_id: str,
                      headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/league/volunteer-shifts/{shift_id}/approve",
            payload, headers,
        )

    def mark_shift_no_show(self, shift_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/league/volunteer-shifts/{shift_id}/mark-no-show",
            payload, headers,
        )

    def delete_volunteer_shift(self, shift_id: str,
                               headers: Dict[str, str]):
        return self._request(
            "DELETE", f"/league/volunteer-shifts/{shift_id}",
            headers=headers,
        )

    # ======================================================================
    # Time-driving clock + audit log — PRD §2.10, §3.8
    # ======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Optional[Dict[str, str]] = None):
        # The clock endpoint is the one endpoint exempt from auth (PRD
        # §2.10), but the LeagueAdmin restriction still applies in the
        # role table (§4). We forward whatever headers caller provides.
        return self._request(
            "POST", "/_clock/advance", payload, headers or {},
        )

    def list_audit_events(self, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/league/audit-events",
            headers=headers, params=params,
        )


# Module-level singleton consumed by tests and fixtures alike.
api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
