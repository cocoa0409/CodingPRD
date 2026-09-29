"""Partner gates on the way in, wage floors on the way out, and the retention ladder."""

from test_helpers import (
    ApiErrorId,
    CheckpointStatus,
    EmploymentStatus,
    MouStatus,
    ParticipantStatus,
    ReferralStatus,
    RetentionOutcome,
    WageVerificationStatus,
    assert_checkpoint_schedule,
    assert_instant_equals,
    assert_ratio,
    factories,
    fixtures,
    make_case_manager_headers,
    make_employer_partner_headers,
    make_intake_specialist_headers,
    make_referral_partner_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import (
    CLOCK_DEC_30,
    CLOCK_OCT_30,
    CLOCK_SEP_07,
    CLOCK_SEP_15,
)

HIRE_DATE = "2026-10-01T00:00:00Z"
LATE_HIRE_DATE = "2026-09-20T00:00:00Z"
EARLY_HIRE_DATE = "2026-09-10T00:00:00Z"


class TestPartnerSubmissionGates:
    """A lapsed MOU and an exhausted quota are two independent refusals."""

    def _a_lapsed_partner_and_a_partner_at_its_quota(self, api):
        """One partner whose MOU has lapsed, one active partner allowed a single referral."""
        fixtures.set_clock(api, CLOCK_SEP_07)
        lapsed = fixtures.create_referral_partner(
            api, organization_name="Lapsed Neighbourhood Trust", mou_status=MouStatus.LAPSED
        )
        capped = fixtures.create_referral_partner(
            api,
            organization_name="Single Slot Alliance",
            referral_quota_per_period=1,
        )
        referral = fixtures.submit_referral(
            api, capped["id"], candidate_reference="CAND-601"
        )
        return {"lapsed": lapsed, "capped": capped, "referral": referral}

    def test_a_lapsed_mou_blocks_submission_outright(self, api):
        """The MOU must be in force before anything else about the candidate matters.

        "Two gates guard submission: a partner whose `mou_status` has gone `LAPSED`
        is refused with `ERR_PARTNER_MOU_LAPSED`, and a partner that has already
        submitted as many referrals as `referral_quota_per_period` within the
        trailing 30 logical-clock days is refused with `ERR_PARTNER_QUOTA_EXCEEDED`
        — the count considered is the referrals of that partner created strictly
        after the instant 30 days before the logical clock's current value, and the
        comparison against the quota is strict."

        Design: Corner/errors/referral_from_lapsed_partner_and_over_quota_rejected
        """
        rows = self._a_lapsed_partner_and_a_partner_at_its_quota(api)

        response = api.create_referral(
            factories.referral_payload(
                rows["lapsed"]["id"], candidate_reference="CAND-602"
            ),
            make_referral_partner_headers(rows["lapsed"]["id"]),
        )

        validate_error(response, ApiErrorId.ERR_PARTNER_MOU_LAPSED, 409)

        partner = fixtures.read_referral_partner(api, rows["lapsed"]["id"])
        assert partner["referrals_submitted_count"] == 0

    def test_a_second_referral_against_a_quota_of_one_is_refused_and_uncounted(self, api):
        """A refused submission does not itself consume quota.

        "The partner's referral count inside the trailing 30-day window is strictly
        below `referral_quota_per_period` — otherwise `ERR_PARTNER_QUOTA_EXCEEDED`
        (409). Applies to referral submission."

        Design: Corner/errors/referral_from_lapsed_partner_and_over_quota_rejected
        """
        rows = self._a_lapsed_partner_and_a_partner_at_its_quota(api)

        response = api.create_referral(
            factories.referral_payload(
                rows["capped"]["id"], candidate_reference="CAND-603"
            ),
            make_referral_partner_headers(rows["capped"]["id"]),
        )

        validate_error(response, ApiErrorId.ERR_PARTNER_QUOTA_EXCEEDED, 409)

        partner = fixtures.read_referral_partner(api, rows["capped"]["id"])
        assert partner["referrals_submitted_count"] == 1

        screened = fixtures.screen_referral(api, rows["referral"]["id"])
        assert screened["status"] == ReferralStatus.ELIGIBLE


class TestOneParticipantPerReferral:
    """A referral yields at most one participant, whatever the second body says."""

    def test_a_second_enrollment_of_the_same_referral_is_refused(self, api):
        """The freshly re-read line version keeps the version guard out of the way.

        "Enrollment is refused when the line's `status` is not `LAUNCHED` or its
        `intake_posture` is `CLOSED`, with `ERR_INTAKE_CLOSED`, and refused when a
        participant already references that referral, with
        `ERR_REFERRAL_ALREADY_ENROLLED` — at most one participant exists per
        referral."

        Design: Corner/errors/enrolling_the_same_referral_twice_rejected
        """
        program = fixtures.enrolled_participant_program(api)
        line_id = program["business_line"]["id"]
        version = fixtures.business_line_version(api, line_id)

        response = api.create_participant(
            factories.participant_payload(
                program["referral"]["id"], line_id, version, wage_cents_per_hour=1700
            ),
            make_intake_specialist_headers(),
        )

        validate_error(response, ApiErrorId.ERR_REFERRAL_ALREADY_ENROLLED, 409)

        rows, meta = validate_paginated(
            api.list_participants(
                make_intake_specialist_headers(),
                {"referral_id": program["referral"]["id"]},
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["wage_cents_per_hour"] == 1650

    def test_the_refusal_leaves_the_referral_and_the_line_exactly_as_they_were(self, api):
        """No state is written when a rule fires.

        "It simultaneously drives the referral `ELIGIBLE → ENROLLED`, which is
        terminal, and refreshes the referring partner's `enrolled_referral_count`
        and `conversion_rate`."

        Design: Corner/errors/enrolling_the_same_referral_twice_rejected
        """
        program = fixtures.enrolled_participant_program(api)
        line_id = program["business_line"]["id"]
        version = fixtures.business_line_version(api, line_id)

        validate_error(
            api.create_participant(
                factories.participant_payload(
                    program["referral"]["id"], line_id, version, wage_cents_per_hour=1700
                ),
                make_intake_specialist_headers(),
            ),
            ApiErrorId.ERR_REFERRAL_ALREADY_ENROLLED,
            409,
        )

        referral = fixtures.read_referral(api, program["referral"]["id"])
        assert referral["status"] == ReferralStatus.ENROLLED

        line = fixtures.read_business_line(api, line_id)
        assert line["version"] == version
        assert line["training_slots_filled"] == 1


class TestPlacementGateOrder:
    """Three placement gates, layered so that the earliest one always answers."""

    def _graduate_and_a_low_floor_employer(self, api):
        """Graduated 2026-09-15 on wage 1650; the employer floor is only 1700."""
        program = fixtures.mid_september_graduate_program(api)
        program["employer"] = fixtures.create_employer(
            api, min_starting_wage_cents_per_hour=1700
        )
        return program

    def _attempt(self, api, program, hire_date, starting_wage_cents_per_hour):
        return api.create_placement(
            factories.placement_payload(
                program["participant"]["id"],
                program["employer"]["id"],
                hire_date=hire_date,
                starting_wage_cents_per_hour=starting_wage_cents_per_hour,
                weekly_hours=32.0,
            ),
            make_case_manager_headers(),
        )

    def test_a_hire_date_before_graduation_is_refused_on_a_legal_wage(self, api):
        """Only the date rule can be firing when the wage clears both floors.

        "The `hire_date` may not predate the participant's `graduated_at`, which
        reports `ERR_HIRE_DATE_BEFORE_GRADUATION`."

        Design: Corner/errors/placement_hire_date_and_wage_floors_rejected
        """
        program = self._graduate_and_a_low_floor_employer(api)
        assert_instant_equals(
            program["participant"]["graduated_at"], CLOCK_SEP_15, "graduated_at"
        )

        response = self._attempt(api, program, EARLY_HIRE_DATE, 1815)

        validate_error(response, ApiErrorId.ERR_HIRE_DATE_BEFORE_GRADUATION, 422)

    def test_the_employer_floor_answers_before_the_progression_floor(self, api):
        """A wage of 1650 breaks both floors, and the employer's is checked first.

        "And two wage floors must both be cleared: `starting_wage_cents_per_hour`
        must be at least the employer's `min_starting_wage_cents_per_hour`,
        reporting `ERR_WAGE_BELOW_EMPLOYER_FLOOR`, and it must also be at least the
        participant's frozen `graduation_wage_cents_per_hour` multiplied by 1.10 and
        rounded half up to whole cents, reporting
        `ERR_WAGE_PROGRESSION_FLOOR_NOT_MET`."

        Design: Corner/errors/placement_hire_date_and_wage_floors_rejected
        """
        program = self._graduate_and_a_low_floor_employer(api)

        below_employer_floor = self._attempt(api, program, LATE_HIRE_DATE, 1650)
        validate_error(
            below_employer_floor, ApiErrorId.ERR_WAGE_BELOW_EMPLOYER_FLOOR, 422
        )

        above_employer_floor_only = self._attempt(api, program, LATE_HIRE_DATE, 1800)
        validate_error(
            above_employer_floor_only,
            ApiErrorId.ERR_WAGE_PROGRESSION_FLOOR_NOT_MET,
            422,
        )

    def test_a_wage_exactly_on_the_progression_floor_is_accepted(self, api):
        """1650 raised by a tenth is 1815, and the floor is inclusive.

        "The second floor is the program's promise that leaving transitional
        employment is a raise of at least ten percent, not a lateral move."

        Design: Corner/errors/placement_hire_date_and_wage_floors_rejected
        """
        program = self._graduate_and_a_low_floor_employer(api)

        for hire_date, wage, expected_error_id, expected_status in (
            (EARLY_HIRE_DATE, 1815, ApiErrorId.ERR_HIRE_DATE_BEFORE_GRADUATION, 422),
            (LATE_HIRE_DATE, 1650, ApiErrorId.ERR_WAGE_BELOW_EMPLOYER_FLOOR, 422),
            (LATE_HIRE_DATE, 1800, ApiErrorId.ERR_WAGE_PROGRESSION_FLOOR_NOT_MET, 422),
        ):
            validate_error(
                self._attempt(api, program, hire_date, wage),
                expected_error_id,
                expected_status,
            )
        assert (
            len(
                fixtures.list_placements(
                    api, {"participant_id": program["participant"]["id"]}
                )
            )
            == 0
        )
        assert (
            fixtures.read_participant(api, program["participant"]["id"])["status"]
            == ParticipantStatus.GRADUATED
        )

        placement = validate_success(
            self._attempt(api, program, LATE_HIRE_DATE, 1815), 201
        )

        assert placement["employment_status"] == EmploymentStatus.ACTIVE
        assert placement["starting_wage_cents_per_hour"] == 1815
        assert (
            fixtures.read_participant(api, program["participant"]["id"])["status"]
            == ParticipantStatus.PLACED
        )


class TestRetentionLadderGuards:
    """A checkpoint must be due, and its predecessors must be settled."""

    def _placement_with_four_open_checkpoints(self, api):
        """Hired 2026-10-01 at 1900, so the ladder falls due 30/90/180/365 days on."""
        program = fixtures.mid_september_graduate_program(api)
        program["employer"] = fixtures.create_employer(
            api, min_starting_wage_cents_per_hour=1700
        )
        program["placement"] = fixtures.create_placement(
            api,
            program["participant"]["id"],
            program["employer"]["id"],
            hire_date=HIRE_DATE,
            starting_wage_cents_per_hour=1900,
        )
        program["checkpoints"] = fixtures.list_checkpoints(
            api, program["placement"]["id"]
        )
        return program

    def test_the_four_checkpoints_fall_due_on_whole_days_after_the_hire_date(self, api):
        """The ladder is laid out at creation, ascending by interval.

        "One row exists per follow-up interval, at 30, 90, 180 and 365 days, and
        each row records its `placement_id`, its `interval_days` and a `due_date`
        equal to the placement's `hire_date` plus that many whole days, landing on
        `00:00:00Z`."

        "The rows are created in ascending `interval_days` order, so creation order
        matches interval order, which is what lets the listing of a placement's
        checkpoints be read positionally: the 30-day row first, then 90, then 180,
        then 365."

        Design: Corner/errors/checkpoint_confirm_before_due_and_out_of_sequence_rejected
        """
        program = self._placement_with_four_open_checkpoints(api)

        assert_checkpoint_schedule(program["checkpoints"], HIRE_DATE)
        for checkpoint in program["checkpoints"]:
            assert checkpoint["status"] == CheckpointStatus.SCHEDULED

    def test_a_confirmation_one_day_early_is_refused(self, api):
        """The clock must have reached the due date, inclusive.

        "The checkpoint must be `SCHEDULED`; the acting `X-User-ID` must equal the
        placement's `employer_id`; the placement's `employment_status` must still be
        `ACTIVE`; the logical clock must have reached the checkpoint's `due_date`,
        inclusive, with an earlier attempt refused as `ERR_CHECKPOINT_NOT_DUE`; and
        every checkpoint of the same placement with a smaller `interval_days` must
        already be in `CONFIRMED` or `VOIDED` status, so the 180-day answer cannot be
        given while the 90-day one is still outstanding or was missed — that failure
        reports `ERR_CHECKPOINT_OUT_OF_SEQUENCE`."

        Design: Corner/errors/checkpoint_confirm_before_due_and_out_of_sequence_rejected
        """
        program = self._placement_with_four_open_checkpoints(api)
        fixtures.set_clock(api, CLOCK_OCT_30)

        response = api.confirm_retention_checkpoint(
            program["checkpoints"][0]["id"],
            factories.checkpoint_confirmation_payload(
                still_employed=True, verified_wage_cents_per_hour=1900
            ),
            make_employer_partner_headers(program["employer"]["id"]),
        )

        validate_error(response, ApiErrorId.ERR_CHECKPOINT_NOT_DUE, 409)

    def test_an_overdue_predecessor_still_blocks_and_then_still_answers(self, api):
        """No sweep has run, so the 30-day rung is late but neither missed nor skippable.

        "The checkpoint must be `SCHEDULED`; the acting `X-User-ID` must equal the
        placement's `employer_id`; the placement's `employment_status` must still be
        `ACTIVE`; the logical clock must have reached the checkpoint's `due_date`,
        inclusive, with an earlier attempt refused as `ERR_CHECKPOINT_NOT_DUE`; and
        every checkpoint of the same placement with a smaller `interval_days` must
        already be in `CONFIRMED` or `VOIDED` status, so the 180-day answer cannot be
        given while the 90-day one is still outstanding or was missed — that failure
        reports `ERR_CHECKPOINT_OUT_OF_SEQUENCE`."

        Design: Corner/errors/checkpoint_confirm_before_due_and_out_of_sequence_rejected
        """
        program = self._placement_with_four_open_checkpoints(api)
        thirty_day, ninety_day = program["checkpoints"][0], program["checkpoints"][1]
        fixtures.set_clock(api, CLOCK_DEC_30)

        out_of_sequence = api.confirm_retention_checkpoint(
            ninety_day["id"],
            factories.checkpoint_confirmation_payload(
                still_employed=True, verified_wage_cents_per_hour=1900
            ),
            make_employer_partner_headers(program["employer"]["id"]),
        )
        validate_error(
            out_of_sequence, ApiErrorId.ERR_CHECKPOINT_OUT_OF_SEQUENCE, 409
        )

        settled = fixtures.confirm_checkpoint(
            api, thirty_day["id"], program["employer"]["id"]
        )
        assert settled["status"] == CheckpointStatus.CONFIRMED
        assert_instant_equals(settled["confirmed_at"], CLOCK_DEC_30, "confirmed_at")

        answered = fixtures.confirm_checkpoint(
            api, ninety_day["id"], program["employer"]["id"]
        )
        assert answered["status"] == CheckpointStatus.CONFIRMED

        placement = fixtures.read_placement(api, program["placement"]["id"])
        assert placement["wage_verification_status"] == WageVerificationStatus.VERIFIED
        assert placement["verified_wage_cents_per_hour"] == 1900
        assert_ratio(placement["wage_progression_pct"], 0.1515, "wage_progression_pct")
        assert placement["retention_outcome"] == RetentionOutcome.PENDING
