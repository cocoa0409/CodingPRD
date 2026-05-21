"""Composite setup helpers — multi-step preambles tests can reuse.

The league lifecycle moves through many states before interesting claims
can be exercised: Season DRAFT_OPEN → REGULAR_SEASON requires >=4 teams
each with roster_count >=8, and getting a team's roster to 8 requires
walking 8 players each through PENDING_VERIFICATION → AGE_VERIFIED →
EVALUATED → DRAFTED. The fixtures below own that plumbing so tests
focus on assertions.

IDENTITY THREADING — PRD §2.1 (verbatim):

    "When `X-User-Role` is `Coach`, `X-User-ID` is the `id` of the
    acting `Coach`; ownership checks on any resource that references a
    `Coach` (for example, drafting onto a `Team`) compare the
    resource's `head_coach_id` to `X-User-ID`."

    "When `X-User-Role` is `Guardian`, `X-User-ID` is the `id` of the
    acting `Guardian`; ownership checks on a `Player` compare the
    player's `guardian_id` to `X-User-ID`, and ownership checks on a
    `VolunteerShift` compare the shift's `guardian_id` to `X-User-ID`."

Every fixture that creates an entity-backed actor MUST mint that
actor's headers via `make_<role>_headers(actor_id)`. Falling back to
the shared placeholder would reproduce the canonical bug: X-User-ID
never matches any real entity id, so all ownership checks reject
unconditionally and downstream tests fail to set up.

CLOCK ANCHORING — PRD §2.10:

    "an administrator-only test-driving capability is provided that
    advances the logical clock to a supplied `to` instant; subsequent
    reads of `now` return that instant and time-gated transitions
    (recording a result, marking a no-show, approving a shift, opening
    the playoffs, cancelling a postponed game) become reachable."

Setup calls use `get_success_data` (lenient 2xx validator) so setup
failures surface as 'Setup failed' rather than confusing assertion
failures downstream.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DRAFT_POSITION_MAX,
    DRAFT_POSITION_MIN,
    MIN_ROSTER_TO_START_REGULAR_SEASON,
    MIN_TEAMS_TO_START_REGULAR_SEASON,
    TEST_DEFAULTS,
)
from .factories import (
    add_days,
    add_hours,
    add_minutes,
    add_seconds,
    assign_referee_payload,
    clock_advance_payload,
    create_coach_payload,
    create_game_payload,
    create_guardian_payload,
    create_player_payload,
    create_referee_payload,
    create_season_payload,
    create_team_payload,
    create_volunteer_shift_payload,
    draft_pick_payload,
    forfeit_payload,
    iso_utc,
    parse_iso,
    postpone_payload,
    record_evaluation_payload,
    record_result_payload,
    reschedule_payload,
    unique_email,
    unique_field_id,
    unique_name,
    verify_age_payload,
)
from .test_users import (
    TEST_USERS,
    make_coach_headers,
    make_guardian_headers,
    make_referee_headers,
)


# ===========================================================================
# Clock — PRD §2.10
# ===========================================================================
def advance_clock_to(target_iso: str,
                     headers: Optional[Dict[str, str]] = None) -> None:
    """Advance the logical clock to `target_iso`.

    Idempotent against repeated calls: if the server clock is already
    at or beyond the target, this helper is a no-op.
    """
    h = headers or TEST_USERS["league_admin_headers"]
    resp = api_client.clock_advance(clock_advance_payload(to=target_iso), h)
    # Some implementations reject "monotonic only" advance — treat any
    # 4xx as best-effort skip; tests that need the clock will fail
    # downstream if it didn't move.
    try:
        get_success_data(resp)
    except AssertionError:
        return


# ===========================================================================
# Primitive creates.
# ===========================================================================
def create_season(
    *,
    name: Optional[str] = None,
    age_division: str = "MAJORS",
    min_birth_date: Optional[str] = None,
    max_birth_date: Optional[str] = None,
    regular_season_start: Optional[str] = None,
    regular_season_end: Optional[str] = None,
    playoff_cutoff_date: Optional[str] = None,
    rainout_window_days: Optional[int] = None,
    volunteer_hours_required_per_family: Optional[float] = None,
    admin_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    h = admin_headers or TEST_USERS["league_admin_headers"]
    payload = create_season_payload(
        name=name,
        age_division=age_division,
        min_birth_date=min_birth_date,
        max_birth_date=max_birth_date,
        regular_season_start=regular_season_start,
        regular_season_end=regular_season_end,
        playoff_cutoff_date=playoff_cutoff_date,
        rainout_window_days=rainout_window_days,
        volunteer_hours_required_per_family=(
            volunteer_hours_required_per_family
        ),
    )
    return get_success_data(api_client.create_season(payload, h))


def create_guardian(
    *,
    full_name: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    admin_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    h = admin_headers or TEST_USERS["league_admin_headers"]
    payload = create_guardian_payload(
        full_name=full_name, email=email, phone=phone,
    )
    return get_success_data(api_client.create_guardian(payload, h))


def create_coach(
    *,
    full_name: Optional[str] = None,
    email: Optional[str] = None,
    background_check_passed: bool = True,
    admin_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    h = admin_headers or TEST_USERS["league_admin_headers"]
    payload = create_coach_payload(
        full_name=full_name,
        email=email,
        background_check_passed=background_check_passed,
    )
    return get_success_data(api_client.create_coach(payload, h))


def create_referee(
    *,
    full_name: Optional[str] = None,
    email: Optional[str] = None,
    certification_level: str = "LEVEL_2",
    weekly_assignment_cap: Optional[int] = None,
    admin_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    h = admin_headers or TEST_USERS["league_admin_headers"]
    payload = create_referee_payload(
        full_name=full_name,
        email=email,
        certification_level=certification_level,
        weekly_assignment_cap=weekly_assignment_cap,
    )
    return get_success_data(api_client.create_referee(payload, h))


def create_player(
    *,
    season_id: str,
    guardian_id: str,
    guardian_headers: Optional[Dict[str, str]] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    birth_date: Optional[str] = None,
    birth_certificate_uri: Optional[str] = TEST_DEFAULTS["BIRTH_CERT_URI"],
) -> Dict[str, Any]:
    """Create a Player. PRD §2.1 ownership rule: the acting Guardian
    must own the new player, so we mint headers via the guardian's id
    unless an explicit header set was provided."""
    h = guardian_headers or make_guardian_headers(guardian_id)
    payload = create_player_payload(
        season_id=season_id,
        guardian_id=guardian_id,
        first_name=first_name,
        last_name=last_name,
        birth_date=birth_date,
        birth_certificate_uri=birth_certificate_uri,
    )
    return get_success_data(api_client.create_player(payload, h))


def create_team(
    *,
    season_id: str,
    head_coach_id: str,
    draft_position: int,
    name: Optional[str] = None,
    admin_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    h = admin_headers or TEST_USERS["league_admin_headers"]
    payload = create_team_payload(
        season_id=season_id,
        head_coach_id=head_coach_id,
        draft_position=draft_position,
        name=name,
    )
    return get_success_data(api_client.create_team(payload, h))


# ===========================================================================
# Player state walk.
# ===========================================================================
def verify_age(player_id: str,
               birth_certificate_uri: Optional[str] = None,
               admin_headers: Optional[Dict[str, str]] = None,
               ) -> Dict[str, Any]:
    h = admin_headers or TEST_USERS["league_admin_headers"]
    payload = verify_age_payload(birth_certificate_uri=birth_certificate_uri)
    return get_success_data(api_client.verify_age(player_id, h, payload))


def record_evaluation(player_id: str,
                      evaluation_score: float,
                      admin_headers: Optional[Dict[str, str]] = None,
                      ) -> Dict[str, Any]:
    h = admin_headers or TEST_USERS["league_admin_headers"]
    return get_success_data(
        api_client.record_evaluation(
            player_id,
            record_evaluation_payload(evaluation_score=evaluation_score),
            h,
        )
    )


def advance_player_to_evaluated(
    *,
    season_id: str,
    guardian_id: str,
    evaluation_score: float = 75.0,
    birth_date: Optional[str] = None,
    birth_certificate_uri: Optional[str] = TEST_DEFAULTS["BIRTH_CERT_URI"],
) -> Dict[str, Any]:
    """Create + verify + evaluate a player. Returns the player dict
    after the EVALUATED transition.

    PRD §3.2: walks the player through PENDING_VERIFICATION →
    AGE_VERIFIED → EVALUATED.
    """
    player = create_player(
        season_id=season_id,
        guardian_id=guardian_id,
        birth_date=birth_date,
        birth_certificate_uri=birth_certificate_uri,
    )
    verify_age(player["id"])
    return record_evaluation(player["id"], evaluation_score)


# ===========================================================================
# Coach + Team helpers.
# ===========================================================================
def make_coach_for_team(*, background_check_passed: bool = True
                        ) -> Dict[str, Any]:
    """Create a coach with background_check_passed=True so they may be
    assigned as head coach (PRD §3.3)."""
    return create_coach(
        background_check_passed=background_check_passed,
    )


def setup_season_with_teams(
    *,
    n_teams: int = 4,
    season_overrides: Optional[Dict[str, Any]] = None,
    rainout_window_days: Optional[int] = None,
    volunteer_hours_required_per_family: Optional[float] = None,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Create a season + n_teams teams, each with its own head coach.

    Returns (season, teams, coaches). Teams have draft_position 1..N.
    Season status remains DRAFT_OPEN — call `populate_team_rosters`
    next to walk to REGULAR_SEASON-ready state.
    """
    season_kwargs = dict(season_overrides or {})
    if rainout_window_days is not None:
        season_kwargs["rainout_window_days"] = rainout_window_days
    if volunteer_hours_required_per_family is not None:
        season_kwargs["volunteer_hours_required_per_family"] = (
            volunteer_hours_required_per_family
        )
    season = create_season(**season_kwargs)

    coaches: List[Dict[str, Any]] = []
    teams: List[Dict[str, Any]] = []
    for i in range(n_teams):
        coach = create_coach(background_check_passed=True)
        team = create_team(
            season_id=season["id"],
            head_coach_id=coach["id"],
            draft_position=i + 1,
            name=unique_name(f"Team{i + 1}"),
        )
        coaches.append(coach)
        teams.append(team)
    return season, teams, coaches


def populate_team_rosters(
    *,
    season: Dict[str, Any],
    teams: List[Dict[str, Any]],
    coaches: List[Dict[str, Any]],
    players_per_team: int = MIN_ROSTER_TO_START_REGULAR_SEASON,
    guardian: Optional[Dict[str, Any]] = None,
    evaluation_score_by_pick: Optional[List[float]] = None,
) -> Tuple[Dict[str, Any], List[List[Dict[str, Any]]]]:
    """Fill each team's roster up to `players_per_team` by walking the
    snake-draft pick order.

    PRD §3.3: With N teams the snake-draft seat for `picks_so_far` is:
        round_index = picks_so_far // N           (0-based)
        seat_in_round = picks_so_far % N
        current_seat = seat_in_round + 1                       (even rounds, ascending)
        current_seat = N - seat_in_round                       (odd rounds, descending)

    Returns (guardian, rosters) where `rosters[i]` is the list of
    drafted players on `teams[i]`.
    """
    n = len(teams)
    if not guardian:
        guardian = create_guardian()
    # Pre-mint all players to be evaluated, one per pick.
    total_picks = n * players_per_team
    players_pool: List[Dict[str, Any]] = []
    for i in range(total_picks):
        score = (
            evaluation_score_by_pick[i]
            if evaluation_score_by_pick is not None
            and i < len(evaluation_score_by_pick)
            else 75.0  # TIER_B by default — well below TIER_A cap
        )
        p = advance_player_to_evaluated(
            season_id=season["id"],
            guardian_id=guardian["id"],
            evaluation_score=score,
        )
        players_pool.append(p)

    rosters: List[List[Dict[str, Any]]] = [[] for _ in range(n)]
    # Walk snake-draft order.
    for pick_idx in range(total_picks):
        round_index = pick_idx // n
        seat_in_round = pick_idx % n
        if round_index % 2 == 0:
            seat = seat_in_round + 1
        else:
            seat = n - seat_in_round
        # Find the team with draft_position == seat.
        team_idx = next(
            i for i, t in enumerate(teams)
            if t["draft_position"] == seat
        )
        team = teams[team_idx]
        coach = coaches[team_idx]
        coach_headers = make_coach_headers(coach["id"])
        player = players_pool[pick_idx]
        resp = api_client.draft_pick(
            team["id"],
            draft_pick_payload(player_id=player["id"]),
            coach_headers,
        )
        updated_player = get_success_data(resp)
        rosters[team_idx].append(updated_player)
    return guardian, rosters


def advance_to_regular_season(season_id: str,
                              admin_headers: Optional[Dict[str, str]] = None,
                              ) -> Dict[str, Any]:
    """Transition Season DRAFT_OPEN → REGULAR_SEASON. PRD §3.1
    preconditions: >=4 teams, every team roster_count >=8, all non-
    WITHDRAWN players DRAFTED."""
    h = admin_headers or TEST_USERS["league_admin_headers"]
    return get_success_data(api_client.start_regular_season(season_id, h))


# ===========================================================================
# Composite fixtures for difficulty design.
# ===========================================================================
def setup_regular_season(
    *,
    n_teams: int = 4,
    players_per_team: int = MIN_ROSTER_TO_START_REGULAR_SEASON,
    rainout_window_days: Optional[int] = None,
    volunteer_hours_required_per_family: Optional[float] = None,
    season_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Full setup through REGULAR_SEASON state.

    Returns a dict with keys: season, teams, coaches, guardian, rosters.
    Subsequent tests can immediately schedule games.
    """
    season, teams, coaches = setup_season_with_teams(
        n_teams=n_teams,
        season_overrides=season_overrides,
        rainout_window_days=rainout_window_days,
        volunteer_hours_required_per_family=(
            volunteer_hours_required_per_family
        ),
    )
    guardian, rosters = populate_team_rosters(
        season=season,
        teams=teams,
        coaches=coaches,
        players_per_team=players_per_team,
    )
    season = advance_to_regular_season(season["id"])
    return {
        "season": season,
        "teams": teams,
        "coaches": coaches,
        "guardian": guardian,
        "rosters": rosters,
    }


def schedule_game(
    *,
    season_id: str,
    home_team_id: str,
    away_team_id: str,
    field_id: Optional[str] = None,
    scheduled_start: str,
    game_type: Optional[str] = None,
    admin_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    h = admin_headers or TEST_USERS["league_admin_headers"]
    payload = create_game_payload(
        season_id=season_id,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        field_id=field_id or unique_field_id(),
        scheduled_start=scheduled_start,
        game_type=game_type,
    )
    return get_success_data(api_client.create_game(payload, h))


def assign_referee_to_game(
    *,
    game_id: str,
    referee_id: str,
    version: Optional[int] = None,
    admin_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    h = admin_headers or TEST_USERS["league_admin_headers"]
    payload = assign_referee_payload(referee_id=referee_id, version=version)
    return get_success_data(api_client.assign_referee(game_id, payload, h))


def record_game_result(
    *,
    game_id: str,
    home_score: int,
    away_score: int,
    version: Optional[int] = None,
    advance_clock_to_iso: Optional[str] = None,
    admin_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """PRD §3.5: scoring requires clock >= scheduled_end. Caller may
    pre-advance the clock via `advance_clock_to_iso`."""
    if advance_clock_to_iso is not None:
        advance_clock_to(advance_clock_to_iso)
    h = admin_headers or TEST_USERS["league_admin_headers"]
    payload = record_result_payload(
        home_score=home_score,
        away_score=away_score,
        version=version,
    )
    return get_success_data(api_client.record_result(game_id, payload, h))


def forfeit_game(
    *,
    game_id: str,
    forfeiting_team_id: str,
    version: Optional[int] = None,
    admin_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    h = admin_headers or TEST_USERS["league_admin_headers"]
    payload = forfeit_payload(
        forfeiting_team_id=forfeiting_team_id,
        version=version,
    )
    return get_success_data(api_client.forfeit_game(game_id, payload, h))


def postpone_game(
    *,
    game_id: str,
    reason: str = "RAIN",
    version: Optional[int] = None,
    admin_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    h = admin_headers or TEST_USERS["league_admin_headers"]
    payload = postpone_payload(reason=reason, version=version)
    return get_success_data(api_client.postpone_game(game_id, payload, h))


def reschedule_game(
    *,
    game_id: str,
    scheduled_start: str,
    referee_id: Optional[str] = None,
    field_id: Optional[str] = None,
    version: Optional[int] = None,
    admin_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    h = admin_headers or TEST_USERS["league_admin_headers"]
    payload = reschedule_payload(
        scheduled_start=scheduled_start,
        referee_id=referee_id,
        field_id=field_id,
        version=version,
    )
    return get_success_data(api_client.reschedule_game(game_id, payload, h))


# ===========================================================================
# Volunteer shift helpers.
# ===========================================================================
def create_volunteer_shift(
    *,
    season_id: str,
    guardian: Dict[str, Any],
    role: str = "SCOREKEEPER",
    scheduled_start: str,
    scheduled_end: str,
    game_id: Optional[str] = None,
) -> Dict[str, Any]:
    """PRD §3.7: a Guardian schedules their own shift. Headers mint from
    the guardian's id so ownership flows through."""
    h = make_guardian_headers(guardian["id"])
    payload = create_volunteer_shift_payload(
        season_id=season_id,
        guardian_id=guardian["id"],
        role=role,
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
        game_id=game_id,
    )
    return get_success_data(api_client.create_volunteer_shift(payload, h))


def check_in_shift(*, shift_id: str, guardian: Dict[str, Any],
                   advance_clock_to_iso: Optional[str] = None,
                   ) -> Dict[str, Any]:
    """Guardian-only operation per PRD §3.7. Pass guardian dict so we
    can mint the correct ownership header."""
    if advance_clock_to_iso is not None:
        advance_clock_to(advance_clock_to_iso)
    h = make_guardian_headers(guardian["id"])
    return get_success_data(api_client.check_in_shift(shift_id, h))


def approve_shift(*, shift_id: str,
                  advance_clock_to_iso: Optional[str] = None,
                  admin_headers: Optional[Dict[str, str]] = None,
                  ) -> Dict[str, Any]:
    """PRD §3.7: only LeagueAdmin approves. May pre-advance the clock
    so that current_time >= shift.scheduled_end (precondition)."""
    if advance_clock_to_iso is not None:
        advance_clock_to(advance_clock_to_iso)
    h = admin_headers or TEST_USERS["league_admin_headers"]
    return get_success_data(api_client.approve_shift(shift_id, h))


def setup_guardian_with_approved_shifts(
    *,
    season_id: str,
    guardian: Optional[Dict[str, Any]] = None,
    durations_minutes: Optional[List[int]] = None,
    base_iso: Optional[str] = None,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Pre-approve N shifts for a guardian. Each shift starts a fresh
    24-hour window from `base_iso` so they don't clash with each other.
    Returns (guardian, list of APPROVED shifts).
    """
    if guardian is None:
        guardian = create_guardian()
    if durations_minutes is None:
        durations_minutes = [90, 135]  # 1.50 + 2.25 = 3.75
    start_iso = base_iso or "2026-06-01T10:00:00.000Z"
    shifts: List[Dict[str, Any]] = []
    for i, dur in enumerate(durations_minutes):
        shift_start = add_days(start_iso, i)
        shift_end = add_minutes(shift_start, dur)
        # Step clock so that BOTH check-in window and approval window
        # are satisfied: check-in at shift_start, approval at shift_end.
        advance_clock_to(shift_start)
        shift = create_volunteer_shift(
            season_id=season_id,
            guardian=guardian,
            scheduled_start=shift_start,
            scheduled_end=shift_end,
        )
        check_in_shift(shift_id=shift["id"], guardian=guardian)
        advance_clock_to(shift_end)
        shift = approve_shift(shift_id=shift["id"])
        shifts.append(shift)
    return guardian, shifts


# ===========================================================================
# Playoffs.
# ===========================================================================
def advance_to_playoffs(
    *,
    season_id: str,
    playoff_cutoff_iso: str = TEST_DEFAULTS["SEASON_PLAYOFF_CUTOFF"],
    admin_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """PRD §3.6: open playoffs once clock >= playoff_cutoff_date AND
    every regular game is terminal."""
    advance_clock_to(playoff_cutoff_iso)
    h = admin_headers or TEST_USERS["league_admin_headers"]
    return get_success_data(api_client.start_playoffs(season_id, h))


def setup_playoff_bracket(
    *,
    rainout_window_days: Optional[int] = None,
    volunteer_hours_required_per_family: Optional[float] = None,
) -> Dict[str, Any]:
    """Build a 4-team season, play out enough regular games that all
    teams have a definite record, then open playoffs.

    Returns dict with: season, teams, coaches, guardian, referee, and
    `bracket_round_1` (list of the two PLAYOFF games created by the
    seeding sweep).
    """
    bundle = setup_regular_season(
        n_teams=4,
        rainout_window_days=rainout_window_days,
        volunteer_hours_required_per_family=(
            volunteer_hours_required_per_family
        ),
    )
    season = bundle["season"]
    teams = bundle["teams"]
    # Ref for the regular games.
    ref = create_referee(weekly_assignment_cap=20)
    # Play 4 regular-season games so each team has a record:
    # T1 vs T2 (T1 wins), T3 vs T4 (T3 wins), T1 vs T3 (T1 wins),
    # T2 vs T4 (T2 wins). Final: T1 4w-0l (no, T1 plays only twice),
    # use 2 games per team: enough for ordering.
    schedule_base = "2026-05-02T18:00:00.000Z"
    plays: List[Tuple[int, int, int, int]] = [
        (0, 1, 8, 2),  # T1 home over T2
        (2, 3, 7, 3),  # T3 home over T4
        (0, 2, 6, 1),  # T1 home over T3
        (1, 3, 5, 2),  # T2 home over T4
    ]
    games: List[Dict[str, Any]] = []
    for idx, (h_idx, a_idx, hs, as_) in enumerate(plays):
        start = add_days(schedule_base, idx)
        g = schedule_game(
            season_id=season["id"],
            home_team_id=teams[h_idx]["id"],
            away_team_id=teams[a_idx]["id"],
            field_id=unique_field_id(),
            scheduled_start=start,
        )
        assign_referee_to_game(game_id=g["id"], referee_id=ref["id"])
        end_iso = add_minutes(start, 90)
        rec = record_game_result(
            game_id=g["id"],
            home_score=hs,
            away_score=as_,
            advance_clock_to_iso=end_iso,
        )
        games.append(rec)
    # Open playoffs.
    advance_to_playoffs(
        season_id=season["id"],
        playoff_cutoff_iso=TEST_DEFAULTS["SEASON_PLAYOFF_CUTOFF"],
    )
    # Find the round-1 playoff games.
    resp = api_client.list_games(
        TEST_USERS["league_admin_headers"],
        params={
            "season_id": season["id"],
            "status": "SCHEDULED",
        },
    )
    all_games = get_success_data(resp)
    items = all_games if isinstance(all_games, list) else all_games.get(
        "items", all_games,
    )
    bracket_round_1 = [
        g for g in items
        if g.get("game_type") == "PLAYOFF"
        and g.get("bracket_round") == 1
    ]
    return {
        "season": season,
        "teams": teams,
        "coaches": bundle["coaches"],
        "guardian": bundle["guardian"],
        "referee": ref,
        "regular_games": games,
        "bracket_round_1": bracket_round_1,
    }


# ===========================================================================
# Single-team-ready helper for fast non-draft tests.
# ===========================================================================
def setup_two_team_regular_season(
    *,
    rainout_window_days: Optional[int] = None,
    volunteer_hours_required_per_family: Optional[float] = None,
) -> Dict[str, Any]:
    """Build a 4-team REGULAR_SEASON. Tests that only need two teams to
    schedule a game work fine with this; they just pick teams[0] and
    teams[1]. The 4-team minimum is enforced by PRD §3.1."""
    return setup_regular_season(
        n_teams=4,
        rainout_window_days=rainout_window_days,
        volunteer_hours_required_per_family=(
            volunteer_hours_required_per_family
        ),
    )


__all__ = [
    # Clock
    "advance_clock_to",
    # Primitives
    "create_season",
    "create_guardian",
    "create_coach",
    "create_referee",
    "create_player",
    "create_team",
    # Player walk
    "verify_age",
    "record_evaluation",
    "advance_player_to_evaluated",
    # Coach
    "make_coach_for_team",
    # Composite
    "setup_season_with_teams",
    "populate_team_rosters",
    "advance_to_regular_season",
    "setup_regular_season",
    "setup_two_team_regular_season",
    # Games
    "schedule_game",
    "assign_referee_to_game",
    "record_game_result",
    "forfeit_game",
    "postpone_game",
    "reschedule_game",
    # Shifts
    "create_volunteer_shift",
    "check_in_shift",
    "approve_shift",
    "setup_guardian_with_approved_shifts",
    # Playoffs
    "advance_to_playoffs",
    "setup_playoff_bracket",
]
