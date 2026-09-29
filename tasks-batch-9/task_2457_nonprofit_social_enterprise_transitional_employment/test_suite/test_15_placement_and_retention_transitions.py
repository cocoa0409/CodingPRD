"""Terminal locks and cascades on the placement and retention-checkpoint rows."""

from test_helpers import (
    ApiErrorId,
    CheckpointStatus,
    EmploymentStatus,
    ParticipantStatus,
    PartnershipStatus,
    RetentionOutcome,
    SeparationType,
    WageVerificationStatus,
    assert_instant_equals,
    assert_ratio,
    factories,
    fixtures,
    make_case_manager_headers,
    make_employer_partner_headers,
    validate_error,
    validate_success,
)
from test_helpers.constants import CLOCK_NOV_05, CLOCK_OCT_16, CLOCK_OCT_31


class TestConfirmingACheckpointTwice:
    """A confirmed checkpoint is terminal, and a second answer changes nothing."""

    def _placement_with_a_confirmed_thirty_day_checkpoint(self, api):
        """A placement hired 2026-10-01 whose 30-day checkpoint is answered."""
        program = fixtures.placed_participant_program(api)
        fixtures.set_clock(api, CLOCK_OCT_31)
        program["confirmed_checkpoint"] = fixtures.confirm_checkpoint(
            api, program["checkpoints"][0]["id"], program["employer"]["id"]
        )
        return program

    def test_a_second_confirmation_is_refused_and_stores_nothing(self, api):
        """The wage carried by the refused body never reaches the row.

        "A checkpoint begins in `SCHEDULED` `status` with `still_employed` null,
        `verified_wage_cents_per_hour` null and `confirmed_at` null; its `status`
        is one of `SCHEDULED`, `CONFIRMED`, `MISSED` or `VOIDED`, and the last
        three are terminal."

        Design: Corner/state_machines/confirm_already_confirmed_checkpoint_cannot_repeat
        """
        program = self._placement_with_a_confirmed_thirty_day_checkpoint(api)
        checkpoint_id = program["checkpoints"][0]["id"]

        response = api.confirm_retention_checkpoint(
            checkpoint_id,
            factories.checkpoint_confirmation_payload(
                still_employed=True, verified_wage_cents_per_hour=2000
            ),
            make_employer_partner_headers(program["employer"]["id"]),
        )

        validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)

        checkpoint = fixtures.list_checkpoints(api, program["placement"]["id"])[0]
        assert checkpoint["status"] == CheckpointStatus.CONFIRMED
        assert_instant_equals(checkpoint["confirmed_at"], CLOCK_OCT_31, "confirmed_at")
        assert checkpoint["verified_wage_cents_per_hour"] == 1900

    def test_the_refusal_leaves_both_placement_dimensions_where_they_were(self, api):
        """Only the 180-day answer moves the retention dimension.

        "The third hop fires only at the 180-day checkpoint: the placement's
        `retention_outcome` becomes `RETAINED_180` and the employer's
        `confirmed_retention_count` and `retention_reliability_pct` are
        re-derived."

        Design: Corner/state_machines/confirm_already_confirmed_checkpoint_cannot_repeat
        """
        program = self._placement_with_a_confirmed_thirty_day_checkpoint(api)

        response = api.confirm_retention_checkpoint(
            program["checkpoints"][0]["id"],
            factories.checkpoint_confirmation_payload(
                still_employed=True, verified_wage_cents_per_hour=2000
            ),
            make_employer_partner_headers(program["employer"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)

        placement = fixtures.read_placement(api, program["placement"]["id"])
        assert placement["wage_verification_status"] == WageVerificationStatus.VERIFIED
        assert placement["verified_wage_cents_per_hour"] == 1900
        assert_ratio(placement["wage_progression_pct"], 0.1515, "wage_progression_pct")
        assert placement["retention_outcome"] == RetentionOutcome.PENDING

        participant = fixtures.read_participant(api, program["participant"]["id"])
        assert participant["status"] == ParticipantStatus.PLACED


class TestSeparatingAPlacementTwice:
    """The separation is reported once; the employment dimension then closes."""

    def test_a_second_separation_is_refused(self, api):
        """`ACTIVE` is the only employment status a separation may leave.

        "The placement must be in `ACTIVE` `employment_status`."

        Design: Corner/state_machines/separate_already_separated_placement_cannot_repeat
        """
        program = fixtures.re_entry_eligible_program(api)
        fixtures.set_clock(api, CLOCK_OCT_16)

        response = api.separate_placement(
            program["placement"]["id"],
            factories.separation_payload(
                separation_type=SeparationType.VOLUNTARY,
                separation_date=CLOCK_OCT_16,
            ),
            make_employer_partner_headers(program["employer"]["id"]),
        )

        validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)

        placement = fixtures.read_placement(api, program["placement"]["id"])
        assert placement["employment_status"] == EmploymentStatus.SEPARATED_INVOLUNTARY
        assert_instant_equals(
            placement["separation_date"], "2026-10-15T00:00:00Z", "separation_date"
        )
        assert placement["separation_days_after_hire"] == 14
        assert placement["retention_outcome"] == RetentionOutcome.FAILED_EARLY

    def test_the_refusal_does_not_count_a_second_failure(self, api):
        """One failed placement is one failure, however often it is reported.

        "`failed_retention_count` counts that employer's placements whose
        `retention_outcome` is `FAILED_EARLY` or `FAILED_LATE`."

        Design: Corner/state_machines/separate_already_separated_placement_cannot_repeat
        """
        program = fixtures.re_entry_eligible_program(api)
        fixtures.set_clock(api, CLOCK_OCT_16)

        response = api.separate_placement(
            program["placement"]["id"],
            factories.separation_payload(
                separation_type=SeparationType.VOLUNTARY,
                separation_date=CLOCK_OCT_16,
            ),
            make_employer_partner_headers(program["employer"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)

        employer = fixtures.read_employer(api, program["employer"]["id"])
        assert employer["failed_retention_count"] == 1
        assert employer["confirmed_retention_count"] == 0
        assert_ratio(
            employer["retention_reliability_pct"], 0.0000, "retention_reliability_pct"
        )
        assert employer["partnership_status"] == PartnershipStatus.ACTIVE

        participant = fixtures.read_participant(api, program["participant"]["id"])
        assert participant["status"] == ParticipantStatus.RE_ENTRY_ELIGIBLE
        assert_instant_equals(
            participant["eligible_re_entry_at"],
            "2026-10-15T00:00:00Z",
            "eligible_re_entry_at",
        )
        assert participant["re_entry_count"] == 0


class TestSeparationVoidsFutureCheckpointsOnly:
    """A separation cancels the follow-ups that have not come due yet."""

    def _separated_after_one_confirmation(self, api):
        """The 30-day answer is given, then the placement ends on 2026-11-05."""
        program = fixtures.placed_participant_program(api)
        fixtures.set_clock(api, CLOCK_OCT_31)
        fixtures.confirm_checkpoint(
            api, program["checkpoints"][0]["id"], program["employer"]["id"]
        )
        fixtures.set_clock(api, CLOCK_NOV_05)
        program["separation"] = validate_success(
            api.separate_placement(
                program["placement"]["id"],
                factories.separation_payload(
                    separation_type=SeparationType.INVOLUNTARY,
                    separation_date=CLOCK_NOV_05,
                ),
                make_employer_partner_headers(program["employer"]["id"]),
            )
        )
        return program

    def test_only_the_checkpoints_due_after_the_separation_are_voided(self, api):
        """An already-answered follow-up is left exactly as it was.

        "Every retention checkpoint of that placement still in `SCHEDULED` status
        whose `due_date` falls after the `separation_date` moves `SCHEDULED →
        VOIDED`, processed in order of `interval_days` ascending — a checkpoint
        that was already due before the separation is left alone to be answered
        or missed on its own terms."

        Design: Corner/state_machines/separation_voids_only_future_scheduled_checkpoints
        """
        program = self._separated_after_one_confirmation(api)

        assert (
            program["separation"]["employment_status"]
            == EmploymentStatus.SEPARATED_INVOLUNTARY
        )
        assert program["separation"]["separation_days_after_hire"] == 35
        assert program["separation"]["retention_outcome"] == RetentionOutcome.FAILED_EARLY

        checkpoints = fixtures.list_checkpoints(api, program["placement"]["id"])
        by_interval = {row["interval_days"]: row for row in checkpoints}
        assert by_interval[30]["status"] == CheckpointStatus.CONFIRMED
        for interval_days in (90, 180, 365):
            assert by_interval[interval_days]["status"] == CheckpointStatus.VOIDED

    def test_the_separation_leaves_the_wage_dimension_untouched(self, api):
        """The two dimensions move on their own evidence.

        "It sets `wage_verification_status` to `VERIFIED`, stores
        `verified_wage_cents_per_hour`, recomputes `wage_progression_pct`, and
        does **not** touch `employment_status`."

        Design: Corner/state_machines/separation_voids_only_future_scheduled_checkpoints
        """
        program = self._separated_after_one_confirmation(api)

        placement = fixtures.read_placement(api, program["placement"]["id"])
        assert placement["wage_verification_status"] == WageVerificationStatus.VERIFIED
        assert_ratio(placement["wage_progression_pct"], 0.1515, "wage_progression_pct")

        employer = fixtures.read_employer(api, program["employer"]["id"])
        assert employer["failed_retention_count"] == 1
        assert_ratio(
            employer["retention_reliability_pct"], 0.0000, "retention_reliability_pct"
        )
        assert employer["partnership_status"] == PartnershipStatus.ACTIVE

        participant = fixtures.read_participant(api, program["participant"]["id"])
        assert participant["status"] == ParticipantStatus.RE_ENTRY_ELIGIBLE
        assert_instant_equals(
            participant["eligible_re_entry_at"], CLOCK_NOV_05, "eligible_re_entry_at"
        )


class TestEmployerProbationThreshold:
    """Three failures put an employer on probation and close it to new hires."""

    def _employer_with_two_failures(self, api):
        """Two graduates on one line; the first fails two placements in a row."""
        program = fixtures.two_graduates_program(api)
        program["employer"] = fixtures.create_employer(api)
        for hire_date, separation_date in (
            ("2026-09-16T00:00:00Z", "2026-09-20T00:00:00Z"),
            ("2026-09-22T00:00:00Z", "2026-09-25T00:00:00Z"),
        ):
            self._fail_a_placement(api, program, hire_date, separation_date)
            fixtures.re_enter_participant(api, program["participant"]["id"])
            fixtures.certify_readiness(api, program["participant"]["id"])
            fixtures.graduate_participant(api, program["participant"]["id"])
        return program

    def _fail_a_placement(self, api, program, hire_date, separation_date):
        fixtures.set_clock(api, hire_date)
        placement = fixtures.create_placement(
            api,
            program["participant"]["id"],
            program["employer"]["id"],
            hire_date=hire_date,
        )
        fixtures.set_clock(api, separation_date)
        fixtures.separate_placement(
            api,
            placement["id"],
            program["employer"]["id"],
            separation_type=SeparationType.INVOLUNTARY,
            separation_date=separation_date,
        )
        return placement

    def test_two_failures_leave_the_employer_active_and_open(self, api):
        """The probation threshold is three, not two.

        "The third hop moves the employer's own standing if a threshold has been
        crossed: `ACTIVE → PROBATION` when `failed_retention_count` has reached at
        least 3 while remaining below 5, and `PROBATION → TERMINATED` when it has
        reached 5 or more."

        Design: Corner/state_machines/employer_probation_threshold_flags_and_blocks_new_placements
        """
        program = self._employer_with_two_failures(api)

        employer = fixtures.read_employer(api, program["employer"]["id"])
        assert employer["failed_retention_count"] == 2
        assert employer["partnership_status"] == PartnershipStatus.ACTIVE

        third = self._fail_a_placement(
            api, program, "2026-09-27T00:00:00Z", "2026-09-28T00:00:00Z"
        )
        placement = fixtures.read_placement(api, third["id"])
        assert placement["employment_status"] == EmploymentStatus.SEPARATED_INVOLUNTARY
        assert placement["separation_days_after_hire"] == 1
        assert placement["retention_outcome"] == RetentionOutcome.FAILED_EARLY

    def test_the_third_failure_closes_the_employer_to_new_placements(self, api):
        """A placement into an employer on probation is refused.

        "The employer's `partnership_status` must be `ACTIVE`, so a placement into
        an employer on probation or terminated is refused with
        `ERR_EMPLOYER_NOT_ACTIVE`."

        Design: Corner/state_machines/employer_probation_threshold_flags_and_blocks_new_placements
        """
        program = self._employer_with_two_failures(api)
        self._fail_a_placement(
            api, program, "2026-09-27T00:00:00Z", "2026-09-28T00:00:00Z"
        )

        employer = fixtures.read_employer(api, program["employer"]["id"])
        assert employer["partnership_status"] == PartnershipStatus.PROBATION
        assert employer["failed_retention_count"] == 3
        assert employer["confirmed_retention_count"] == 0
        assert_ratio(
            employer["retention_reliability_pct"], 0.0000, "retention_reliability_pct"
        )

        response = api.create_placement(
            factories.placement_payload(
                program["second_participant"]["id"],
                program["employer"]["id"],
                hire_date="2026-09-28T00:00:00Z",
            ),
            make_case_manager_headers(),
        )

        validate_error(response, ApiErrorId.ERR_EMPLOYER_NOT_ACTIVE, 409)

        second = fixtures.read_participant(api, program["second_participant"]["id"])
        assert second["status"] == ParticipantStatus.GRADUATED
        assert (
            len(
                fixtures.list_placements(
                    api, {"participant_id": program["second_participant"]["id"]}
                )
            )
            == 0
        )
