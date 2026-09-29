"""Values that land exactly on an inclusive or exclusive boundary."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import factories as f
from test_helpers.assertions import assert_instant_equals
from test_helpers.api_errors import ERR_FACILITY_COURTS_EXCEEDED
from test_helpers.constants import (
    AGE_18_OVER,
    CLOCK_DEFAULT,
    FORMAT_MENS_DOUBLES,
    INELIGIBLE_PLAYER_SUSPENDED,
    PLAYER_ACTIVE,
    PLAYER_STRIKE_SUSPENDED,
    RATING_PERIOD_RECALC_IN_PROGRESS,
    SCHED_SCHEDULED,
    SPOT_ACTIVE,
    SPOT_INELIGIBLE,
    STRIKE_INELIGIBLE_LINEUP,
    STRIKE_NO_SHOW_DEFAULT,
    TIER_SECTION,
)
from test_helpers.fixtures import (
    AWAY_ALTERNATING_LEVELS,
    Scenario,
    played_match,
    six_a_side_league,
    standard_three_lines,
    two_team_league,
)
from test_helpers.test_users import LEAGUE_COORDINATOR, SECTION_ADMIN

ALL_TWELVE = ["ph1", "ph2", "ph3", "ph4", "ph5", "ph6",
              "pa1", "pa2", "pa3", "pa4", "pa5", "pa6"]


# ---------------------------------------------------------------------------
# Instance: recalc_delta_hits_both_thresholds_exactly_and_signed_comparison_decides
# ---------------------------------------------------------------------------
def _proposals_sitting_on_both_thresholds(api):
    """One verified match puts deltas of exactly +0.250, -0.350 and -0.250 in play."""
    s = six_a_side_league(api, away_levels=list(AWAY_ALTERNATING_LEVELS))
    played_match(s, standard_three_lines(s), match_key="m1")
    get_success_data(api.year_end_recalc(s.section["id"], SECTION_ADMIN))
    return s


def test_a_delta_of_exactly_plus_or_minus_the_threshold_moves_the_level(api):
    """+0.250 promotes a2 and -0.350 demotes h5 and h6; both bounds are inclusive.

    PRD 3.9: "Both boundaries are inclusive: a delta of exactly 0.25 bumps up, a
    delta of exactly negative 0.35 bumps down, and a delta of negative 0.34 leaves
    the level alone."

    Design: Difficulty/boundary_precision_check/recalc_delta_hits_both_thresholds_exactly_and_signed_comparison_decides
    """
    s = _proposals_sitting_on_both_thresholds(api)

    a2 = s.refresh_player("pa2")
    assert a2["proposed_recalc_dynamic"] == 3.750
    assert a2["proposed_recalc_level"] == 4.0
    assert a2["rating_level"] == 3.5

    h5 = s.refresh_player("ph5")
    assert h5["proposed_recalc_dynamic"] == 3.650
    assert h5["proposed_recalc_level"] == 3.5
    assert h5["rating_level"] == 4.0

    h6 = s.refresh_player("ph6")
    assert h6["proposed_recalc_dynamic"] == 3.650
    assert h6["proposed_recalc_level"] == 3.5


def test_the_negative_mirror_of_the_up_threshold_leaves_the_level_alone(api):
    """a1 sits at -0.250, so an absolute-value comparison would wrongly demote it.

    PRD 3.9: "Otherwise `proposed_recalc_level` is set equal to the player's
    existing `rating_level` - in scope, evaluated, and proposed unchanged."

    Design: Difficulty/boundary_precision_check/recalc_delta_hits_both_thresholds_exactly_and_signed_comparison_decides
    """
    s = _proposals_sitting_on_both_thresholds(api)

    a1 = s.refresh_player("pa1")
    assert a1["proposed_recalc_dynamic"] == 3.750
    assert a1["rating_level"] == 4.0
    assert a1["proposed_recalc_level"] == 4.0
    assert a1["proposed_recalc_level"] != 3.5

    h1 = s.refresh_player("ph1")
    assert h1["proposed_recalc_dynamic"] == 4.000
    assert h1["proposed_recalc_level"] == 4.0
    h3 = s.refresh_player("ph3")
    assert h3["proposed_recalc_dynamic"] == 3.882
    assert h3["proposed_recalc_level"] == 4.0

    for key in ("pa3", "pa4", "pa5", "pa6"):
        assert s.refresh_player(key)["proposed_recalc_level"] == 4.0

    changed = [
        key
        for key in ALL_TWELVE
        if s.refresh_player(key)["proposed_recalc_level"]
        != s.refresh_player(key)["rating_level"]
    ]
    assert len(changed) == 5

    section = get_success_data(api.get_section(s.section["id"], SECTION_ADMIN))
    assert section["rating_period_status"] == RATING_PERIOD_RECALC_IN_PROGRESS
    assert section["recalculated_player_count"] == 12


# ---------------------------------------------------------------------------
# Instance: schedule_at_exact_occupancy_end_admitted_one_minute_earlier_rejected
# ---------------------------------------------------------------------------
def _two_court_facility_fully_booked_from_eighteen_hundred(api):
    """M1 holds both courts over [18:00, 21:30); M2 pairs two idle teams."""
    s = Scenario(api)
    s.set_clock(CLOCK_DEFAULT)
    s.create_section(min_matches_for_playoff_eligibility=1)
    s.create_facility(court_count=2, turnaround_buffer_minutes=30)
    s.create_league(
        tier=TIER_SECTION,
        ntrp_level=4.0,
        age_group=AGE_18_OVER,
        format=FORMAT_MENS_DOUBLES,
        min_active_roster_size=2,
        match_duration_minutes=180,
    )
    s.open_registration()

    team_keys = ["th", "ta", "t3", "t4"]
    for index, team_key in enumerate(team_keys, start=1):
        first, second = f"p{index}a", f"p{index}b"
        s.add_player(first, level=4.0)
        s.add_player(second, level=4.0)
        s.create_team(team_key, first, f"Squad {index}")
        s.fill_roster(team_key, [first, second])
        s.register_team(team_key)

    s.set_clock("2026-08-08T00:00:00Z")
    s.lock_rosters()
    s.start_play()

    s.create_match("m1", "th", "ta")
    s.schedule_match("m1", "2026-08-15T18:00:00Z", 2)
    s.create_match("m2", "t3", "t4")
    return s


def test_a_start_exactly_on_the_buffer_extended_end_instant_is_admitted(api):
    """21:30 is 18:00 plus 180 minutes plus the 30-minute buffer, so it fits.

    PRD 3.5: "And a request whose start instant is exactly equal to an occupant's
    interval end - that is, exactly the occupant's start plus the occupant's
    duration plus the buffer - does **not** intersect that occupant, and is
    admitted even when the facility is otherwise at exactly its `court_count`."

    Design: Difficulty/boundary_precision_check/schedule_at_exact_occupancy_end_admitted_one_minute_earlier_rejected
    """
    s = _two_court_facility_fully_booked_from_eighteen_hundred(api)
    m2 = s.refresh_match("m2")
    scheduled = get_success_data(
        api.schedule_match(
            m2["id"],
            f.schedule_payload(
                s.facility["id"], "2026-08-15T21:30:00Z", m2["version"], 2
            ),
            LEAGUE_COORDINATOR,
        )
    )
    assert scheduled["schedule_status"] == SCHED_SCHEDULED
    assert_instant_equals(scheduled["scheduled_start_at"], "2026-08-15T21:30:00Z")
    assert scheduled["courts_required"] == 2
    assert scheduled["facility_id"] == s.facility["id"]

    # scheduled_end_at is start + duration and deliberately excludes the buffer.
    assert_instant_equals(scheduled["scheduled_end_at"], "2026-08-16T00:30:00Z")
    first = s.refresh_match("m1")
    assert_instant_equals(first["scheduled_start_at"], "2026-08-15T18:00:00Z")
    assert_instant_equals(first["scheduled_end_at"], "2026-08-15T21:00:00Z")
    assert first["schedule_status"] == SCHED_SCHEDULED


def test_one_minute_before_that_instant_exhausts_the_two_courts(api):
    """21:29 still intersects the occupancy, so the court rule refuses it.

    PRD 3.5: "The service sums the `courts_required` of every occupant whose
    interval intersects the requested interval, and requires that sum plus the
    requested `courts_required` to be at most the facility's `court_count`;
    exceeding it is refused with `ERR_FACILITY_COURTS_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/schedule_at_exact_occupancy_end_admitted_one_minute_earlier_rejected
    """
    s = _two_court_facility_fully_booked_from_eighteen_hundred(api)
    m2 = s.refresh_match("m2")
    get_success_data(
        api.schedule_match(
            m2["id"],
            f.schedule_payload(
                s.facility["id"], "2026-08-15T21:30:00Z", m2["version"], 2
            ),
            LEAGUE_COORDINATOR,
        )
    )

    rescheduling = s.refresh_match("m2")
    validate_error(
        api.schedule_match(
            rescheduling["id"],
            f.schedule_payload(
                s.facility["id"],
                "2026-08-15T21:29:00Z",
                rescheduling["version"],
                2,
            ),
            LEAGUE_COORDINATOR,
        ),
        ERR_FACILITY_COURTS_EXCEEDED,
        409,
    )

    unchanged = s.refresh_match("m2")
    assert_instant_equals(unchanged["scheduled_start_at"], "2026-08-15T21:30:00Z")
    assert_instant_equals(unchanged["scheduled_end_at"], "2026-08-16T00:30:00Z")
    assert unchanged["schedule_status"] == SCHED_SCHEDULED
    assert unchanged["version"] == rescheduling["version"]


# ---------------------------------------------------------------------------
# Instance: weighted_strike_total_suspends_only_at_exactly_the_strike_limit
# ---------------------------------------------------------------------------
def _one_ledger_at_three_and_one_at_two(api):
    """h2 reaches 1 + 2 == 3 across two rows; a2 holds a single row worth 2."""
    s = two_team_league(
        api,
        roster_size=2,
        section_kwargs={
            "min_matches_for_playoff_eligibility": 1,
            "strike_limit": 3,
            "disqualification_strike_limit": 6,
        },
    )
    away_strike = get_success_data(
        api.create_strike(
            f.strike_payload(
                s.player_id("pa2"),
                STRIKE_INELIGIBLE_LINEUP,
                reason="Played on an unactivated spot in a friendly",
            ),
            LEAGUE_COORDINATOR,
        ),
        201,
    )
    home_first = get_success_data(
        api.create_strike(
            f.strike_payload(
                s.player_id("ph2"),
                STRIKE_NO_SHOW_DEFAULT,
                reason="Failed to appear for a rescheduled fixture",
            ),
            LEAGUE_COORDINATOR,
        ),
        201,
    )
    home_second = get_success_data(
        api.create_strike(
            f.strike_payload(
                s.player_id("ph2"),
                STRIKE_INELIGIBLE_LINEUP,
                reason="Second violation: ineligible lineup",
            ),
            LEAGUE_COORDINATOR,
        ),
        201,
    )
    return s, away_strike, home_first, home_second


def test_reaching_the_strike_limit_exactly_suspends_the_player(api):
    """Weights 1 and 2 sum to exactly 3, and the threshold is reached, not passed.

    PRD 3.7: "With the default `strike_limit` of 3, a `NO_SHOW_DEFAULT` weighing 1
    landing on top of an `INELIGIBLE_LINEUP` weighing 2 suspends the player at
    exactly 3 - the threshold is reached, not merely passed."

    Design: Difficulty/boundary_precision_check/weighted_strike_total_suspends_only_at_exactly_the_strike_limit
    """
    s, away_strike, home_first, home_second = _one_ledger_at_three_and_one_at_two(api)
    assert home_first["weight"] == 1
    assert home_second["weight"] == 2
    assert away_strike["weight"] == 2

    h2 = s.refresh_player("ph2")
    assert h2["strike_count"] == 3
    assert h2["status"] == PLAYER_STRIKE_SUSPENDED

    spot = s.refresh_spot("ph2")
    assert spot["status"] == SPOT_INELIGIBLE
    assert spot["ineligible_reason"] == INELIGIBLE_PLAYER_SUSPENDED
    assert spot["source_strike_id"] == home_second["id"]


def test_a_single_heavier_row_below_the_limit_leaves_the_player_active(api):
    """a2 holds weight 2 out of 3 in one row and is not suspended by row count.

    PRD 3.7: "A player's `strike_count` is not a tally of strike rows; it is the
    **sum of the `weight` of every strike charged to that player whose `status` is
    `ACTIVE`**."

    Design: Difficulty/boundary_precision_check/weighted_strike_total_suspends_only_at_exactly_the_strike_limit
    """
    s, _away, _first, _second = _one_ledger_at_three_and_one_at_two(api)

    a2 = s.refresh_player("pa2")
    assert a2["strike_count"] == 2
    assert a2["status"] == PLAYER_ACTIVE

    away_spot = s.refresh_spot("pa2")
    assert away_spot["status"] == SPOT_ACTIVE
    assert away_spot["ineligible_reason"] is None

    home = s.refresh_team("th")
    assert home["active_roster_size"] == 1
    assert home["roster_compliant"] is False
    away = s.refresh_team("ta")
    assert away["active_roster_size"] == 2
    assert away["roster_compliant"] is True
    assert s.refresh_league()["noncompliant_team_count"] == 1
