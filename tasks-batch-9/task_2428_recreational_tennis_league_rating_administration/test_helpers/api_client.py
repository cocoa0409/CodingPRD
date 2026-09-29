"""Typed HTTP client — one method per endpoint declared in PRD 4."""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX


class TennisApiClient(GenericApiClient):
    """One method per PRD 4 endpoint; every method returns the raw response."""

    # ---------------------------------------------------------------- clock
    def set_clock(self, current_utc: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/_clock/set_current_utc",
            {"current_utc": current_utc},
            headers,
        )

    def set_clock_raw(
        self, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/_clock/set_current_utc", payload, headers
        )

    # -------------------------------------------------------------- sections
    def create_section(self, payload: Any, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/sections", payload, headers)

    def get_section(self, section_id: str, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/sections/{section_id}", None, headers)

    def list_sections(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/sections", params, headers)

    def list_section_facilities(
        self, section_id: str, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/sections/{section_id}/facilities", params, headers
        )

    def year_end_recalc(self, section_id: str, headers, payload: Any = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/sections/{section_id}/year-end-recalc",
            payload if payload is not None else {},
            headers,
        )

    def publish_recalc(self, section_id: str, headers, payload: Any = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/sections/{section_id}/publish-recalc",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------ facilities
    def create_facility(self, payload: Any, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/facilities", payload, headers)

    def get_facility(self, facility_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/facilities/{facility_id}", None, headers
        )

    # --------------------------------------------------------------- leagues
    def create_league(self, payload: Any, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/leagues", payload, headers)

    def get_league(self, league_id: str, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/leagues/{league_id}", None, headers)

    def list_leagues(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/leagues", params, headers)

    def get_standings(
        self, league_id: str, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/leagues/{league_id}/standings", params, headers
        )

    def open_registration(self, league_id: str, headers, payload: Any = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/leagues/{league_id}/open-registration",
            payload if payload is not None else {},
            headers,
        )

    def lock_rosters(self, league_id: str, headers, payload: Any = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/leagues/{league_id}/lock-rosters",
            payload if payload is not None else {},
            headers,
        )

    def start_play(self, league_id: str, headers, payload: Any = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/leagues/{league_id}/start-play",
            payload if payload is not None else {},
            headers,
        )

    def seed_playoffs(self, league_id: str, headers, payload: Any = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/leagues/{league_id}/seed-playoffs",
            payload if payload is not None else {},
            headers,
        )

    def advance_teams(self, league_id: str, headers, payload: Any = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/leagues/{league_id}/advance-teams",
            payload if payload is not None else {},
            headers,
        )

    # --------------------------------------------------------------- players
    def create_player(self, payload: Any, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/players", payload, headers)

    def get_player(self, player_id: str, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/players/{player_id}", None, headers)

    def list_players(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/players", params, headers)

    def assign_rating(self, player_id: str, payload: Any, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/players/{player_id}/ratings", payload, headers
        )

    def list_player_committee_votes(
        self, player_id: str, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/players/{player_id}/committee-votes", params, headers
        )

    # ----------------------------------------------------------------- teams
    def create_team(self, payload: Any, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/teams", payload, headers)

    def get_team(self, team_id: str, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/teams/{team_id}", None, headers)

    def list_teams(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/teams", params, headers)

    def register_team(self, team_id: str, headers, payload: Any = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/teams/{team_id}/register",
            payload if payload is not None else {},
            headers,
        )

    def withdraw_team(self, team_id: str, headers, payload: Any = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/teams/{team_id}/withdraw",
            payload if payload is not None else {},
            headers,
        )

    # ----------------------------------------------------------- roster spots
    def create_roster_spot(self, payload: Any, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/roster-spots", payload, headers)

    def get_roster_spot(self, spot_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/roster-spots/{spot_id}", None, headers
        )

    def list_roster_spots(
        self, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/roster-spots", params, headers)

    def activate_roster_spot(self, spot_id: str, headers, payload: Any = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/roster-spots/{spot_id}/activate",
            payload if payload is not None else {},
            headers,
        )

    def delete_roster_spot(self, spot_id: str, headers) -> requests.Response:
        return self._request(
            "DELETE", f"{API_PREFIX}/roster-spots/{spot_id}", None, headers
        )

    # --------------------------------------------------------------- matches
    def create_match(self, payload: Any, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/matches", payload, headers)

    def get_match(self, match_id: str, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/matches/{match_id}", None, headers)

    def list_matches(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/matches", params, headers)

    def schedule_match(self, match_id: str, payload: Any, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/matches/{match_id}/schedule", payload, headers
        )

    def confirm_match(self, match_id: str, headers, payload: Any = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/matches/{match_id}/confirm",
            payload if payload is not None else {},
            headers,
        )

    def mark_played(self, match_id: str, headers, payload: Any = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/matches/{match_id}/mark-played",
            payload if payload is not None else {},
            headers,
        )

    def default_match(self, match_id: str, payload: Any, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/matches/{match_id}/default", payload, headers
        )

    # ------------------------------------------------------------ scorecards
    def create_scorecard(self, payload: Any, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/scorecards", payload, headers)

    def get_scorecard(self, scorecard_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/scorecards/{scorecard_id}", None, headers
        )

    def list_scorecards(
        self, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/scorecards", params, headers)

    def review_scorecard(
        self, scorecard_id: str, payload: Any, headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/scorecards/{scorecard_id}/review", payload, headers
        )

    def amend_scorecard(
        self, scorecard_id: str, payload: Any, headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/scorecards/{scorecard_id}/amend", payload, headers
        )

    # --------------------------------------------------------------- strikes
    def create_strike(self, payload: Any, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/strikes", payload, headers)

    def get_strike(self, strike_id: str, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/strikes/{strike_id}", None, headers)

    def list_strikes(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/strikes", params, headers)

    def rescind_strike(self, strike_id: str, payload: Any, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/strikes/{strike_id}/rescind", payload, headers
        )

    # --------------------------------------------------------- rating appeals
    def create_rating_appeal(self, payload: Any, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/rating-appeals", payload, headers)

    def get_rating_appeal(self, appeal_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/rating-appeals/{appeal_id}", None, headers
        )

    def list_rating_appeals(
        self, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/rating-appeals", params, headers)

    def start_appeal_review(self, appeal_id: str, headers, payload: Any = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/rating-appeals/{appeal_id}/start-review",
            payload if payload is not None else {},
            headers,
        )

    def decide_appeal(self, appeal_id: str, payload: Any, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/rating-appeals/{appeal_id}/decide", payload, headers
        )

    # ------------------------------------------------------------ grievances
    def create_grievance(self, payload: Any, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/grievances", payload, headers)

    def get_grievance(self, grievance_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/grievances/{grievance_id}", None, headers
        )

    def list_grievances(
        self, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/grievances", params, headers)

    def start_grievance_review(self, grievance_id: str, headers, payload: Any = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/grievances/{grievance_id}/start-review",
            payload if payload is not None else {},
            headers,
        )

    def withdraw_grievance(self, grievance_id: str, headers, payload: Any = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/grievances/{grievance_id}/withdraw",
            payload if payload is not None else {},
            headers,
        )

    def decide_grievance(
        self, grievance_id: str, payload: Any, headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/grievances/{grievance_id}/decide", payload, headers
        )

    # -------------------------------------------------------- committee votes
    def create_committee_vote(self, payload: Any, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/committee-votes", payload, headers)

    def get_committee_vote(self, vote_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/committee-votes/{vote_id}", None, headers
        )
