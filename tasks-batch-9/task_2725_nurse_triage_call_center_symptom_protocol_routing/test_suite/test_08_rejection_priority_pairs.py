"""Ordered rejection: the earlier rule wins even when a later one also holds."""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId


@pytest.fixture
def two_saturated_single_call_nurses(world):
    """Two nurses capped at one call each, both already holding a live call."""
    world.bootstrap(
        clock="2026-08-03T14:30:00Z",
        nurse_keys=("nurse_a", "nurse_b"),
        max_concurrent_calls=1,
    )
    call_one = world.call_through_assignment("nurse_a", reason_text="chest discomfort")
    call_two = world.call_through_assignment("nurse_b", reason_text="sore throat")
    return call_one, call_two


class TestCallStateBeatsNurseCapacity:
    def test_reassigning_an_assigned_call_reports_the_call_state_not_the_capacity(
        self, world, two_saturated_single_call_nurses
    ):
        """PRD §2.12: "Every candidate rejection is evaluated in strictly ascending
        priority order, and the **first** rule whose condition holds produces the
        response; no later rule is evaluated and no state is written."

        Design: Difficulty/priority_pair_validation_conflict/assign_nurse_call_state_priority_17_beats_nurse_capacity_priority_51_rejected
        """
        _, call_two = two_saturated_single_call_nurses

        response = world.api.assign_nurse(
            call_two["id"],
            f.assign_nurse_payload(world.nurse_id("nurse_a")),
            world.intake,
        )

        validate_error(response, ApiErrorId.ERR_CALL_INVALID_STATE, 409)

    def test_the_capacity_error_is_never_the_answer_here(
        self, world, two_saturated_single_call_nurses
    ):
        """PRD §2.12: "51. `ERR_NURSE_AT_CAPACITY` — a `preferred_nurse_id` was
        supplied and that nurse's `active_call_load` is at or above their
        `max_concurrent_calls`. Guards `POST /triage-calls/{id}/assign-nurse`."

        Design: Difficulty/priority_pair_validation_conflict/assign_nurse_call_state_priority_17_beats_nurse_capacity_priority_51_rejected
        """
        _, call_two = two_saturated_single_call_nurses
        saturated = world.nurse("nurse_a")
        assert saturated["active_call_load"] == saturated["max_concurrent_calls"], (
            "the preferred nurse really is at capacity, so both rules apply"
        )

        response = world.api.assign_nurse(
            call_two["id"],
            f.assign_nurse_payload(world.nurse_id("nurse_a")),
            world.intake,
        )

        body = response.json()
        assert body["data"]["error_id"] != ApiErrorId.ERR_NURSE_AT_CAPACITY.value, (
            "priority 17 is evaluated before priority 51, so the later rule is "
            "never reached"
        )

    def test_the_rejected_reassignment_writes_no_state(
        self, world, two_saturated_single_call_nurses
    ):
        """PRD §2.12: "17. `ERR_CALL_INVALID_STATE` — the call's `status` is not in
        the from-set of the requested transition. Guards every triage-call action
        endpoint and `POST /dispositions`."

        Design: Difficulty/priority_pair_validation_conflict/assign_nurse_call_state_priority_17_beats_nurse_capacity_priority_51_rejected
        """
        _, call_two = two_saturated_single_call_nurses

        world.api.assign_nurse(
            call_two["id"],
            f.assign_nurse_payload(world.nurse_id("nurse_a")),
            world.intake,
        )

        after = world.call(call_two["id"])
        assert after["status"] == "ASSIGNED"
        assert after["assigned_nurse_id"] == world.nurse_id("nurse_b")
        assert after["deferred_assignment_count"] == 0
        assert world.nurse("nurse_a")["active_call_load"] == 1
        assert world.nurse("nurse_b")["active_call_load"] == 1


@pytest.fixture
def expired_licence_with_two_assessed_calls(world):
    """Two assessed calls whose nurse's only licence lapses overnight."""
    world.bootstrap(
        clock="2026-08-03T14:30:00Z",
        license_expires_on="2026-08-03",
        protocol={"base_severity": 62},
    )
    call_one, assessment_one = world.call_through_assessment(
        "nurse_a", red_flag_count=1, reason_text="chest discomfort"
    )
    call_two, assessment_two = world.call_through_assessment(
        "nurse_a", red_flag_count=1, reason_text="chest discomfort again"
    )
    world.set_clock("2026-08-04T14:30:00Z")
    return (call_one, assessment_one), (call_two, assessment_two)


class TestLicensureBeatsAssessmentMismatch:
    def test_the_lapsed_licence_is_reported_before_the_mismatched_assessment(
        self, world, expired_licence_with_two_assessed_calls
    ):
        """PRD §2.12: "On the disposition create path, the version handshake at
        position 23 is evaluated *before* the licensure gate at 24, which is itself
        before the documentation gate at 27, which is before the de-escalation gate
        at 28."

        Design: Difficulty/priority_pair_validation_conflict/disposition_licensure_priority_24_beats_assessment_mismatch_priority_34_rejected
        """
        (call_one, _), (_, assessment_two) = expired_licence_with_two_assessed_calls

        response = world.api.create_disposition(
            f.disposition_payload(
                call_one["id"],
                assessment_two["id"],
                "ED_NOW",
                world.call_version(call_one["id"]),
            ),
            world.nurse_headers("nurse_a"),
        )

        validate_error(response, ApiErrorId.ERR_NURSE_NOT_LICENSED_IN_STATE, 409)

    def test_the_mismatch_error_is_never_reached(
        self, world, expired_licence_with_two_assessed_calls
    ):
        """PRD §2.12: "34. `ERR_ASSESSMENT_CALL_MISMATCH` — the referenced
        assessment's `call_id` is not the `call_id` in the body. Guards
        `POST /dispositions`."

        Design: Difficulty/priority_pair_validation_conflict/disposition_licensure_priority_24_beats_assessment_mismatch_priority_34_rejected
        """
        (call_one, _), (call_two, assessment_two) = (
            expired_licence_with_two_assessed_calls
        )
        assert assessment_two["call_id"] == call_two["id"] != call_one["id"], (
            "the cited assessment really does belong to the other call"
        )

        response = world.api.create_disposition(
            f.disposition_payload(
                call_one["id"],
                assessment_two["id"],
                "ED_NOW",
                world.call_version(call_one["id"]),
            ),
            world.nurse_headers("nurse_a"),
        )

        body = response.json()
        assert (
            body["data"]["error_id"] != ApiErrorId.ERR_ASSESSMENT_CALL_MISMATCH.value
        ), "priority 24 fires first, so priority 34 is never evaluated"

    def test_the_licence_has_lapsed_by_the_new_clock_reading(
        self, world, expired_licence_with_two_assessed_calls
    ):
        """PRD §3.2: "a licence with `expires_on` of 2026-08-03 is `ACTIVE` at
        2026-08-03T23:59:00Z and `EXPIRED` at 2026-08-04T00:00:00Z."

        Design: Difficulty/priority_pair_validation_conflict/disposition_licensure_priority_24_beats_assessment_mismatch_priority_34_rejected
        """
        licences = world.licenses("nurse_a")
        rows = licences if isinstance(licences, list) else licences["data"]

        assert len(rows) == 1
        assert rows[0]["expires_on"] == "2026-08-03"
        assert rows[0]["status"] == "EXPIRED"

    def test_the_rejected_disposition_leaves_both_calls_and_assessments_untouched(
        self, world, expired_licence_with_two_assessed_calls
    ):
        """PRD §2.12: "no later rule is evaluated and no state is written."

        Design: Difficulty/priority_pair_validation_conflict/disposition_licensure_priority_24_beats_assessment_mismatch_priority_34_rejected
        """
        (call_one, assessment_one), (_, assessment_two) = (
            expired_licence_with_two_assessed_calls
        )

        world.api.create_disposition(
            f.disposition_payload(
                call_one["id"],
                assessment_two["id"],
                "ED_NOW",
                world.call_version(call_one["id"]),
            ),
            world.nurse_headers("nurse_a"),
        )

        assert world.call(call_one["id"])["status"] == "ASSESSING"
        assert world.assessment(assessment_one["id"])["status"] == "ACTIVE"
        assert world.assessment(assessment_two["id"])["status"] == "ACTIVE"
        _, meta = validate_paginated(world.api.list_dispositions(world.admin))
        assert meta["total_count"] == 0
