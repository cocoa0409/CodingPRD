"""Observation staffing: the ceiling is taken per episode, then the ceilings add.

Two twenty-minute episodes are the cleanest place to see the rounding order,
because summing the minutes first and ceiling once would lose a quarter hour.
"""

from test_helpers import (
    InterventionType,
    RestraintStatus,
    active_restraint,
    assert_billable_status,
    assert_observation_quarter_hours,
    read_admission,
    release_restraint,
    set_clock,
    voluntary_placed_admission,
)

EPISODE_MINUTES = 20
FIRST_RELEASE = "2026-09-03T08:20:00Z"
SECOND_START = "2026-09-03T08:30:00Z"
SECOND_RELEASE = "2026-09-03T08:50:00Z"


def _placed_admission(api, roster, ward):
    """A voluntary patient in the first bed of the ward."""
    return voluntary_placed_admission(
        api,
        roster,
        ward,
        mrn="MRN-2367-Q1",
        legal_name="Quinn Baird",
        age_years=40,
        gender_care_category="MALE",
        bed_id=ward.beds[0]["id"],
    )


def _episode_of_twenty_minutes(api, roster, admission_id, release_at):
    """Order, authorize and release one twenty-minute mechanical restraint."""
    episode = active_restraint(
        api,
        roster,
        admission_id,
        InterventionType.MECHANICAL_RESTRAINT.value,
        EPISODE_MINUTES,
    )
    return release_restraint(api, roster, episode["id"], release_clock=release_at)


class TestObservationStaffingRounding:
    """Per-episode ceilings, added afterwards — never a single ceiling over the sum."""

    def test_one_twenty_minute_episode_bills_two_quarter_hours(
        self, api, clock, roster, ward
    ):
        """Twenty minutes of restraint rounds up to two quarter hours on its own.

        PRD 3.6: "`observation_staff_quarter_hours` is the sum, over every
        episode of that admission whose `status` is `RELEASED`, `DEBRIEFED` or
        `EXPIRED_UNAUTHORIZED`, of that episode's `actual_duration_minutes`
        divided by 15 and rounded up to the next whole number."

        Design: Difficulty/combinatorial_formula/observation_quarter_hours_per_episode_ceiling_before_sum
        """
        case = _placed_admission(api, roster, ward)
        released = _episode_of_twenty_minutes(
            api, roster, case["admission"]["id"], FIRST_RELEASE
        )

        assert released["actual_duration_minutes"] == EPISODE_MINUTES
        assert released["required_check_count"] == 2
        assert released["status"] == RestraintStatus.RELEASED.value
        assert_billable_status(released["status"])

        admission = read_admission(api, case["admission"]["id"])
        assert admission["observation_staff_quarter_hours"] == 2

    def test_two_twenty_minute_episodes_bill_four_quarter_hours_and_not_three(
        self, api, clock, roster, ward
    ):
        """Ceiling each episode first yields four; ceiling the forty-minute sum would yield three.

        PRD 3.6: "**The rounding order is pinned: the ceiling is taken per
        episode and the per-episode ceilings are then added.** Summing the raw
        minutes first and taking a single ceiling is
        wrong — two 20-minute episodes contribute two quarter-hours each, for a
        total of four, not the three that a single ceiling over 40 minutes would
        give."

        Design: Difficulty/combinatorial_formula/observation_quarter_hours_per_episode_ceiling_before_sum
        """
        case = _placed_admission(api, roster, ward)
        first = _episode_of_twenty_minutes(
            api, roster, case["admission"]["id"], FIRST_RELEASE
        )
        set_clock(api, SECOND_START)
        second = _episode_of_twenty_minutes(
            api, roster, case["admission"]["id"], SECOND_RELEASE
        )

        assert first["actual_duration_minutes"] == EPISODE_MINUTES
        assert second["actual_duration_minutes"] == EPISODE_MINUTES
        assert second["required_check_count"] == 2

        admission = read_admission(api, case["admission"]["id"])
        assert_observation_quarter_hours(admission, [EPISODE_MINUTES, EPISODE_MINUTES])
        assert admission["observation_staff_quarter_hours"] == 4
        assert admission["observation_staff_quarter_hours"] != 3
