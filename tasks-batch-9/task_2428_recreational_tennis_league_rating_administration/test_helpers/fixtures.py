"""Composite setup builders.

Every test starts against an empty database, so each precondition has to be
constructed from scratch through the endpoints PRD 4 declares.  ``Scenario``
wraps the repetitive parts of that chain (section, facility, league, players,
teams, roster spots, lifecycle transitions, matches and scorecards) so tests can
state only the step they are actually probing.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import TennisApiClient
from .constants import (
    AGE_18_OVER,
    CLOCK_DEFAULT,
    FORMAT_MENS_DOUBLES,
    GENDER_M,
    RATING_SOURCE_COMPUTER,
    REVIEW_VERIFY,
    STAGE_PLAYOFF,
    STAGE_REGULAR,
    TIER_SECTION,
)
from .test_users import (
    LEAGUE_COORDINATOR,
    SECTION_ADMIN,
    make_captain_headers,
    make_committee_chair_headers,
    make_committee_member_headers,
)


class Scenario:
    """Mutable holder for one test's world, plus the builders that fill it."""

    def __init__(self, api: TennisApiClient):
        self.api = api
        self.section: Dict[str, Any] = {}
        self.facility: Dict[str, Any] = {}
        self.league: Dict[str, Any] = {}
        self.players: Dict[str, Dict[str, Any]] = {}
        self.teams: Dict[str, Dict[str, Any]] = {}
        self.spots: Dict[str, Dict[str, Any]] = {}
        self.matches: Dict[str, Dict[str, Any]] = {}
        self.scorecards: Dict[str, Dict[str, Any]] = {}
        self.clock: str = CLOCK_DEFAULT

    # ------------------------------------------------------------------ clock
    def set_clock(self, current_utc: str) -> None:
        get_success_data(self.api.set_clock(current_utc, SECTION_ADMIN))
        self.clock = current_utc

    # ------------------------------------------------------------ foundations
    def create_section(self, **overrides) -> Dict[str, Any]:
        self.section = get_success_data(
            self.api.create_section(f.section_payload(**overrides), SECTION_ADMIN),
            201,
        )
        return self.section

    def create_facility(self, **overrides) -> Dict[str, Any]:
        facility = get_success_data(
            self.api.create_facility(
                f.facility_payload(
                    overrides.pop("section_id", self.section["id"]), **overrides
                ),
                SECTION_ADMIN,
            ),
            201,
        )
        if not self.facility:
            self.facility = facility
        return facility

    def create_league(self, **overrides) -> Dict[str, Any]:
        league = get_success_data(
            self.api.create_league(
                f.league_payload(
                    overrides.pop("section_id", self.section["id"]), **overrides
                ),
                SECTION_ADMIN,
            ),
            201,
        )
        if not self.league:
            self.league = league
        return league

    def open_registration(self, league: Optional[Dict[str, Any]] = None) -> None:
        league = league or self.league
        get_success_data(self.api.open_registration(league["id"], SECTION_ADMIN))

    # ---------------------------------------------------------------- players
    def add_player(
        self,
        key: str,
        level: Optional[float] = None,
        gender: str = GENDER_M,
        birth_year: int = 1990,
        full_name: Optional[str] = None,
        section_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        player = get_success_data(
            self.api.create_player(
                f.player_payload(
                    section_id or self.section["id"],
                    full_name or f"Player {key.upper()}",
                    birth_year=birth_year,
                    gender=gender,
                ),
                SECTION_ADMIN,
            ),
            201,
        )
        if level is not None:
            player = get_success_data(
                self.api.assign_rating(
                    player["id"],
                    f.rating_payload(level, RATING_SOURCE_COMPUTER),
                    LEAGUE_COORDINATOR,
                )
            )
        self.players[key] = player
        return player

    def player_id(self, key: str) -> str:
        return self.players[key]["id"]

    def refresh_player(self, key: str) -> Dict[str, Any]:
        self.players[key] = get_success_data(
            self.api.get_player(self.players[key]["id"], SECTION_ADMIN)
        )
        return self.players[key]

    # ------------------------------------------------------------------ teams
    def create_team(
        self,
        key: str,
        captain_key: str,
        name: Optional[str] = None,
        league: Optional[Dict[str, Any]] = None,
        facility: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        league = league or self.league
        facility = facility or self.facility
        team = get_success_data(
            self.api.create_team(
                f.team_payload(
                    league["id"], facility["id"], name or f"Team {key.upper()}"
                ),
                make_captain_headers(self.player_id(captain_key)),
            ),
            201,
        )
        team["_captain_key"] = captain_key
        self.teams[key] = team
        return team

    def team_version(self, key: str) -> int:
        return get_success_data(
            self.api.get_team(self.teams[key]["id"], SECTION_ADMIN)
        )["version"]

    def refresh_team(self, key: str) -> Dict[str, Any]:
        captain_key = self.teams[key].get("_captain_key")
        team = get_success_data(self.api.get_team(self.teams[key]["id"], SECTION_ADMIN))
        team["_captain_key"] = captain_key
        self.teams[key] = team
        return team

    def captain_headers(self, team_key: str) -> Dict[str, str]:
        return make_captain_headers(
            self.player_id(self.teams[team_key]["_captain_key"])
        )

    def add_spot(self, team_key: str, player_key: str) -> Dict[str, Any]:
        team = self.teams[team_key]
        spot = get_success_data(
            self.api.create_roster_spot(
                f.roster_spot_payload(
                    team["id"], self.player_id(player_key), self.team_version(team_key)
                ),
                self.captain_headers(team_key),
            ),
            201,
        )
        self.spots[player_key] = spot
        return spot

    def activate_spot(self, team_key: str, player_key: str) -> Dict[str, Any]:
        spot = get_success_data(
            self.api.activate_roster_spot(
                self.spots[player_key]["id"], self.captain_headers(team_key)
            )
        )
        self.spots[player_key] = spot
        return spot

    def refresh_spot(self, player_key: str) -> Dict[str, Any]:
        self.spots[player_key] = get_success_data(
            self.api.get_roster_spot(self.spots[player_key]["id"], SECTION_ADMIN)
        )
        return self.spots[player_key]

    def fill_roster(self, team_key: str, player_keys: List[str]) -> None:
        for player_key in player_keys:
            self.add_spot(team_key, player_key)
            self.activate_spot(team_key, player_key)

    def register_team(self, team_key: str) -> Dict[str, Any]:
        team = get_success_data(
            self.api.register_team(
                self.teams[team_key]["id"], self.captain_headers(team_key)
            )
        )
        team["_captain_key"] = self.teams[team_key]["_captain_key"]
        self.teams[team_key] = team
        return team

    # -------------------------------------------------------------- lifecycle
    def lock_rosters(self, league: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        league = league or self.league
        return get_success_data(self.api.lock_rosters(league["id"], LEAGUE_COORDINATOR))

    def start_play(self, league: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        league = league or self.league
        result = get_success_data(self.api.start_play(league["id"], LEAGUE_COORDINATOR))
        if league["id"] == self.league.get("id"):
            self.league = result
        return result

    def refresh_league(self, league_id: Optional[str] = None) -> Dict[str, Any]:
        league_id = league_id or self.league["id"]
        league = get_success_data(self.api.get_league(league_id, SECTION_ADMIN))
        if league_id == self.league.get("id"):
            self.league = league
        return league

    # ---------------------------------------------------------------- matches
    def create_match(
        self,
        key: str,
        home_key: str,
        away_key: str,
        round_number: int = 1,
        league: Optional[Dict[str, Any]] = None,
        **overrides,
    ) -> Dict[str, Any]:
        league = league or self.league
        match = get_success_data(
            self.api.create_match(
                f.match_payload(
                    league["id"],
                    self.teams[home_key]["id"],
                    self.teams[away_key]["id"],
                    round_number=round_number,
                    **overrides,
                ),
                LEAGUE_COORDINATOR,
            ),
            201,
        )
        match["_home_key"] = home_key
        match["_away_key"] = away_key
        self.matches[key] = match
        return match

    def schedule_match(
        self,
        key: str,
        scheduled_start_at: str,
        courts_required: int = 3,
        facility: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        facility = facility or self.facility
        current = self.refresh_match(key)
        match = get_success_data(
            self.api.schedule_match(
                current["id"],
                f.schedule_payload(
                    facility["id"],
                    scheduled_start_at,
                    current["version"],
                    courts_required,
                ),
                LEAGUE_COORDINATOR,
            )
        )
        return self._store_match(key, match)

    def _store_match(self, key: str, match: Dict[str, Any]) -> Dict[str, Any]:
        match["_home_key"] = self.matches[key]["_home_key"]
        match["_away_key"] = self.matches[key]["_away_key"]
        self.matches[key] = match
        return match

    def refresh_match(self, key: str) -> Dict[str, Any]:
        match = get_success_data(
            self.api.get_match(self.matches[key]["id"], SECTION_ADMIN)
        )
        return self._store_match(key, match)

    def confirm_match(self, key: str) -> Dict[str, Any]:
        home_key = self.matches[key]["_home_key"]
        match = get_success_data(
            self.api.confirm_match(
                self.matches[key]["id"], self.captain_headers(home_key)
            )
        )
        return self._store_match(key, match)

    def mark_played(self, key: str) -> Dict[str, Any]:
        match = get_success_data(
            self.api.mark_played(self.matches[key]["id"], LEAGUE_COORDINATOR)
        )
        return self._store_match(key, match)

    def default_match(self, key: str, defaulting_side: str, default_kind: str):
        match = get_success_data(
            self.api.default_match(
                self.matches[key]["id"],
                f.default_payload(defaulting_side, default_kind),
                LEAGUE_COORDINATOR,
            )
        )
        return self._store_match(key, match)

    # ------------------------------------------------------------- scorecards
    def submit_scorecard(
        self, match_key: str, lines: List[Dict[str, Any]], key: str = "sc1"
    ) -> Dict[str, Any]:
        home_key = self.matches[match_key]["_home_key"]
        card = get_success_data(
            self.api.create_scorecard(
                f.scorecard_payload(self.matches[match_key]["id"], lines),
                self.captain_headers(home_key),
            ),
            201,
        )
        card["_match_key"] = match_key
        self.scorecards[key] = card
        return card

    def review_scorecard(
        self, key: str = "sc1", decision: str = REVIEW_VERIFY, **extra
    ) -> Dict[str, Any]:
        card = self.scorecards[key]
        away_key = self.matches[card["_match_key"]]["_away_key"]
        payload = {"decision": decision}
        payload.update(extra)
        result = get_success_data(
            self.api.review_scorecard(
                card["id"], payload, self.captain_headers(away_key)
            )
        )
        result["_match_key"] = card["_match_key"]
        self.scorecards[key] = result
        return result

    # --------------------------------------------------------------- committee
    def add_committee(self, chair_key: str = "pch", member_keys=("pc1", "pc2")):
        """Add committee actors that hold no roster spot anywhere."""
        self.add_player(chair_key, full_name="Chair Coleman")
        for member_key in member_keys:
            self.add_player(member_key, full_name=f"Member {member_key.upper()}")

    def chair_headers(self, chair_key: str = "pch") -> Dict[str, str]:
        return make_committee_chair_headers(self.player_id(chair_key))

    def member_headers(self, member_key: str) -> Dict[str, str]:
        return make_committee_member_headers(self.player_id(member_key))


# ---------------------------------------------------------------------------
# High-level composite builders
# ---------------------------------------------------------------------------
HOME_KEYS_6 = ["ph1", "ph2", "ph3", "ph4", "ph5", "ph6"]
AWAY_KEYS_6 = ["pa1", "pa2", "pa3", "pa4", "pa5", "pa6"]


def two_team_league(
    api: TennisApiClient,
    *,
    roster_size: int = 2,
    ntrp_level: float = 4.0,
    home_levels: Optional[List[float]] = None,
    away_levels: Optional[List[float]] = None,
    gender: str = GENDER_M,
    age_group: str = AGE_18_OVER,
    league_format: str = FORMAT_MENS_DOUBLES,
    section_kwargs: Optional[Dict[str, Any]] = None,
    facility_kwargs: Optional[Dict[str, Any]] = None,
    league_kwargs: Optional[Dict[str, Any]] = None,
    with_committee: bool = False,
    start: bool = True,
) -> Scenario:
    """Section + facility + league + two rosters of ``roster_size``, in play."""
    s = Scenario(api)
    s.set_clock(CLOCK_DEFAULT)
    s.create_section(**dict({"min_matches_for_playoff_eligibility": 1}, **(section_kwargs or {})))
    s.create_facility(**(facility_kwargs or {}))
    s.create_league(
        **dict(
            {
                "tier": TIER_SECTION,
                "ntrp_level": ntrp_level,
                "age_group": age_group,
                "format": league_format,
                "min_active_roster_size": roster_size,
            },
            **(league_kwargs or {}),
        )
    )
    s.open_registration()

    home_keys = HOME_KEYS_6[:roster_size]
    away_keys = AWAY_KEYS_6[:roster_size]
    home_levels = home_levels or [ntrp_level] * roster_size
    away_levels = away_levels or [ntrp_level] * roster_size
    for key, level in zip(home_keys, home_levels):
        s.add_player(key, level=level, gender=gender)
    for key, level in zip(away_keys, away_levels):
        s.add_player(key, level=level, gender=gender)
    if with_committee:
        s.add_committee()

    s.create_team("th", home_keys[0], "Balboa Aces")
    s.fill_roster("th", home_keys)
    s.create_team("ta", away_keys[0], "Volley Kings")
    s.fill_roster("ta", away_keys)
    s.register_team("th")
    s.register_team("ta")

    if start:
        s.set_clock("2026-08-08T00:00:00Z")
        s.lock_rosters()
        s.start_play()
        s.refresh_league()
    return s


def played_match(
    s: Scenario,
    lines: List[Dict[str, Any]],
    match_key: str = "m1",
    start_at: str = "2026-08-15T18:00:00Z",
    end_at: str = "2026-08-15T21:00:00Z",
    courts_required: int = 3,
    verify: bool = True,
    stage: str = STAGE_REGULAR,
    round_number: int = 1,
    scorecard_key: str = "sc1",
) -> Scenario:
    """Create, schedule, confirm, play and report one match on ``s``."""
    s.create_match(match_key, "th", "ta", round_number=round_number, stage=stage)
    s.schedule_match(match_key, start_at, courts_required)
    s.confirm_match(match_key)
    s.set_clock(end_at)
    s.mark_played(match_key)
    s.submit_scorecard(match_key, lines, key=scorecard_key)
    if verify:
        s.review_scorecard(key=scorecard_key)
        s.refresh_match(match_key)
    return s


def standard_three_lines(s: Scenario) -> List[Dict[str, Any]]:
    """Home wins lines 1-2, away wins line 3 (6-4 6-0, 6-4 6-3, 4-6 4-6)."""
    return [
        f.scorecard_line(
            1,
            [s.player_id("ph1"), s.player_id("ph2")],
            [s.player_id("pa1"), s.player_id("pa2")],
            [f.set_score(6, 4), f.set_score(6, 0)],
        ),
        f.scorecard_line(
            2,
            [s.player_id("ph3"), s.player_id("ph4")],
            [s.player_id("pa3"), s.player_id("pa4")],
            [f.set_score(6, 4), f.set_score(6, 3)],
        ),
        f.scorecard_line(
            3,
            [s.player_id("ph5"), s.player_id("ph6")],
            [s.player_id("pa5"), s.player_id("pa6")],
            [f.set_score(4, 6), f.set_score(4, 6)],
        ),
    ]


AWAY_ALTERNATING_LEVELS = [4.0, 3.5, 4.0, 3.5, 4.0, 3.5]
SIX_PLAYER_LEAGUE_KWARGS = {
    "lines_per_match": 3,
    "max_roster_size": 14,
    "min_playoff_eligible_players": 6,
    "max_teams": 8,
    "advancement_slots": 1,
    "match_duration_minutes": 180,
    "allow_same_day_doubleheader": False,
    "season_end_at": "2026-10-31T00:00:00Z",
}


def six_a_side_league(api: TennisApiClient, **overrides) -> Scenario:
    """Two six-player rosters in a 4.0 three-line league that is in play."""
    kwargs = {
        "roster_size": 6,
        "league_kwargs": dict(SIX_PLAYER_LEAGUE_KWARGS),
    }
    kwargs.update(overrides)
    return two_team_league(api, **kwargs)


def playoff_three_lines(s: Scenario) -> List[Dict[str, Any]]:
    """Away wins lines 1-2, home wins line 3 (6-7 0-6, 3-6 4-6, 6-2 6-2)."""
    return [
        f.scorecard_line(
            1,
            [s.player_id("ph1"), s.player_id("ph2")],
            [s.player_id("pa1"), s.player_id("pa2")],
            [f.set_score(6, 7), f.set_score(0, 6)],
        ),
        f.scorecard_line(
            2,
            [s.player_id("ph3"), s.player_id("ph4")],
            [s.player_id("pa3"), s.player_id("pa4")],
            [f.set_score(3, 6), f.set_score(4, 6)],
        ),
        f.scorecard_line(
            3,
            [s.player_id("ph5"), s.player_id("ph6")],
            [s.player_id("pa5"), s.player_id("pa6")],
            [f.set_score(6, 2), f.set_score(6, 2)],
        ),
    ]


def regular_plus_playoff_season(api: TennisApiClient) -> Scenario:
    """One verified REGULAR match and one verified PLAYOFF match, same rosters."""
    s = six_a_side_league(api, away_levels=list(AWAY_ALTERNATING_LEVELS))
    played_match(s, standard_three_lines(s), match_key="m1")
    played_match(
        s,
        playoff_three_lines(s),
        match_key="m2",
        start_at="2026-11-07T18:00:00Z",
        end_at="2026-11-07T21:00:00Z",
        stage=STAGE_PLAYOFF,
        scorecard_key="sc2",
    )
    return s
