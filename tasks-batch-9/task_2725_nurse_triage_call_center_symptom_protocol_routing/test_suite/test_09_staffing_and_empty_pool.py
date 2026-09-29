"""Staffing-adequacy boundaries and the empty licensed candidate pool."""

import pytest

from prd_bench_local_runner.testing import validate_error

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_percentage, assert_whole_minutes


@pytest.fixture
def one_state_roster(world):
    """A part-window California shift, a whole-window Nevada shift, two CA calls."""
    world.bootstrap(
        clock="2026-08-03T14:30:00Z", nurse_keys=("nurse_a",), with_shifts=False
    )
    ca_shift = world.add_shift(
        "nurse_a", start_utc="2026-08-03T14:32:00Z", end_utc="2026-08-03T15:00:00Z"
    )
    world.create_nurse("nurse_d", full_name="Dot Nevins", seniority_level=1)
    world.add_license(
        "nurse_d",
        state_code="NV",
        license_number="NV-44444",
        expires_on="2027-01-31",
    )
    world.add_shift(
        "nurse_d", start_utc="2026-08-03T14:00:00Z", end_utc="2026-08-03T15:00:00Z"
    )
    world.open_call(reason_text="chest discomfort")
    world.open_call(reason_text="chest discomfort in a second caller")
    return ca_shift


class TestStaffingAdequacyBoundaries:
    def test_twenty_eight_scheduled_minutes_against_thirty_five_required_is_strained(
        self, world, one_state_roster
    ):
        """PRD §3.10: "Against those thirty-five required minutes, twenty-eight
        scheduled minutes give a ratio of 80.0 and a posture of `STRAINED`".

        Design: Difficulty/boundary_precision_check/staffing_adequacy_ratio_at_exactly_80_then_one_minute_less_then_zero_demand
        """
        readout = world.staffing_adequacy(
            state_code="CA",
            window_start_utc="2026-08-03T14:00:00Z",
            window_end_utc="2026-08-03T15:00:00Z",
        )

        assert readout["offered_call_count"] == 2
        assert_whole_minutes(readout["required_nurse_minutes"], 35, "required minutes")
        assert_whole_minutes(readout["scheduled_nurse_minutes"], 28, "scheduled minutes")
        assert_percentage(readout["adequacy_ratio_pct"], 80.0, "adequacy_ratio_pct")
        assert readout["staffing_posture"] == "STRAINED", (
            "the 80.0 boundary belongs to STRAINED"
        )

    def test_one_scheduled_minute_less_falls_to_critical_at_seventy_seven_point_one(
        self, world, one_state_roster
    ):
        """PRD §3.10: "twenty-seven scheduled minutes give 77.142857, reported as
        77.1, and a posture of `CRITICAL`".

        Design: Difficulty/boundary_precision_check/staffing_adequacy_ratio_at_exactly_80_then_one_minute_less_then_zero_demand
        """
        readout = world.staffing_adequacy(
            state_code="CA",
            window_start_utc="2026-08-03T14:00:00Z",
            window_end_utc="2026-08-03T14:59:00Z",
        )

        assert readout["offered_call_count"] == 2
        assert_whole_minutes(readout["required_nurse_minutes"], 35, "required minutes")
        assert_whole_minutes(readout["scheduled_nurse_minutes"], 27, "scheduled minutes")
        assert_percentage(readout["adequacy_ratio_pct"], 77.1, "adequacy_ratio_pct")
        assert readout["staffing_posture"] == "CRITICAL"

    def test_zero_demand_is_fully_adequate_rather_than_a_division_error(
        self, world, one_state_roster
    ):
        """PRD §3.10: "`adequacy_ratio_pct` is 100.0 whenever
        `required_nurse_minutes` is zero — the zero-demand case is always fully
        adequate and never a division error".

        Design: Difficulty/boundary_precision_check/staffing_adequacy_ratio_at_exactly_80_then_one_minute_less_then_zero_demand
        """
        readout = world.staffing_adequacy(
            state_code="NV",
            window_start_utc="2026-08-03T14:00:00Z",
            window_end_utc="2026-08-03T15:00:00Z",
        )

        assert readout["offered_call_count"] == 0
        assert_whole_minutes(readout["required_nurse_minutes"], 0, "required minutes")
        assert_whole_minutes(readout["scheduled_nurse_minutes"], 60, "scheduled minutes")
        assert_percentage(readout["adequacy_ratio_pct"], 100.0, "adequacy_ratio_pct")
        assert readout["staffing_posture"] == "ADEQUATE"

    def test_the_out_of_state_shift_contributes_nothing_to_the_queried_state(
        self, world, one_state_roster
    ):
        """PRD §3.10: "A shift whose nurse is licensed only in another state
        contributes zero scheduled minutes and does not appear in
        `licensed_nurse_count`, so adding that nurse to the roster cannot move the
        posture".

        Design: Difficulty/boundary_precision_check/staffing_adequacy_ratio_at_exactly_80_then_one_minute_less_then_zero_demand
        """
        ca_shift = one_state_roster
        assert_whole_minutes(ca_shift["scheduled_minutes"], 28, "shift scheduled_minutes")

        california = world.staffing_adequacy(
            state_code="CA",
            window_start_utc="2026-08-03T14:00:00Z",
            window_end_utc="2026-08-03T15:00:00Z",
        )

        assert california["licensed_nurse_count"] == 1
        assert california["state_code"] == "CA", "the readout echoes its query back"


@pytest.fixture
def consented_call_in_an_unlicensed_state(world):
    """A Nevada caller and a roster licensed only in California."""
    world.bootstrap(clock="2026-08-03T14:30:00Z", nurse_keys=("nurse_a",))
    call = world.call_through_consent(
        caller_state_code="NV", reason_text="chest discomfort"
    )
    return call


class TestEmptyCandidateSetOnlyMovesTheDeferralCounter:
    def test_both_routing_attempts_are_refused_for_want_of_a_licensed_nurse(
        self, world, consented_call_in_an_unlicensed_state
    ):
        """PRD §3.4: "A nurse who holds an active licence in a state other than the
        caller's produces an empty pool and this outcome".

        Design: Difficulty/boundary_precision_check/empty_licensed_candidate_set_cannot_assign_and_only_moves_the_deferral_counter
        """
        call = consented_call_in_an_unlicensed_state

        first = world.api.assign_nurse(call["id"], {}, world.intake)
        second = world.api.assign_nurse(call["id"], {}, world.intake)

        validate_error(first, ApiErrorId.ERR_NO_LICENSED_NURSE_AVAILABLE, 409)
        validate_error(second, ApiErrorId.ERR_NO_LICENSED_NURSE_AVAILABLE, 409)

    def test_the_failed_attempts_are_still_counted_on_the_call(
        self, world, consented_call_in_an_unlicensed_state
    ):
        """PRD §3.4: "`deferred_assignment_count` increases by one and the call's
        `version` increases by one, while `status` stays at `CONSENTED`,
        `assigned_nurse_id` stays absent, and every nurse counter is left
        untouched."

        Design: Difficulty/boundary_precision_check/empty_licensed_candidate_set_cannot_assign_and_only_moves_the_deferral_counter
        """
        call = consented_call_in_an_unlicensed_state
        assert call["deferred_assignment_count"] == 0
        version_before = call["version"]

        world.api.assign_nurse(call["id"], {}, world.intake)
        world.api.assign_nurse(call["id"], {}, world.intake)

        after = world.call(call["id"])
        assert after["status"] == "CONSENTED"
        assert after["assigned_nurse_id"] is None
        assert after["assigned_at"] is None
        assert after["deferred_assignment_count"] == 2
        assert after["version"] > version_before, (
            "each refused attempt still bumps the call version"
        )

    def test_no_nurse_counter_moves_on_the_empty_pool_outcome(
        self, world, consented_call_in_an_unlicensed_state
    ):
        """PRD §2.9: "`Nurse.active_call_load` must at all times equal the number
        of `TriageCall` rows whose assigned nurse is that nurse and whose `status` is
        `ASSIGNED`, `ASSESSING` or `DISPOSITIONED`."

        Design: Difficulty/boundary_precision_check/empty_licensed_candidate_set_cannot_assign_and_only_moves_the_deferral_counter
        """
        call = consented_call_in_an_unlicensed_state

        world.api.assign_nurse(call["id"], {}, world.intake)
        world.api.assign_nurse(call["id"], {}, world.intake)

        nurse = world.nurse("nurse_a")
        assert nurse["active_call_load"] == 0
        assert nurse["pending_high_risk_count"] == 0
        assert nurse["intake_eligibility"] == "ON_ROTATION"
