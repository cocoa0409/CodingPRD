"""The participant lifecycle is a cycle: re-entry returns a person to the line."""

from test_helpers import (
    IntakePosture,
    ParticipantStatus,
    RetentionOutcome,
    assert_instant_equals,
    assert_participant,
    assert_previous_cycle_cleared,
    factories,
    fixtures,
    make_intake_specialist_headers,
    validate_success,
)


class TestReEntryClosesTheCycle:
    """An early separation, then a return to transitional employment."""

    def test_early_separation_parks_the_participant_as_re_entry_eligible(self, api):
        """A separation inside ninety days sends the person back to the program.

        "The fifth and last hop applies only when `retention_outcome` came out as
        `FAILED_EARLY`: the participant moves `PLACED → RE_ENTRY_ELIGIBLE` with
        `eligible_re_entry_at` stamped from the logical clock."

        Design: Difficulty/non_linear_state_machine/participant_cycle_returns_from_re_entry_to_transitional
        """
        program = fixtures.re_entry_eligible_program(api)

        placement = program["placement"]
        assert placement["retention_outcome"] == RetentionOutcome.FAILED_EARLY
        assert placement["separation_days_after_hire"] == 14

        participant = fixtures.read_participant(api, program["participant"]["id"])
        assert participant["status"] == ParticipantStatus.RE_ENTRY_ELIGIBLE
        assert_instant_equals(
            participant["eligible_re_entry_at"],
            "2026-10-15T00:00:00Z",
            "eligible_re_entry_at",
        )

    def test_re_entry_returns_to_transitional_employment_at_a_fresh_wage(self, api):
        """Re-entry counts the return and overwrites the transitional wage.

        "The transition `RE_ENTRY_ELIGIBLE → TRANSITIONAL_EMPLOYED` increments
        `re_entry_count` by one, restamps `enrolled_at` from the logical clock,
        overwrites `wage_cents_per_hour` with the supplied value, and clears the
        whole previous cycle's evidence: `readiness_certified_by_user_id`,
        `readiness_certified_at`, `graduated_at`, `graduation_wage_cents_per_hour`
        and `eligible_re_entry_at` all become null."

        Design: Difficulty/non_linear_state_machine/participant_cycle_returns_from_re_entry_to_transitional
        """
        program = fixtures.re_entry_eligible_program(api)

        response = api.re_enter_participant(
            program["participant"]["id"],
            factories.re_entry_payload(1700),
            make_intake_specialist_headers(),
        )
        participant = validate_success(response)

        assert_participant(participant)
        assert participant["status"] == ParticipantStatus.TRANSITIONAL_EMPLOYED
        assert participant["re_entry_count"] == 1
        assert participant["wage_cents_per_hour"] == 1700
        assert_instant_equals(
            participant["enrolled_at"], "2026-10-15T00:00:00Z", "enrolled_at"
        )

    def test_re_entry_clears_the_previous_cycle_and_re_occupies_a_slot(self, api):
        """The returning trainee starts from zero and takes a training slot back.

        "`training_slots_filled` is the number of participants on the line whose
        `status` is `TRANSITIONAL_EMPLOYED` or `READY_FOR_GRADUATION`; no other
        participant status occupies a slot."

        Design: Difficulty/non_linear_state_machine/participant_cycle_returns_from_re_entry_to_transitional
        """
        program = fixtures.re_entry_eligible_program(api)

        participant = validate_success(
            api.re_enter_participant(
                program["participant"]["id"],
                factories.re_entry_payload(1700),
                make_intake_specialist_headers(),
            )
        )

        assert_previous_cycle_cleared(participant)

        line = fixtures.read_business_line(api, program["business_line"]["id"])
        assert line["training_slots_filled"] == 1
        assert line["intake_posture"] == IntakePosture.OPEN
