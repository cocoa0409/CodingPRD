"""The re-assessment loop and the four-hop cascade it sets off."""

import pytest

from prd_bench_local_runner.testing import validate_paginated

from test_helpers.assertions import assert_nurse_load


@pytest.fixture
def thrice_assessed_call(world):
    """One call scored three times, each score followed by a disposition."""
    world.bootstrap(clock="2026-08-03T14:30:00Z", protocol={"base_severity": 62})
    call = world.call_through_assignment("nurse_a")
    rounds = []
    for red_flags, level in ((1, "ED_NOW"), (0, "URGENT_CARE_24H"), (3, "EMERGENCY_911")):
        assessment = world.create_assessment(
            call["id"], "nurse_a", red_flag_count=red_flags
        )
        disposition = world.create_disposition(
            call["id"], assessment["id"], level, "nurse_a"
        )
        rounds.append((assessment, disposition))
    return call, rounds


class TestReassessmentCycleRunsTwice:
    def test_only_the_latest_assessment_stays_active(self, world, thrice_assessed_call):
        """PRD §3.5: "An assessment is created with `status` `ACTIVE`, and **only
        one assessment may be `ACTIVE` on a call at a time.**"

        Design: Difficulty/non_linear_state_machine/triage_call_reassessment_cycle_returns_dispositioned_to_assessing_twice
        """
        call, rounds = thrice_assessed_call
        (first, _), (second, _), (third, _) = rounds

        assert world.assessment(first["id"])["status"] == "SUPERSEDED"
        assert world.assessment(second["id"])["status"] == "SUPERSEDED"
        assert world.assessment(third["id"])["status"] == "ACTIVE"
        assert second["acuity_score"] == 62, "no red flags leaves the base severity"
        assert third["acuity_score"] == 86, "three red flags add the capped 24 points"

    def test_the_earlier_dispositions_are_voided_and_the_last_stays_authorized(
        self, world, thrice_assessed_call
    ):
        """PRD §3.6: "A disposition whose `advice_status` is `AUTHORIZED` or
        `OVERRIDDEN` becomes `VOIDED` when the assessment it was built on is
        superseded by a later assessment, or when its call is abandoned."

        Design: Difficulty/non_linear_state_machine/triage_call_reassessment_cycle_returns_dispositioned_to_assessing_twice
        """
        call, rounds = thrice_assessed_call
        (_, first), (_, second), (_, third) = rounds

        assert world.disposition(first["id"])["advice_status"] == "VOIDED"
        assert world.disposition(second["id"])["advice_status"] == "VOIDED"
        assert world.disposition(third["id"])["advice_status"] == "AUTHORIZED"
        assert world.call(call["id"])["status"] == "DISPOSITIONED"

    def test_the_earlier_callback_tasks_are_cancelled_leaving_one_open(
        self, world, thrice_assessed_call
    ):
        """PRD §3.5: "In the fourth hop, because those tasks left the open set, the
        practice's `open_callback_count` is decreased by one for each cancelled
        task."

        Design: Difficulty/non_linear_state_machine/triage_call_reassessment_cycle_returns_dispositioned_to_assessing_twice
        """
        call, rounds = thrice_assessed_call
        (_, first), (_, second), (_, third) = rounds

        assert world.callback_for(first["id"])["status"] == "CANCELLED"
        assert world.callback_for(second["id"])["status"] == "CANCELLED"
        latest = world.callback_for(third["id"])
        assert latest["status"] == "PENDING"
        assert latest["risk_class"] == "HIGH_RISK"
        assert world.practice()["open_callback_count"] == 1

    def test_every_assessment_and_disposition_of_the_call_remains_listable(
        self, world, thrice_assessed_call
    ):
        """PRD §3.5: "Assessment listings may be narrowed by `call_id`, by
        `protocol_id` and by `status`."

        Design: Difficulty/non_linear_state_machine/triage_call_reassessment_cycle_returns_dispositioned_to_assessing_twice
        """
        call, _ = thrice_assessed_call

        assessments, assessment_meta = validate_paginated(
            world.api.list_assessments(world.admin, {"call_id": call["id"]})
        )
        dispositions, disposition_meta = validate_paginated(
            world.api.list_dispositions(world.admin, {"call_id": call["id"]})
        )

        assert assessment_meta["total_count"] == 3
        assert len(assessments) == 3
        assert disposition_meta["total_count"] == 3
        assert len(dispositions) == 3

    def test_the_final_emergency_level_holds_the_warm_transfer_and_high_risk_counter(
        self, world, thrice_assessed_call
    ):
        """PRD §3.6: "the second hop, caused by that flag turning on, increases the
        determining nurse's `pending_high_risk_count` by one".

        Design: Difficulty/non_linear_state_machine/triage_call_reassessment_cycle_returns_dispositioned_to_assessing_twice
        """
        call, _ = thrice_assessed_call

        assert world.call(call["id"])["requires_warm_transfer"] is True
        assert_nurse_load(
            world.nurse("nurse_a"), active=1, high_risk=1, eligibility="ON_ROTATION"
        )


@pytest.fixture
def capped_emergency_call(world):
    """An EMERGENCY_911 call held by a nurse whose high-risk cap is one."""
    world.bootstrap(
        clock="2026-08-03T14:30:00Z",
        protocol={"base_severity": 62},
        high_risk_cap=1,
        max_concurrent_calls=2,
    )
    call = world.call_through_assignment("nurse_a")
    assessment = world.create_assessment(call["id"], "nurse_a", red_flag_count=3)
    disposition = world.create_disposition(
        call["id"], assessment["id"], "EMERGENCY_911", "nurse_a"
    )
    return call, assessment, disposition


class TestReassessmentRestoresFourDownstreamCounters:
    def test_the_emergency_disposition_first_pulls_the_nurse_off_rotation(
        self, world, capped_emergency_call
    ):
        """PRD §3.6: "the third hop, caused by that count reaching the nurse's
        `high_risk_cap`, sets that nurse's `intake_eligibility` to `OFF_ROTATION`,
        which immediately removes them from the routing pool for every subsequent
        call."

        Design: Difficulty/transitive_cascade/reassessment_voids_emergency_disposition_and_restores_four_downstream_counters
        """
        assert_nurse_load(
            world.nurse("nurse_a"), active=1, high_risk=1, eligibility="OFF_ROTATION"
        )
        assert world.practice()["open_callback_count"] == 1

    def test_the_second_assessment_supersedes_the_first_and_voids_its_disposition(
        self, world, capped_emergency_call
    ):
        """PRD §3.5: "In the first hop, the new assessment is created `ACTIVE` and
        the call's previously `ACTIVE` assessment flips to `SUPERSEDED`."

        Design: Difficulty/transitive_cascade/reassessment_voids_emergency_disposition_and_restores_four_downstream_counters
        """
        call, first_assessment, disposition = capped_emergency_call

        second_assessment = world.create_assessment(
            call["id"], "nurse_a", red_flag_count=0
        )

        assert world.assessment(first_assessment["id"])["status"] == "SUPERSEDED"
        assert second_assessment["status"] == "ACTIVE"
        assert second_assessment["acuity_score"] == 62
        voided = world.disposition(disposition["id"])
        assert voided["advice_status"] == "VOIDED"
        assert voided["requires_callback"] is True, (
            "the callback obligation stored on the disposition is not rewritten"
        )

    def test_the_cascade_cancels_the_callback_and_clears_the_warm_transfer_hold(
        self, world, capped_emergency_call
    ):
        """PRD §3.5: "where such a disposition had set the call's
        `requires_warm_transfer`, that flag is cleared, the determining nurse's
        `pending_high_risk_count` is decreased by one, and that nurse's
        `intake_eligibility` returns to `ON_ROTATION` once the count falls below
        their `high_risk_cap`."

        Design: Difficulty/transitive_cascade/reassessment_voids_emergency_disposition_and_restores_four_downstream_counters
        """
        call, _, disposition = capped_emergency_call

        world.create_assessment(call["id"], "nurse_a", red_flag_count=0)

        assert world.callback_for(disposition["id"])["status"] == "CANCELLED"
        assert world.practice()["open_callback_count"] == 0
        assert_nurse_load(
            world.nurse("nurse_a"), active=1, high_risk=0, eligibility="ON_ROTATION"
        )
        reassessed = world.call(call["id"])
        assert reassessed["requires_warm_transfer"] is False
        assert reassessed["status"] == "ASSESSING"
