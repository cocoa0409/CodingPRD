"""Operations that hinge on the state of a neighbouring entity."""

from test_helpers import (
    ApiErrorId,
    BusinessLineStatus,
    CostCategory,
    CostClassification,
    IntakePosture,
    JOB_COACH_USER_ID,
    ReferralStatus,
    SupportActivityStatus,
    assert_instant_equals,
    assert_period_ledger,
    assert_ratio,
    factories,
    fixtures,
    make_intake_specialist_headers,
    make_job_coach_headers,
    validate_error,
)


class TestSupportDeliveryNeedsAPeriodCoveringNow:
    """The delivery anchor is the clock, not the participant's enrolment date."""

    def _planned_coaching_with_an_october_period_only(self, api):
        """A trainee enrolled on 2026-09-07 whose line has an October period only."""
        program = fixtures.enrolled_participant_program(api, with_period=False)
        program["subsidy_period"] = fixtures.create_open_subsidy_period(
            api,
            program["business_line"]["id"],
            period_start="2026-10-01T00:00:00Z",
            period_end="2026-10-31T00:00:00Z",
        )
        program["activity"] = fixtures.plan_support_activity(
            api, program["participant"]["id"], duration_minutes=90, cost_cents=6000
        )
        return program

    def test_delivery_is_refused_while_no_open_period_covers_the_clock(self, api):
        """The anchor instant for a delivery is the logical clock's current instant.

        "**Delivery** is reserved to a `JobCoach`. The activity must be `PLANNED`,
        the participant must be in `TRANSITIONAL_EMPLOYED`, `READY_FOR_GRADUATION`
        or `PLACED` status — a graduate awaiting placement and an exited participant
        cannot receive services — and an open accounting period must exist for the
        participant's business line covering the logical clock's current instant,
        failing which the request is refused with `ERR_NO_OPEN_SUBSIDY_PERIOD`."

        Design: Difficulty/cross_entity_state_dependency/support_delivery_depends_on_open_period_covering_now
        """
        program = self._planned_coaching_with_an_october_period_only(api)

        response = api.deliver_support_activity(
            program["activity"]["id"], make_job_coach_headers()
        )

        validate_error(response, ApiErrorId.ERR_NO_OPEN_SUBSIDY_PERIOD, 409)

        activity = fixtures.read_support_activity(api, program["activity"]["id"])
        assert activity["status"] == SupportActivityStatus.PLANNED
        assert activity["delivered_at"] is None
        assert activity["delivered_by_user_id"] is None

        period = fixtures.read_subsidy_period(api, program["subsidy_period"]["id"])
        assert period["mission_cost_cents"] == 0
        assert period["total_cost_cents"] == 0

    def test_moving_the_clock_into_the_period_lets_the_same_delivery_through(self, api):
        """The same request succeeds once the clock sits inside the period interval.

        "The transition `PLANNED → DELIVERED` stamps `delivered_at` from the logical
        clock, records the acting operator as `delivered_by_user_id`, and auto-posts
        one cost entry into the selected period with `classification` `MISSION`,
        `amount_cents` equal to the activity's `cost_cents`, `source_activity_id`
        pointing at this activity, `status` `POSTED`, and `category` `COACHING` when
        the activity's `category` is `JOB_COACHING` or `CASE_MANAGEMENT` and
        `SUPPORT_SERVICE` otherwise."

        Design: Difficulty/cross_entity_state_dependency/support_delivery_depends_on_open_period_covering_now
        """
        program = self._planned_coaching_with_an_october_period_only(api)
        api.deliver_support_activity(program["activity"]["id"], make_job_coach_headers())

        fixtures.set_clock(api, "2026-10-05T00:00:00Z")
        delivered = fixtures.deliver_support_activity(api, program["activity"]["id"])

        assert delivered["status"] == SupportActivityStatus.DELIVERED
        assert_instant_equals(
            delivered["delivered_at"], "2026-10-05T00:00:00Z", "delivered_at"
        )
        assert delivered["delivered_by_user_id"] == JOB_COACH_USER_ID

        entries = fixtures.list_cost_entries(
            api, {"source_activity_id": program["activity"]["id"]}
        )
        assert len(entries) == 1
        entry = entries[0]
        assert entry["subsidy_period_id"] == program["subsidy_period"]["id"]
        assert entry["category"] == CostCategory.COACHING
        assert entry["classification"] == CostClassification.MISSION
        assert entry["amount_cents"] == 6000

    def test_the_delivery_re_derives_the_period_ledger_and_the_progress_metrics(
        self, api
    ):
        """Support cost is wholly mission cost, and it lands on both owners at once.

        "Support cost is always wholly mission cost: a coaching hour is never
        charged to the trading operation."

        Design: Difficulty/cross_entity_state_dependency/support_delivery_depends_on_open_period_covering_now
        """
        program = self._planned_coaching_with_an_october_period_only(api)
        fixtures.set_clock(api, "2026-10-05T00:00:00Z")
        fixtures.deliver_support_activity(api, program["activity"]["id"])

        period = fixtures.read_subsidy_period(api, program["subsidy_period"]["id"])
        assert_period_ledger(period, 6000, 0, 6000)
        assert_ratio(period["mission_share"], 0.0000, "mission_share")
        assert period["true_cost_per_trainee_hour_cents"] is None
        assert period["subsidy_per_trainee_hour_cents"] is None

        participant = fixtures.read_participant(api, program["participant"]["id"])
        assert participant["support_activity_minutes"] == 90
        assert participant["delivered_coaching_count"] == 1


class TestEnrollmentDependsOnQualityDrivenPosture:
    """Ten incidents on a single completion shut intake on a line with free slots."""

    def test_ten_incidents_close_intake_while_the_line_stays_launched(self, api):
        """The quality counter alone can close intake.

        "`intake_posture` is `OPEN` when the line's `status` is `LAUNCHED` **and**
        `training_slots_filled` is strictly less than `training_slots_total` **and**
        `quality_incident_count` is strictly less than ten; in every other case it
        is `CLOSED`."

        Design: Difficulty/cross_entity_state_dependency/enrollment_depends_on_quality_driven_intake_posture
        """
        program = fixtures.quality_closed_intake_program(api)

        shift = fixtures.read_work_shift(api, program["work_shift"]["id"])
        assert shift["quality_defect_count"] == 6
        assert shift["customer_complaint_count"] == 4

        line = fixtures.read_business_line(api, program["business_line"]["id"])
        assert line["status"] == BusinessLineStatus.LAUNCHED
        assert line["training_slots_filled"] == 1
        assert line["quality_incident_count"] == 10
        assert line["intake_posture"] == IntakePosture.CLOSED

    def test_enrollment_with_a_current_version_is_still_refused(self, api):
        """A fresh version does not help once posture has closed on quality.

        "Enrollment is refused when the line's `status` is not `LAUNCHED` or its
        `intake_posture` is `CLOSED`, with `ERR_INTAKE_CLOSED`, and refused when a
        participant already references that referral, with
        `ERR_REFERRAL_ALREADY_ENROLLED` — at most one participant exists per
        referral."

        Design: Difficulty/cross_entity_state_dependency/enrollment_depends_on_quality_driven_intake_posture
        """
        program = fixtures.quality_closed_intake_program(api)
        line_id = program["business_line"]["id"]
        second_referral_id = program["second_referral"]["id"]
        current_version = fixtures.business_line_version(api, line_id)

        response = api.create_participant(
            factories.participant_payload(
                second_referral_id, line_id, current_version
            ),
            make_intake_specialist_headers(),
        )

        validate_error(response, ApiErrorId.ERR_INTAKE_CLOSED, 409)

        assert fixtures.participant_count(api, {"referral_id": second_referral_id}) == 0
        referral = fixtures.read_referral(api, second_referral_id)
        assert referral["status"] == ReferralStatus.ELIGIBLE
