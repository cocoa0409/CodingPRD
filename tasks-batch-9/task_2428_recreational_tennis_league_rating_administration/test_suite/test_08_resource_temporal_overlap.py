"""Facility-court and team-calendar interval geometries."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import factories as f
from test_helpers.assertions import assert_instant_equals
from test_helpers.api_errors import (
    ERR_FACILITY_COURTS_EXCEEDED,
    ERR_TEAM_DATE_CONFLICT,
)
from test_helpers.constants import (
    RESULT_PENDING,
    SCHED_SCHEDULED,
    SCHED_UNSCHEDULED,
    TEAM_IN_PLAY,
)
from test_helpers.fixtures import Scenario, two_team_league
from test_helpers.test_users import LEAGUE_COORDINATOR


# ---------------------------------------------------------------------------
# Instance: facility_occupancy_extends_past_playing_end_by_the_turnaround_buffer
# ---------------------------------------------------------------------------
def _four_teams_on_a_two_court_facility(api):
    s = Scenario(api)
    s.set_clock("2026-08-01T00:00:00Z")
    s.create_section(min_matches_for_playoff_eligibility=1)
    s.create_facility(court_count=2, turnaround_buffer_minutes=30)
    s.create_league(
        min_active_roster_size=2,
        match_duration_minutes=180,
        allow_same_day_doubleheader=False,
    )
    s.open_registration()

    keys = [f"p{i}" for i in range(1, 9)]
    for key in keys:
        s.add_player(key, level=4.0)
    for index, (team_key, name) in enumerate(
        [("t1", "Team One"), ("t2", "Team Two"), ("t3", "Team Three"), ("t4", "Team Four")]
    ):
        pair = keys[index * 2 : index * 2 + 2]
        s.create_team(team_key, pair[0], name)
        s.fill_roster(team_key, pair)
        s.register_team(team_key)

    s.set_clock("2026-08-08T00:00:00Z")
    s.lock_rosters()
    s.start_play()

    s.create_match("m1", "t1", "t2")
    s.schedule_match("m1", "2026-08-15T18:00:00Z", 2)
    s.create_match("m2", "t3", "t4", round_number=1)
    return s


def test_slot_starting_exactly_at_playing_end_is_still_inside_the_buffer(api):
    """21:00 is M1's playing end but its courts stay busy until 21:30.

    PRD 3.5: "Every match occupies a **half-open interval** that begins at its
    `scheduled_start_at` and ends at that instant advanced by its own league's
    `match_duration_minutes` *plus* the buffer named in
    `turnaround_buffer_minutes` on the facility it occupies."

    Design: Difficulty/resource_temporal_overlap/facility_occupancy_extends_past_playing_end_by_the_turnaround_buffer
    """
    s = _four_teams_on_a_two_court_facility(api)
    m2 = s.matches["m2"]

    response = api.schedule_match(
        m2["id"],
        f.schedule_payload(
            s.facility["id"], "2026-08-15T21:00:00Z", m2["version"], courts_required=2
        ),
        LEAGUE_COORDINATOR,
    )
    validate_error(response, ERR_FACILITY_COURTS_EXCEEDED, 409)
    assert response.json()["data"]["error_id"] != ERR_TEAM_DATE_CONFLICT

    stored = s.refresh_match("m2")
    assert stored["schedule_status"] == SCHED_UNSCHEDULED
    assert stored["result_status"] == RESULT_PENDING
    assert stored["facility_id"] is None
    assert stored["scheduled_start_at"] is None
    assert stored["scheduled_end_at"] is None
    assert stored["version"] == m2["version"]


def test_slot_fifteen_minutes_into_the_buffer_is_rejected_and_leaves_m1_intact(api):
    """21:15 sits strictly inside [18:00, 21:30) so the two courts are gone.

    PRD 3.5: "The service sums the `courts_required` of every occupant whose
    interval intersects the requested interval, and requires that sum plus the
    requested `courts_required` to be at most the facility's `court_count`;
    exceeding it is refused with `ERR_FACILITY_COURTS_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/facility_occupancy_extends_past_playing_end_by_the_turnaround_buffer
    """
    s = _four_teams_on_a_two_court_facility(api)
    m2 = s.matches["m2"]

    validate_error(
        api.schedule_match(
            m2["id"],
            f.schedule_payload(
                s.facility["id"],
                "2026-08-15T21:15:00Z",
                m2["version"],
                courts_required=2,
            ),
            LEAGUE_COORDINATOR,
        ),
        ERR_FACILITY_COURTS_EXCEEDED,
        409,
    )

    m1 = s.refresh_match("m1")
    assert_instant_equals(m1["scheduled_start_at"], "2026-08-15T18:00:00Z")
    assert_instant_equals(m1["scheduled_end_at"], "2026-08-15T21:00:00Z")
    assert m1["courts_required"] == 2
    assert m1["schedule_status"] == SCHED_SCHEDULED
    assert s.refresh_match("m2")["version"] == m2["version"]


# ---------------------------------------------------------------------------
# Instance: team_calendar_rejects_earlier_same_date_slot_and_admits_later_next_date_slot
# ---------------------------------------------------------------------------
def _two_facility_calendar_world(api, allow_doubleheader=False):
    s = two_team_league(
        api,
        roster_size=2,
        league_kwargs={
            "match_duration_minutes": 180,
            "allow_same_day_doubleheader": allow_doubleheader,
        },
    )
    fac2 = s.create_facility(name="Mission Bay Courts", court_count=3)
    s.create_match("m1", "th", "ta", round_number=1)
    s.schedule_match("m1", "2026-08-15T18:00:00Z", 3)
    s.create_match("m2", "ta", "th", round_number=2)
    return s, fac2


def test_calendar_bucket_rejects_a_slot_sixteen_hours_before_the_peer(api):
    """02:00 cannot overlap 18:00 in any interval sense, yet the date collides.

    PRD 3.5: "When the flag is false, which is the default, the rule is a pure
    **UTC calendar-date bucket**: the request is rejected if any peer's
    `scheduled_start_at` falls on the same UTC calendar date as the requested
    start."

    Design: Difficulty/resource_temporal_overlap/team_calendar_rejects_earlier_same_date_slot_and_admits_later_next_date_slot
    """
    s, fac2 = _two_facility_calendar_world(api)
    m2 = s.matches["m2"]

    response = api.schedule_match(
        m2["id"],
        f.schedule_payload(fac2["id"], "2026-08-15T02:00:00Z", m2["version"], 3),
        LEAGUE_COORDINATOR,
    )
    validate_error(response, ERR_TEAM_DATE_CONFLICT, 409)
    error_id = response.json()["data"]["error_id"]
    assert error_id != "ERR_FACILITY_SECTION_MISMATCH"
    assert error_id != ERR_FACILITY_COURTS_EXCEEDED

    stored = s.refresh_match("m2")
    assert stored["schedule_status"] == SCHED_UNSCHEDULED
    assert stored["version"] == m2["version"]


def test_calendar_bucket_admits_a_slot_only_hours_later_on_the_next_utc_date(api):
    """00:30 the next day is 3.5 hours after M1's playing end and is admitted.

    PRD 3.5: "Calendar dates are computed by truncating an instant to its UTC
    calendar date, and separations are measured in whole minutes."

    Design: Difficulty/resource_temporal_overlap/team_calendar_rejects_earlier_same_date_slot_and_admits_later_next_date_slot
    """
    s, fac2 = _two_facility_calendar_world(api)
    m2 = s.matches["m2"]

    data = get_success_data(
        api.schedule_match(
            m2["id"],
            f.schedule_payload(fac2["id"], "2026-08-16T00:30:00Z", m2["version"], 3),
            LEAGUE_COORDINATOR,
        ),
        200,
    )
    assert data["schedule_status"] == SCHED_SCHEDULED
    assert data["facility_id"] == fac2["id"]
    assert_instant_equals(data["scheduled_start_at"], "2026-08-16T00:30:00Z")
    assert_instant_equals(data["scheduled_end_at"], "2026-08-16T03:30:00Z")

    m1 = s.refresh_match("m1")
    assert_instant_equals(m1["scheduled_start_at"], "2026-08-15T18:00:00Z")
    assert m1["facility_id"] == s.facility["id"]
    assert m1["schedule_status"] == SCHED_SCHEDULED
    assert s.refresh_team("th")["status"] == TEAM_IN_PLAY
    assert s.refresh_team("ta")["status"] == TEAM_IN_PLAY


# ---------------------------------------------------------------------------
# Instance: doubleheader_start_to_start_gap_rejects_a_slot_the_court_rule_admits
# ---------------------------------------------------------------------------
def _doubleheader_world(api):
    s = two_team_league(
        api,
        roster_size=2,
        league_kwargs={
            "match_duration_minutes": 180,
            "allow_same_day_doubleheader": True,
        },
    )
    s.create_match("m1", "th", "ta", round_number=1)
    s.schedule_match("m1", "2026-08-15T18:00:00Z", 3)
    s.create_match("m2", "ta", "th", round_number=2)
    return s


def test_doubleheader_gap_of_210_minutes_is_rejected_although_courts_are_free(api):
    """21:30 is exactly the end of M1's court occupancy but only 210 minutes out.

    PRD 3.5: "the request is rejected if any peer's start is within 240 minutes
    - four hours - of the requested start in either direction"

    Design: Difficulty/resource_temporal_overlap/doubleheader_start_to_start_gap_rejects_a_slot_the_court_rule_admits
    """
    s = _doubleheader_world(api)
    m2 = s.matches["m2"]

    response = api.schedule_match(
        m2["id"],
        f.schedule_payload(s.facility["id"], "2026-08-15T21:30:00Z", m2["version"], 3),
        LEAGUE_COORDINATOR,
    )
    validate_error(response, ERR_TEAM_DATE_CONFLICT, 409)
    assert response.json()["data"]["error_id"] != ERR_FACILITY_COURTS_EXCEEDED
    assert s.refresh_match("m2")["schedule_status"] == SCHED_UNSCHEDULED
