"""
Contended resources across time: overlapping competition windows and the
assessor's per-calendar-day assessment capacity.

Two behaviours in the requirements guard a resource that is contended over a
span of time rather than at a single instant.

The first is the wrestler as the contended resource.  Section 3.7 declares that
a wrestler "must not already hold a non-``SCRATCHED`` entry on another event
whose half-open competition window overlaps this event's window", refused as
``ERR_ENTRY_WINDOW_CONFLICT``, and that "adjacency with a gap of exactly zero
days is permitted, so an event ending at the instant another begins is fine".
The window itself is declared alongside ``competition_days`` in section 3.7: it
"opens at midnight UTC on ``event_date`` and closes at midnight UTC that many
days later", so a two-day event beginning 2026-12-12 occupies
[2026-12-12, 2026-12-14) and a one-day event on 2026-12-14 begins exactly where
that window ends.

The second is the assessor as the contended resource, under different temporal
semantics: section 3.3 requires that "the assessor must have fewer than
``assessor_daily_assessment_capacity`` non-voided assessments already recorded
whose ``assessed_at`` falls on the same UTC calendar day as the new one, counted
across every wrestler and every team the assessor works with", exceeding which
is ``ERR_ASSESSOR_DAY_CAPACITY_EXCEEDED``.  The bound is a count inside one UTC
calendar-day bucket, so the boundary that matters is the day edge.
"""

import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import api_errors, constants, factories, fixtures
from test_helpers.assertions import assert_instant_equals, assert_row_count
from test_helpers.test_users import STATE_OFFICE, assessor_headers, coach_headers

# ── The three competition windows section 3.7 derives ────────────────
# "Region Duals" is a two-day event, so it occupies [2026-12-12, 2026-12-14).
TWO_DAY_EVENT_DATE = "2026-12-12"
TWO_DAY_COMPETITION_DAYS = 2
# "Winter Classic" is a one-day event lying strictly inside that window.
OVERLAP_EVENT_DATE = "2026-12-13"
# "New Year Duals" is a one-day event starting exactly where the two-day window
# closes — a gap of exactly zero days.
ADJACENT_EVENT_DATE = "2026-12-14"

ENTRY_CLASS_LBS = constants.CANON_TARGET_CLASS_LBS
ENTRY_SEASON_WINS = 6

# ── The assessed_at instants inside and outside one UTC day bucket ────
DAY_ONE_INSTANTS = (
    "2026-11-01T08:00:00Z",
    "2026-11-01T12:00:00Z",
    "2026-11-01T23:00:00Z",
)
FOURTH_SAME_DAY_INSTANT = "2026-11-01T23:59:30Z"
NEXT_DAY_INSTANT = "2026-11-02T00:00:00Z"
SETUP_CLOCK_INSTANT = "2026-11-01T23:59:59Z"

# The three readings already on the books for 2026-11-01, one per wrestler.
DAY_ONE_READINGS = (
    (159.6, 14.0, 1.020),
    (172.0, 16.0, 1.018),
    (200.0, 20.0, 1.015),
)
# The reading the fourth attempt carries, byte-identical across both attempts.
FOURTH_READING = (138.0, 22.0, 1.016)

DAY_CAPACITY = 3


# ── Local builders ───────────────────────────────────────────────────

def _competition_windows_scenario(api):
    """A certified wrestler and the three events whose windows are compared.

    The canonical chain of section 3.5 leaves Alex Mercer certified on a
    ``WEEKLY_STEP`` plan built from a 159.6 pound baseline at a 1.5 percent
    weekly rate toward the 150 pound class, whose last milestone falls on
    2026-12-07 at 147.9 pounds.  No growth allowance is published, so on every
    date from 2026-12-12 onward his eligibility floor is the larger of his
    147.6 pound certified minimum and that 147.9 pound schedule value, and the
    smallest class at or above it — 150 — is the class every entry below uses.
    """
    scenario = fixtures.certified_wrestler(api)
    scenario.event_two_day = fixtures.create_event(
        api,
        scenario.season_id,
        "Region Duals",
        TWO_DAY_EVENT_DATE,
        constants.EVENT_TYPE_DUAL,
        competition_days=TWO_DAY_COMPETITION_DAYS,
        weigh_in_days=2,
        consecutive_day_allowance_lbs=1.0,
    )
    scenario.event_overlap = fixtures.create_event(
        api,
        scenario.season_id,
        "Winter Classic",
        OVERLAP_EVENT_DATE,
        constants.EVENT_TYPE_TOURNAMENT,
        competition_days=1,
        weigh_in_days=1,
    )
    scenario.event_adjacent = fixtures.create_event(
        api,
        scenario.season_id,
        "New Year Duals",
        ADJACENT_EVENT_DATE,
        constants.EVENT_TYPE_DUAL,
        competition_days=1,
        weigh_in_days=1,
    )
    return scenario


def _enter(api, scenario, event):
    """Attempt an entry for the scenario's wrestler, acting as their coach."""
    return api.create_entry(
        event["id"],
        factories.entry_payload(
            scenario.wrestler_id, ENTRY_CLASS_LBS, season_win_count=ENTRY_SEASON_WINS
        ),
        coach_headers(scenario.team_id),
    )


def _entry_count(api, event_id):
    return fixtures.read_event(api, event_id)["entry_count"]


def _capacity_scenario(api):
    """One assessor at capacity 3 with three assessments on 2026-11-01.

    The four wrestlers are spread over two teams so that the aggregation the
    requirements describe — "across every wrestler and every team the assessor
    works with" — is observable as assessor-scoped rather than team-scoped.
    """
    scenario = fixtures.open_season_with_team(
        api,
        school_name=constants.DEFAULT_TEAM_NAME,
        clock=SETUP_CLOCK_INSTANT,
        assessor_daily_assessment_capacity=DAY_CAPACITY,
    )
    scenario.team_north_id = scenario.team_id
    scenario.team_south = fixtures.create_team(
        api, scenario.season_id, constants.SECOND_TEAM_NAME
    )
    scenario.team_south_id = scenario.team_south["id"]

    assessor = fixtures.create_certified_assessor(api)
    scenario.assessor = assessor
    scenario.assessor_id = assessor["id"]

    roster = (
        ("Alex Mercer", constants.SEX_MALE, 11, scenario.team_north_id),
        ("Blake Ito", constants.SEX_MALE, 12, scenario.team_north_id),
        ("Casey Lund", constants.SEX_MALE, 10, scenario.team_south_id),
        ("Devon Park", constants.SEX_FEMALE, 11, scenario.team_south_id),
    )
    scenario.wrestler_ids = [
        fixtures.create_wrestler(api, team_id, full_name, sex, grade)["id"]
        for full_name, sex, grade, team_id in roster
    ]
    scenario.wrestler_d_id = scenario.wrestler_ids[3]

    scenario.day_one_assessments = [
        fixtures.create_assessment(
            api,
            wrestler_id,
            scenario.assessor_id,
            method=constants.METHOD_SKINFOLD,
            assessed_at=assessed_at,
            measured_weight_lbs=reading[0],
            body_fat_pct=reading[1],
            urine_specific_gravity=reading[2],
        )
        for wrestler_id, assessed_at, reading in zip(
            scenario.wrestler_ids, DAY_ONE_INSTANTS, DAY_ONE_READINGS
        )
    ]
    return scenario


def _fourth_attempt(api, scenario, assessed_at, assessor_id=None):
    """The fourth assessment attempt of the day, aimed at the other team."""
    acting_id = assessor_id or scenario.assessor_id
    measured, body_fat, gravity = FOURTH_READING
    return api.create_assessment(
        scenario.wrestler_d_id,
        factories.assessment_payload(
            assessor_id=acting_id,
            method=constants.METHOD_SKINFOLD,
            assessed_at=assessed_at,
            measured_weight_lbs=measured,
            body_fat_pct=body_fat,
            urine_specific_gravity=gravity,
        ),
        assessor_headers(acting_id),
    )


# ── The wrestler as the contended resource: half-open windows ────────

@pytest.mark.parametrize(
    "first_event_key, second_event_key",
    [
        ("event_two_day", "event_overlap"),
        ("event_overlap", "event_two_day"),
    ],
    ids=["two_day_held_first", "one_day_held_first"],
)
def test_overlapping_competition_windows_refuse_the_second_entry(
    api, first_event_key, second_event_key
):
    """A second entry whose competition window overlaps a held one is refused.

    Section 3.7 forbids a wrestler from holding a non-``SCRATCHED`` entry on
    another event whose half-open competition window overlaps the window of the
    event being entered, and names the refusal ``ERR_ENTRY_WINDOW_CONFLICT``.
    The two-day event beginning 2026-12-12 occupies [2026-12-12, 2026-12-14)
    under the window definition attached to ``competition_days``, and the
    one-day event on 2026-12-13 occupies [2026-12-13, 2026-12-14), which lies
    strictly inside it.  The requirement is stated over the pair of windows, so
    it holds whichever of the two entries the wrestler already holds.

    Design: Difficulty/resource_temporal_overlap/wrestler_competition_window_half_open_overlap
    """
    scenario = _competition_windows_scenario(api)

    held = validate_success(_enter(api, scenario, scenario[first_event_key]), 201)
    assert held["status"] == constants.ENTRY_ENTERED

    refused = _enter(api, scenario, scenario[second_event_key])
    validate_error(refused, api_errors.ERR_ENTRY_WINDOW_CONFLICT, 409)


def test_refused_overlapping_entry_leaves_no_row_and_no_counter_movement(api):
    """The refused overlapping entry is never persisted anywhere.

    Section 3.7 has a successful entry land in ``ENTERED`` and increment the
    event's ``entry_count``; an entry refused for a window conflict does
    neither, so the contested event stays at zero entries and its entry listing
    stays empty, while the entry the wrestler already held is untouched.

    Design: Difficulty/resource_temporal_overlap/wrestler_competition_window_half_open_overlap
    """
    scenario = _competition_windows_scenario(api)
    held = validate_success(_enter(api, scenario, scenario.event_two_day), 201)

    validate_error(
        _enter(api, scenario, scenario.event_overlap),
        api_errors.ERR_ENTRY_WINDOW_CONFLICT,
        409,
    )

    assert _entry_count(api, scenario.event_overlap["id"]) == 0
    assert_row_count(
        api.list_entries(
            STATE_OFFICE, {"event_id": scenario.event_overlap["id"], "limit": 100}
        ),
        0,
        "entries of the overlapping event",
    )

    assert _entry_count(api, scenario.event_two_day["id"]) == 1
    unchanged = fixtures.read_entry(api, held["id"])
    assert unchanged["status"] == constants.ENTRY_ENTERED
    assert unchanged["weight_class_lbs"] == ENTRY_CLASS_LBS


def test_zero_day_gap_between_windows_is_permitted(api):
    """An event beginning exactly where another ends is not a conflict.

    Section 3.7 states that adjacency with a gap of exactly zero days is
    permitted, "so an event ending at the instant another begins is fine".  The
    two-day window [2026-12-12, 2026-12-14) is half-open, and the one-day event
    on 2026-12-14 occupies [2026-12-14, 2026-12-15), whose inclusive start is
    the exclusive end of the first window, so the entry is accepted and each
    event counts exactly one entry.

    Design: Difficulty/resource_temporal_overlap/wrestler_competition_window_half_open_overlap
    """
    scenario = _competition_windows_scenario(api)
    validate_success(_enter(api, scenario, scenario.event_two_day), 201)

    adjacent = validate_success(_enter(api, scenario, scenario.event_adjacent), 201)
    assert adjacent["status"] == constants.ENTRY_ENTERED
    assert adjacent["event_id"] == scenario.event_adjacent["id"]
    assert adjacent["wrestler_id"] == scenario.wrestler_id

    assert _entry_count(api, scenario.event_adjacent["id"]) == 1
    assert _entry_count(api, scenario.event_two_day["id"]) == 1


def test_wrestler_holds_both_disjoint_entries_after_the_refused_overlap(api):
    """Across the whole sequence the wrestler keeps exactly two live entries.

    The overlapping attempt of section 3.7 is refused and the adjacent one
    accepted, so the wrestler's cross-event entry listing carries exactly the
    two-day event's entry and the adjacent event's entry, both in ``ENTERED``.

    Design: Difficulty/resource_temporal_overlap/wrestler_competition_window_half_open_overlap
    """
    scenario = _competition_windows_scenario(api)
    two_day_entry = validate_success(
        _enter(api, scenario, scenario.event_two_day), 201
    )

    validate_error(
        _enter(api, scenario, scenario.event_overlap),
        api_errors.ERR_ENTRY_WINDOW_CONFLICT,
        409,
    )
    adjacent = validate_success(_enter(api, scenario, scenario.event_adjacent), 201)

    rows = assert_row_count(
        api.list_entries(
            STATE_OFFICE, {"wrestler_id": scenario.wrestler_id, "limit": 100}
        ),
        2,
        "entries of the wrestler",
    )
    assert {row["id"] for row in rows} == {two_day_entry["id"], adjacent["id"]}
    assert [row["status"] for row in rows] == [
        constants.ENTRY_ENTERED,
        constants.ENTRY_ENTERED,
    ]
    assert {row["event_id"] for row in rows} == {
        scenario.event_two_day["id"],
        scenario.event_adjacent["id"],
    }


# ── The assessor as the contended resource: one UTC day bucket ───────

def test_fourth_assessment_in_the_same_utc_day_is_refused(api):
    """The day bucket is aggregated across every wrestler and every team.

    Section 3.3 requires the acting assessor to have fewer than
    ``assessor_daily_assessment_capacity`` non-voided assessments already
    recorded whose ``assessed_at`` falls on the same UTC calendar day as the new
    one, counted across every wrestler and every team the assessor works with,
    and refuses the excess with ``ERR_ASSESSOR_DAY_CAPACITY_EXCEEDED``.  Three
    assessments already sit on 2026-11-01 against wrestlers of one team, so a
    fourth on that day is refused even though it names a wrestler on the other
    team and no two of the four instants coincide.

    Design: Difficulty/resource_temporal_overlap/assessor_daily_aggregate_capacity
    """
    scenario = _capacity_scenario(api)
    # The season carries the capacity the requirements read, and the fourth
    # wrestler sits on the other team's roster.
    season = get_success_data(api.get_season(scenario.season_id, STATE_OFFICE))
    assert season["assessor_daily_assessment_capacity"] == DAY_CAPACITY
    assert (
        fixtures.read_wrestler(api, scenario.wrestler_d_id)["team_id"]
        == scenario.team_south_id
    )
    assert scenario.team_south_id != scenario.team_north_id
    assert [row["status"] for row in scenario.day_one_assessments] == [
        constants.ASSESSMENT_DRAFT
    ] * DAY_CAPACITY

    refused = _fourth_attempt(api, scenario, FOURTH_SAME_DAY_INSTANT)
    validate_error(refused, api_errors.ERR_ASSESSOR_DAY_CAPACITY_EXCEEDED, 409)


def test_refused_capacity_assessment_is_never_persisted(api):
    """A capacity refusal leaves the day's three recorded assessments alone.

    Section 3.3 has a created assessment land in ``DRAFT``; the refused fourth
    creates nothing, so the assessor's filtered assessment listing still carries
    exactly the three rows of 2026-11-01, each still ``DRAFT`` at the instant it
    was recorded, and the wrestler the refused attempt named has no assessment
    at all.

    Design: Difficulty/resource_temporal_overlap/assessor_daily_aggregate_capacity
    """
    scenario = _capacity_scenario(api)

    validate_error(
        _fourth_attempt(api, scenario, FOURTH_SAME_DAY_INSTANT),
        api_errors.ERR_ASSESSOR_DAY_CAPACITY_EXCEEDED,
        409,
    )

    rows = assert_row_count(
        api.list_assessments(
            STATE_OFFICE, {"assessor_id": scenario.assessor_id, "limit": 100}
        ),
        DAY_CAPACITY,
        "assessments of the assessor",
    )
    assert {row["id"] for row in rows} == {
        row["id"] for row in scenario.day_one_assessments
    }
    for recorded, instant in zip(scenario.day_one_assessments, DAY_ONE_INSTANTS):
        still_open = fixtures.read_assessment(api, recorded["id"])
        assert still_open["status"] == constants.ASSESSMENT_DRAFT
        assert_instant_equals(still_open["assessed_at"], instant, "assessed_at")

    assert_row_count(
        api.list_assessments(
            STATE_OFFICE, {"wrestler_id": scenario.wrestler_d_id, "limit": 100}
        ),
        0,
        "assessments of the fourth wrestler",
    )


def test_next_utc_day_bucket_accepts_the_identical_reading(api):
    """Thirty seconds later, in the next day bucket, the same payload lands.

    The bound of section 3.3 is a count inside one UTC calendar day of
    ``assessed_at``, so the reading refused at 2026-11-01T23:59:30Z is accepted
    unchanged at 2026-11-02T00:00:00Z, where the assessor holds no assessment
    yet.  The new row lands in ``DRAFT`` and the assessor's listing grows to
    four.

    Design: Difficulty/resource_temporal_overlap/assessor_daily_aggregate_capacity
    """
    scenario = _capacity_scenario(api)
    validate_error(
        _fourth_attempt(api, scenario, FOURTH_SAME_DAY_INSTANT),
        api_errors.ERR_ASSESSOR_DAY_CAPACITY_EXCEEDED,
        409,
    )

    fixtures.move_clock(api, NEXT_DAY_INSTANT)
    accepted = validate_success(
        _fourth_attempt(api, scenario, NEXT_DAY_INSTANT), 201
    )

    assert accepted["status"] == constants.ASSESSMENT_DRAFT
    assert accepted["assessor_id"] == scenario.assessor_id
    assert accepted["wrestler_id"] == scenario.wrestler_d_id
    assert_instant_equals(accepted["assessed_at"], NEXT_DAY_INSTANT, "assessed_at")

    assert_row_count(
        api.list_assessments(
            STATE_OFFICE, {"assessor_id": scenario.assessor_id, "limit": 100}
        ),
        DAY_CAPACITY + 1,
        "assessments of the assessor",
    )
    rows = assert_row_count(
        api.list_assessments(
            STATE_OFFICE, {"wrestler_id": scenario.wrestler_d_id, "limit": 100}
        ),
        1,
        "assessments of the fourth wrestler",
    )
    assert rows[0]["id"] == accepted["id"]


def test_day_capacity_is_counted_per_assessor(api):
    """The bucket belongs to the acting assessor, not to the calendar day.

    Section 3.3 scopes the count to the assessments the acting assessor has
    already recorded.  A second credentialed assessor who has recorded nothing
    on 2026-11-01 may therefore take the very reading the first assessor was
    refused, on the same UTC day and against the same wrestler.

    Design: Difficulty/resource_temporal_overlap/assessor_daily_aggregate_capacity
    """
    scenario = _capacity_scenario(api)
    validate_error(
        _fourth_attempt(api, scenario, FOURTH_SAME_DAY_INSTANT),
        api_errors.ERR_ASSESSOR_DAY_CAPACITY_EXCEEDED,
        409,
    )

    second = fixtures.create_certified_assessor(
        api, full_name="Ravi Chandra", credential_number="AS-1002"
    )
    accepted = validate_success(
        _fourth_attempt(
            api, scenario, FOURTH_SAME_DAY_INSTANT, assessor_id=second["id"]
        ),
        201,
    )

    assert accepted["status"] == constants.ASSESSMENT_DRAFT
    assert accepted["assessor_id"] == second["id"]
    assert_instant_equals(
        accepted["assessed_at"], FOURTH_SAME_DAY_INSTANT, "assessed_at"
    )

    assert_row_count(
        api.list_assessments(STATE_OFFICE, {"assessor_id": second["id"], "limit": 100}),
        1,
        "assessments of the second assessor",
    )
    assert_row_count(
        api.list_assessments(
            STATE_OFFICE, {"assessor_id": scenario.assessor_id, "limit": 100}
        ),
        DAY_CAPACITY,
        "assessments of the first assessor",
    )
