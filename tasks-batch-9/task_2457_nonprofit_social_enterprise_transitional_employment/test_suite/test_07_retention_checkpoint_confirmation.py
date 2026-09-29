"""The 180-day confirmation cascade: retention, wage evidence and alumni status."""

from test_helpers import (
    CheckpointStatus,
    EmploymentStatus,
    ParticipantStatus,
    RetentionOutcome,
    WageVerificationStatus,
    assert_checkpoint_schedule,
    assert_instant_equals,
    assert_ratio,
    assert_retention_checkpoint,
    fixtures,
)


class TestOneHundredEightyDayConfirmation:
    """The 30- and 90-day answers are in; the 180-day answer completes the story."""

    def test_the_schedule_holds_four_checkpoints_in_ascending_interval_order(self, api):
        """Creating a placement creates exactly four checkpoints, and only that way.

        "Creating a placement therefore creates exactly four retention checkpoints
        and no operation ever creates one any other way. One row exists per
        follow-up interval, at 30, 90, 180 and 365 days, and each row records its
        `placement_id`, its `interval_days` and a `due_date` equal to the
        placement's `hire_date` plus that many whole days, landing on `00:00:00Z`."

        Design: Difficulty/transitive_cascade/checkpoint_180_confirm_retains_placement_and_alumni
        """
        program = fixtures.placed_participant_program(api)

        assert_checkpoint_schedule(program["checkpoints"], "2026-10-01T00:00:00Z")
        for checkpoint in program["checkpoints"]:
            assert checkpoint["placement_id"] == program["placement"]["id"]
            assert checkpoint["status"] == CheckpointStatus.SCHEDULED
            assert checkpoint["still_employed"] is None
            assert checkpoint["confirmed_at"] is None

    def test_confirming_at_180_days_marks_the_placement_retained(self, api):
        """The third hop of confirmation fires only at the 180-day checkpoint.

        "The third hop fires only at the 180-day checkpoint: the placement's
        `retention_outcome` becomes `RETAINED_180` and the employer's
        `confirmed_retention_count` and `retention_reliability_pct` are
        re-derived."

        Design: Difficulty/transitive_cascade/checkpoint_180_confirm_retains_placement_and_alumni
        """
        program = fixtures.retained_placement_program(api)
        checkpoint_180 = program["checkpoints"][2]

        confirmed = fixtures.confirm_checkpoint(
            api, checkpoint_180["id"], program["employer"]["id"]
        )

        assert_retention_checkpoint(confirmed)
        assert confirmed["interval_days"] == 180
        assert confirmed["status"] == CheckpointStatus.CONFIRMED
        assert confirmed["still_employed"] is True
        assert_instant_equals(
            confirmed["confirmed_at"], "2027-03-30T00:00:00Z", "confirmed_at"
        )

        placement = fixtures.read_placement(api, program["placement"]["id"])
        assert placement["retention_outcome"] == RetentionOutcome.RETAINED_180
        assert placement["employment_status"] == EmploymentStatus.ACTIVE

    def test_confirmation_verifies_the_wage_and_re_derives_employer_reliability(
        self, api
    ):
        """The second hop runs in parallel on the wage dimension.

        "The second runs in parallel on the wage dimension: when the confirmation
        carried `still_employed` as true and the placement's
        `wage_verification_status` is not `DISPUTED`, that status moves
        `UNVERIFIED → VERIFIED`, the placement's `verified_wage_cents_per_hour`
        takes the checkpoint's evidenced wage, and `wage_progression_pct` is
        recomputed."

        Design: Difficulty/transitive_cascade/checkpoint_180_confirm_retains_placement_and_alumni
        """
        program = fixtures.retained_placement_program(api)

        fixtures.confirm_checkpoint(
            api, program["checkpoints"][2]["id"], program["employer"]["id"]
        )

        placement = fixtures.read_placement(api, program["placement"]["id"])
        assert placement["wage_verification_status"] == WageVerificationStatus.VERIFIED
        assert placement["verified_wage_cents_per_hour"] == 1900
        assert_ratio(
            placement["wage_progression_pct"], 0.1515, "wage_progression_pct"
        )

        employer = fixtures.read_employer(api, program["employer"]["id"])
        assert employer["confirmed_retention_count"] == 1
        assert employer["failed_retention_count"] == 0
        assert_ratio(
            employer["retention_reliability_pct"], 1.0000, "retention_reliability_pct"
        )

    def test_the_participant_becomes_an_alumnus_and_the_365_day_row_waits(self, api):
        """The fourth hop is the program's definition of success.

        "The fourth follows from the third: because the placement reached
        `RETAINED_180`, the participant moves `PLACED → ALUMNI_RETAINED`, which is
        terminal and is the program's definition of success. The 365-day checkpoint
        exists for reporting continuity and does not itself change any retention
        outcome."

        Design: Difficulty/transitive_cascade/checkpoint_180_confirm_retains_placement_and_alumni
        """
        program = fixtures.retained_placement_program(api)

        fixtures.confirm_checkpoint(
            api, program["checkpoints"][2]["id"], program["employer"]["id"]
        )

        participant = fixtures.read_participant(api, program["participant"]["id"])
        assert participant["status"] == ParticipantStatus.ALUMNI_RETAINED

        checkpoints = fixtures.list_checkpoints(api, program["placement"]["id"])
        annual = checkpoints[3]
        assert annual["interval_days"] == 365
        assert annual["status"] == CheckpointStatus.SCHEDULED
        assert_instant_equals(annual["due_date"], "2027-10-01T00:00:00Z", "due_date")
