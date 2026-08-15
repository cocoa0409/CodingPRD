"""Milestone evaluation: the inclusive due boundary, direction-aware
comparisons, and the empty-FINAL-set MISSED rule."""
import pytest

from test_helpers import (
    get_success_data,
    validate_success,
)
from test_helpers.fixtures import (
    record_and_validate,
    record_observation,
    set_clock,
    setup_observation_world,
)
from test_helpers.test_users import DIRECTOR, LEAD


class TestMilestoneBoundary:
    def test_milestone_due_inclusive_boundary(self, api):
        """PRD section 3.8: "Every `PENDING` milestone of the cycle whose
        `due_date` is on or before the current logical time - an inclusive
        boundary - is evaluated against the FINAL variant of attainment for
        its indicator in this cycle". "Milestones whose `due_date` lies in
        the future remain `PENDING`, are untouched, and are not counted in
        the batch tallies; the response reports `evaluated_count`,
        `met_count`, and `missed_count`."

        Design: Difficulty/boundary_precision_check/milestone_due_inclusive_boundary
        """
        world = setup_observation_world(
            program_name="Workforce", program_code="WKF",
            indicator_specs=[{
                "code": "I1", "measurement_frequency": "MONTHLY",
            }])
        ind = world["indicators"]["I1"]
        record_and_validate(world["participant"]["id"], ind["id"],
                            world["instrument"]["id"], value=75)

        m1 = get_success_data(api.create_milestone(
            world["cycle"]["id"],
            {"indicator_id": ind["id"],
             "due_date": "2026-08-15T00:00:00Z",
             "milestone_target": 70},
            LEAD))
        m2 = get_success_data(api.create_milestone(
            world["cycle"]["id"],
            {"indicator_id": ind["id"],
             "due_date": "2026-08-15T00:00:01Z",
             "milestone_target": 70},
            LEAD))

        set_clock("2026-08-15T00:00:00Z")
        result = get_success_data(
            api.evaluate_milestones(world["cycle"]["id"], DIRECTOR))
        assert result["evaluated_count"] == 1
        assert result["met_count"] == 1
        assert result["missed_count"] == 0

        m1_after = get_success_data(api.get_milestone(m1["id"], LEAD))
        assert m1_after["status"] == "MET"

        m2_after = get_success_data(api.get_milestone(m2["id"], LEAD))
        assert m2_after["status"] == "PENDING"

    def test_milestone_one_second_before_due_not_evaluated(self, api):
        """PRD section 3.8: "Milestones whose `due_date` lies in the future
        remain `PENDING`, are untouched, and are not counted in the batch
        tallies".

        Design: Difficulty/boundary_precision_check/milestone_due_inclusive_boundary
        """
        world = setup_observation_world(
            program_name="Workforce2", program_code="WK2",
            indicator_specs=[{
                "code": "I1", "measurement_frequency": "MONTHLY",
            }])
        ind = world["indicators"]["I1"]
        record_and_validate(world["participant"]["id"], ind["id"],
                            world["instrument"]["id"], value=75)

        m1 = get_success_data(api.create_milestone(
            world["cycle"]["id"],
            {"indicator_id": ind["id"],
             "due_date": "2026-08-15T00:00:00Z",
             "milestone_target": 70},
            LEAD))

        # One second before due: not yet evaluable.
        set_clock("2026-08-14T23:59:59Z")
        result = get_success_data(
            api.evaluate_milestones(world["cycle"]["id"], DIRECTOR))
        assert result["evaluated_count"] == 0

        m1_after = get_success_data(api.get_milestone(m1["id"], LEAD))
        assert m1_after["status"] == "PENDING"


class TestMilestoneDirection:
    def test_milestone_lower_is_better_met(self, api):
        """PRD section 3.8: "for `HIGHER_IS_BETTER`, the milestone becomes
        `MET` when the aggregated value is at least `milestone_target`; for
        `LOWER_IS_BETTER`, when it is at most `milestone_target`; failing the
        comparison means `MISSED`."

        Design: Corner/calculations/milestone_lower_is_better_met
        """
        world = setup_observation_world(
            program_name="Lower", program_code="LWR",
            indicator_specs=[{
                "code": "L1", "unit": "COUNT", "direction": "LOWER_IS_BETTER",
                "baseline_value": 100, "target_value": 0,
                "measurement_frequency": "END_OF_CYCLE",
            }])
        ind = world["indicators"]["L1"]
        record_and_validate(world["participant"]["id"], ind["id"],
                            world["instrument"]["id"], value=30)

        milestone = get_success_data(api.create_milestone(
            world["cycle"]["id"],
            {"indicator_id": ind["id"],
             "due_date": "2026-08-01T00:00:00Z",
             "milestone_target": 40},
            LEAD))

        result = get_success_data(
            api.evaluate_milestones(world["cycle"]["id"], DIRECTOR))
        assert result["met_count"] == 1

        milestone_after = get_success_data(api.get_milestone(milestone["id"], LEAD))
        assert milestone_after["status"] == "MET"

    def test_milestone_without_validated_obs_missed(self, api):
        """PRD section 3.8: "If that aggregated value does not exist (no
        `VALIDATED` observations), the milestone becomes `MISSED`."

        Design: Corner/calculations/milestone_without_validated_obs_missed
        """
        world = setup_observation_world(
            program_name="Missed", program_code="MSD",
            indicator_specs=[{
                "code": "I1", "measurement_frequency": "END_OF_CYCLE",
            }])
        ind = world["indicators"]["I1"]
        # Record but never validate -> FINAL input set empty.
        record_observation(world["participant"]["id"], ind["id"],
                           world["instrument"]["id"], value=99)

        milestone = get_success_data(api.create_milestone(
            world["cycle"]["id"],
            {"indicator_id": ind["id"],
             "due_date": "2026-08-01T00:00:00Z",
             "milestone_target": 50},
            LEAD))

        result = get_success_data(
            api.evaluate_milestones(world["cycle"]["id"], DIRECTOR))
        assert result["missed_count"] == 1

        milestone_after = get_success_data(api.get_milestone(milestone["id"], LEAD))
        assert milestone_after["status"] == "MISSED"
