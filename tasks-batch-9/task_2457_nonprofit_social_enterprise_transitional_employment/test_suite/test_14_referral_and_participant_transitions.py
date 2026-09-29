"""Revisits, gates and terminal locks along the referral and participant paths."""

from test_helpers import (
    ApiErrorId,
    BusinessLineStatus,
    IntakePosture,
    MouTier,
    ParticipantStatus,
    PriorityBand,
    ReferralStatus,
    ReleasedReason,
    ScreeningDecision,
    ShiftAssignmentStatus,
    SupportActivityStatus,
    WorkShiftStatus,
    assert_hours,
    assert_instant_equals,
    assert_period_ledger,
    assert_previous_cycle_cleared,
    assert_ratio,
    assert_score,
    factories,
    fixtures,
    make_case_manager_headers,
    make_intake_specialist_headers,
    make_job_coach_headers,
    make_program_director_headers,
    validate_error,
    validate_success,
)
from test_helpers.constants import (
    CLOCK_SEP_07,
    CLOCK_SEP_08,
    CLOCK_SEP_15,
    CLOCK_SEP_20,
    CLOCK_SEP_25,
)
from test_helpers.test_users import (
    CASE_MANAGER_USER_ID,
    INTAKE_SPECIALIST_USER_ID,
    JOB_COACH_USER_ID,
    SECOND_INTAKE_SPECIALIST_USER_ID,
)

TWO_BARRIERS = ["JUSTICE_INVOLVED", "HOUSING_INSTABILITY"]


def _parked_candidate(api, hours_available_per_week=21):
    """A TIER_2 partner and one candidate parked in WAITLISTED by intake-1."""
    fixtures.set_clock(api, CLOCK_SEP_07)
    partner = fixtures.create_referral_partner(
        api,
        organization_name="Midtown Bridge",
        mou_tier=MouTier.TIER_2,
        referral_quota_per_period=5,
    )
    referral = fixtures.submit_referral(
        api,
        partner["id"],
        candidate_reference="CAND-101",
        declared_barrier_codes=list(TWO_BARRIERS),
        household_income_cents=200000,
        household_size=1,
        hours_available_per_week=hours_available_per_week,
    )
    parked = fixtures.screen_referral(
        api,
        referral["id"],
        ScreeningDecision.WAITLISTED,
        intake_user_id=INTAKE_SPECIALIST_USER_ID,
        verified_barrier_codes=list(TWO_BARRIERS),
        verified_household_income_cents=200000,
        verified_household_size=1,
        verified_hours_available_per_week=hours_available_per_week,
    )
    return {"partner": partner, "referral": parked}


class TestReScreeningAWaitlistedReferral:
    """The waitlist is a parking place, and a second screening overwrites it."""

    def test_the_waitlist_branch_parks_a_below_floor_candidate(self, api):
        """Parking does not enforce the score floor.

        "The **waitlist** branch, `SUBMITTED → WAITLISTED` or a re-screen that
        lands on `WAITLISTED` again, deliberately does **not** enforce the score
        floor: a below-floor candidate can be parked and re-screened once new
        evidence arrives, and re-screening simply overwrites
        `verified_barrier_codes`, the three verified inputs, all three derived
        scoring fields, `screened_at` and `decided_by_user_id`."

        Design: Corner/state_machines/rescreen_waitlisted_referral_to_eligible
        """
        parked = _parked_candidate(api)["referral"]

        assert parked["status"] == ReferralStatus.WAITLISTED
        assert_score(parked["eligibility_score"], 49.00, "eligibility_score")
        assert parked["priority_band"] == PriorityBand.BAND_C
        assert_instant_equals(parked["screened_at"], CLOCK_SEP_07, "screened_at")
        assert parked["decided_by_user_id"] == INTAKE_SPECIALIST_USER_ID

    def test_re_screening_overwrites_the_scores_and_both_stamps(self, api):
        """One extra hour of availability lifts the score onto the floor.

        "The **eligible** branch, `SUBMITTED → ELIGIBLE` or `WAITLISTED →
        ELIGIBLE`, is the only one that enforces floors: it requires at least
        one verified barrier code, `hours_available_per_week` of at least 20, and
        an `eligibility_score` of at least 50.00."

        Design: Corner/state_machines/rescreen_waitlisted_referral_to_eligible
        """
        parked = _parked_candidate(api)["referral"]
        fixtures.set_clock(api, CLOCK_SEP_08)

        response = api.screen_referral(
            parked["id"],
            factories.screening_payload(
                ScreeningDecision.ELIGIBLE,
                verified_barrier_codes=list(TWO_BARRIERS),
                verified_household_income_cents=200000,
                verified_household_size=1,
                verified_hours_available_per_week=22,
            ),
            make_intake_specialist_headers(SECOND_INTAKE_SPECIALIST_USER_ID),
        )
        referral = validate_success(response)

        assert referral["status"] == ReferralStatus.ELIGIBLE
        assert_score(referral["eligibility_score"], 50.00, "eligibility_score")
        assert referral["priority_band"] == PriorityBand.BAND_B
        assert_ratio(referral["fpl_ratio"], 1.5905, "fpl_ratio")
        assert referral["hours_available_per_week"] == 22
        assert_instant_equals(referral["screened_at"], CLOCK_SEP_08, "screened_at")
        assert referral["decided_by_user_id"] == SECOND_INTAKE_SPECIALIST_USER_ID


class TestReadinessCertificationThresholds:
    """Hours alone are not readiness: the contact-time thresholds bind too."""

    def test_a_single_coaching_session_is_a_shortfall(self, api):
        """Two of the three thresholds are not enough.

        "A shortfall on any one of the three is refused with
        `ERR_GRADUATION_CRITERIA_NOT_MET`."

        Design: Corner/state_machines/certify_readiness_with_one_coaching_session_rejected
        """
        program = fixtures.two_week_shift_program(api)
        participant_id = program["participant"]["id"]
        fixtures.deliver_new_support_activity(
            api, participant_id, cost_cents=6000, duration_minutes=90
        )

        response = api.certify_readiness(
            participant_id, make_job_coach_headers(JOB_COACH_USER_ID)
        )

        validate_error(response, ApiErrorId.ERR_GRADUATION_CRITERIA_NOT_MET, 422)

        participant = fixtures.read_participant(api, participant_id)
        assert participant["status"] == ParticipantStatus.TRANSITIONAL_EMPLOYED
        assert participant["readiness_certified_by_user_id"] is None
        assert participant["readiness_certified_at"] is None
        assert_hours(
            participant["transitional_hours_worked"],
            24.000,
            "transitional_hours_worked",
        )
        assert participant["support_activity_minutes"] == 90
        assert participant["delivered_coaching_count"] == 1


class TestGraduationSegregationOfDuties:
    """The operator who certified readiness may not also sign the graduation."""

    def test_the_certifying_operator_cannot_also_graduate(self, api):
        """Acting as a case manager does not launder the certifying identity.

        "**Segregation of duties.** The case manager graduating a participant is
        not the user who certified readiness — otherwise
        `ERR_SEGREGATION_OF_DUTIES` (409). Applies to graduation."

        Design: Corner/state_machines/graduate_by_certifying_coach_rejected_by_segregation
        """
        program = fixtures.ready_for_graduation_program(api)
        participant_id = program["participant"]["id"]

        response = api.graduate_participant(
            participant_id, make_case_manager_headers(JOB_COACH_USER_ID)
        )

        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 409)

        participant = fixtures.read_participant(api, participant_id)
        assert participant["status"] == ParticipantStatus.READY_FOR_GRADUATION
        assert participant["graduated_at"] is None

    def test_a_second_operator_graduates_and_frees_the_training_slot(self, api):
        """Graduation freezes the wage and hands the slot back to intake.

        "Graduation releases the training slot, so the line's
        `training_slots_filled` and `intake_posture` are re-derived and its
        `version` is incremented by one."

        Design: Corner/state_machines/graduate_by_certifying_coach_rejected_by_segregation
        """
        program = fixtures.ready_for_graduation_program(api)
        participant_id = program["participant"]["id"]

        response = api.graduate_participant(
            participant_id, make_case_manager_headers(CASE_MANAGER_USER_ID)
        )
        participant = validate_success(response)

        assert participant["status"] == ParticipantStatus.GRADUATED
        assert_instant_equals(participant["graduated_at"], CLOCK_SEP_15, "graduated_at")
        assert participant["graduation_wage_cents_per_hour"] == 1650

        line = fixtures.read_business_line(api, program["business_line"]["id"])
        assert line["training_slots_filled"] == 0
        assert line["intake_posture"] == IntakePosture.OPEN


class TestWorkShiftAutoClose:
    """The shift's own state is a pure function of the seats sitting on it."""

    def _shift_with_two_seats(self, api):
        """One twelve-hour shift carrying both trainees of the line."""
        program = fixtures.enrolled_participant_program(api)
        fixtures.add_second_participant(api, program, wage_cents_per_hour=1650)
        shift = fixtures.create_work_shift(
            api,
            program["business_line"]["id"],
            "2026-09-07T08:00:00Z",
            "2026-09-07T20:00:00Z",
        )
        program["work_shift"] = shift
        program["first_seat"] = fixtures.seat_participant(
            api, shift["id"], program["participant"]["id"]
        )
        program["second_seat"] = fixtures.seat_participant(
            api, shift["id"], program["second_participant"]["id"]
        )
        fixtures.set_clock(api, "2026-09-07T20:00:00Z")
        return program

    def test_a_shift_stays_scheduled_while_one_seat_is_still_assigned(self, api):
        """Auto-close needs every seat terminal, not merely one.

        "A shift moves `SCHEDULED → CLOSED` when it is still `SCHEDULED`, has at
        least one assignment row, every assignment on it is in `COMPLETED` or
        `RELEASED` status, and at least one of them is `COMPLETED`."

        Design: Corner/state_machines/work_shift_auto_closes_when_children_reach_terminal
        """
        program = self._shift_with_two_seats(api)

        completed = fixtures.complete_assignment(api, program["first_seat"]["id"], 12.000)

        assert completed["status"] == ShiftAssignmentStatus.COMPLETED
        assert completed["wage_cost_cents"] == 19800

        shift = fixtures.read_work_shift(api, program["work_shift"]["id"])
        assert shift["status"] == WorkShiftStatus.SCHEDULED
        assert shift["billable_labor_cost_cents"] is None
        assert shift["assigned_count"] == 1

    def test_the_last_release_closes_the_shift_on_completed_costs_alone(self, api):
        """A released seat empties the roster without adding a cent.

        "`RELEASED` assignments contribute nothing and keep `wage_cost_cents`
        null."

        Design: Corner/state_machines/work_shift_auto_closes_when_children_reach_terminal
        """
        program = self._shift_with_two_seats(api)
        fixtures.complete_assignment(api, program["first_seat"]["id"], 12.000)

        released = fixtures.release_assignment(api, program["second_seat"]["id"])

        assert released["status"] == ShiftAssignmentStatus.RELEASED
        assert released["released_reason"] == ReleasedReason.MANUAL_RELEASE
        assert released["wage_cost_cents"] is None

        shift = fixtures.read_work_shift(api, program["work_shift"]["id"])
        assert shift["status"] == WorkShiftStatus.CLOSED
        assert shift["billable_labor_cost_cents"] == 19800
        assert shift["assigned_count"] == 0
        assert shift["quality_defect_count"] == 0
        assert shift["customer_complaint_count"] == 0


class TestRepeatedBusinessLineReview:
    """A launched line has left the review and launch transitions behind it."""

    def test_a_launched_line_refuses_a_second_review_and_a_second_launch(self, api):
        """Neither transition is declared from `LAUNCHED`.

        "**Declared transition.** The target entity is in a state from which the
        requested transition is declared — otherwise
        `ERR_INVALID_STATE_TRANSITION` (409). Applies to every action endpoint:
        review, launch, screen, certify-readiness, graduate, re-enter, deliver,
        void, wage-verification, separate, confirm, and close."

        Design: Corner/state_machines/review_of_approved_business_line_cannot_repeat
        """
        fixtures.set_clock(api, CLOCK_SEP_07)
        line = fixtures.create_launched_business_line(api)
        launched_version = line["version"]

        repeat_review = api.review_business_line(
            line["id"], factories.review_payload(), make_program_director_headers()
        )
        validate_error(repeat_review, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)

        repeat_launch = api.launch_business_line(
            line["id"], make_program_director_headers()
        )
        validate_error(repeat_launch, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)

        stored = fixtures.read_business_line(api, line["id"])
        assert stored["status"] == BusinessLineStatus.LAUNCHED
        assert_instant_equals(stored["launched_at"], CLOCK_SEP_07, "launched_at")
        assert stored["intake_posture"] == IntakePosture.OPEN
        assert stored["version"] == launched_version


class TestVoidingAPlannedSupportActivity:
    """Voiding something that was never delivered cannot move money.

    A planned session has no cost entry behind it, so the void is a pure state
    change on the activity row.
    """

    def test_voiding_a_planned_session_moves_no_ledger(self, api):
        """No entry exists, so none is voided and no aggregate changes.

        "Voiding a `PLANNED` activity, `PLANNED → VOIDED`, simply stores the
        supplied `voided_reason` and moves on — no cost entry exists, so there is
        no ledger movement at all."

        Design: Corner/state_machines/void_planned_support_activity_moves_no_ledger
        """
        program = fixtures.enrolled_participant_program(api)
        activity = fixtures.plan_support_activity(
            api, program["participant"]["id"], duration_minutes=90, cost_cents=6000
        )

        response = api.void_support_activity(
            activity["id"],
            factories.void_payload(voided_reason="DUPLICATE_ENTRY"),
            make_program_director_headers(),
        )
        voided = validate_success(response)

        assert voided["status"] == SupportActivityStatus.VOIDED
        assert voided["voided_reason"] == "DUPLICATE_ENTRY"
        assert voided["delivered_at"] is None
        assert voided["delivered_by_user_id"] is None

        assert fixtures.cost_entry_count(api, {"source_activity_id": activity["id"]}) == 0

        period = fixtures.read_subsidy_period(api, program["subsidy_period"]["id"])
        assert_period_ledger(period, 0, 0, 0)
        assert_ratio(period["mission_share"], 0.0000, "mission_share")
        assert_hours(period["trainee_hours"], 0.000, "trainee_hours")
        assert period["true_cost_per_trainee_hour_cents"] is None
        assert period["subsidy_per_trainee_hour_cents"] is None

        participant = fixtures.read_participant(api, program["participant"]["id"])
        assert participant["support_activity_minutes"] == 0
        assert participant["delivered_coaching_count"] == 0


class TestReEntryLimit:
    """Two returns to transitional employment are allowed; a third is not."""

    def _place_and_fail_early(self, api, program, hire_clock, separation_clock):
        """One placement that ends involuntarily inside the ninety-day window."""
        fixtures.set_clock(api, hire_clock)
        placement = fixtures.create_placement(
            api,
            program["participant"]["id"],
            program["employer"]["id"],
            hire_date=hire_clock,
        )
        fixtures.set_clock(api, separation_clock)
        fixtures.separate_placement(
            api,
            placement["id"],
            program["employer"]["id"],
            separation_type="INVOLUNTARY",
            separation_date=separation_clock,
        )
        return placement

    def _re_enter(self, api, participant_id, wage_cents_per_hour=1700):
        return validate_success(
            api.re_enter_participant(
                participant_id,
                factories.re_entry_payload(wage_cents_per_hour=wage_cents_per_hour),
                make_intake_specialist_headers(),
            )
        )

    def _re_certify_and_graduate(self, api, participant_id, graduation_clock):
        validate_success(
            api.certify_readiness(
                participant_id, make_job_coach_headers(JOB_COACH_USER_ID)
            )
        )
        fixtures.set_clock(api, graduation_clock)
        return validate_success(
            api.graduate_participant(
                participant_id, make_case_manager_headers(CASE_MANAGER_USER_ID)
            )
        )

    def _graduate_with_an_employer(self, api):
        program = fixtures.mid_september_graduate_program(api)
        program["employer"] = fixtures.create_employer(api)
        return program

    def test_the_first_re_entry_clears_the_previous_cycle(self, api):
        """Returning to work wipes every trace of the cycle that just ended.

        "The transition `RE_ENTRY_ELIGIBLE → TRANSITIONAL_EMPLOYED` increments
        `re_entry_count` by one, restamps `enrolled_at` from the logical clock,
        overwrites `wage_cents_per_hour` with the supplied value, and clears the
        whole previous cycle's evidence: `readiness_certified_by_user_id`,
        `readiness_certified_at`, `graduated_at`,
        `graduation_wage_cents_per_hour` and `eligible_re_entry_at` all become
        null."

        Design: Corner/state_machines/participant_re_entry_limit_bounds_the_cycle
        """
        program = self._graduate_with_an_employer(api)
        participant_id = program["participant"]["id"]
        self._place_and_fail_early(
            api, program, "2026-09-16T00:00:00Z", CLOCK_SEP_20
        )

        participant = self._re_enter(api, participant_id)

        assert participant["status"] == ParticipantStatus.TRANSITIONAL_EMPLOYED
        assert participant["re_entry_count"] == 1
        assert_instant_equals(participant["enrolled_at"], CLOCK_SEP_20, "enrolled_at")
        assert participant["wage_cents_per_hour"] == 1700
        assert_previous_cycle_cleared(participant)

    def test_a_third_re_entry_is_refused_once_the_count_reaches_two(self, api):
        """The limit is checked on the way in, never on the way out.

        "Three preconditions apply: the participant must be in
        `RE_ENTRY_ELIGIBLE` status, their `re_entry_count` must be strictly below
        the re-entry limit of two — a third attempt is refused with
        `ERR_RE_ENTRY_LIMIT_REACHED` — and the business line must be `LAUNCHED`
        with `intake_posture` `OPEN`."

        Design: Corner/state_machines/participant_re_entry_limit_bounds_the_cycle
        """
        program = self._graduate_with_an_employer(api)
        participant_id = program["participant"]["id"]

        self._place_and_fail_early(
            api, program, "2026-09-16T00:00:00Z", CLOCK_SEP_20
        )
        first = self._re_enter(api, participant_id)
        assert first["re_entry_count"] == 1
        self._re_certify_and_graduate(api, participant_id, "2026-09-21T00:00:00Z")

        self._place_and_fail_early(
            api, program, "2026-09-22T00:00:00Z", CLOCK_SEP_25
        )
        second = self._re_enter(api, participant_id)
        assert second["re_entry_count"] == 2
        assert_instant_equals(second["enrolled_at"], CLOCK_SEP_25, "enrolled_at")
        self._re_certify_and_graduate(api, participant_id, "2026-09-26T00:00:00Z")

        self._place_and_fail_early(
            api, program, "2026-09-27T00:00:00Z", "2026-09-28T00:00:00Z"
        )

        parked = fixtures.read_participant(api, participant_id)
        assert parked["status"] == ParticipantStatus.RE_ENTRY_ELIGIBLE
        assert parked["re_entry_count"] == 2
        assert_instant_equals(
            parked["eligible_re_entry_at"], "2026-09-28T00:00:00Z", "eligible_re_entry_at"
        )

        response = api.re_enter_participant(
            participant_id,
            factories.re_entry_payload(),
            make_intake_specialist_headers(),
        )

        validate_error(response, ApiErrorId.ERR_RE_ENTRY_LIMIT_REACHED, 409)

        after = fixtures.read_participant(api, participant_id)
        assert after["status"] == ParticipantStatus.RE_ENTRY_ELIGIBLE
        assert after["re_entry_count"] == 2
        assert_hours(
            after["transitional_hours_worked"], 24.000, "transitional_hours_worked"
        )
        assert after["support_activity_minutes"] == 180
        assert after["delivered_coaching_count"] == 2

        line = fixtures.read_business_line(api, program["business_line"]["id"])
        assert line["training_slots_filled"] == 0
