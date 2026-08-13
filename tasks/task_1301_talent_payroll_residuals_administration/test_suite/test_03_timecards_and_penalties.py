"""Timecard lifecycle, computed fields, daily gross, and penalty assessment."""
from test_helpers import (
    ACCOUNTANT,
    CLERK,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_penalty_assessment,
    assert_timecard,
    create_approved_timecard,
    create_draft_engagement,
    create_performer,
    create_ratified_agreement,
    create_shooting_production,
    create_timecard,
    create_timecard_payload,
    get_timecard,
    get_success_data,
    list_all_penalty_assessments,
    list_all_timecards,
    revise_timecard_payload,
    setup_standard,
    setup_with_approved_timecard,
    validate_error,
    validate_paginated,
)


class TestTimecardCreationComputedFields:
    def test_computed_fields_server_derived(self, api):
        """PRD §3.5: "On a successful submission, the server computes
        `worked_minutes` (the difference between `wrap_time` and `call_time`,
        minus the meal break duration from `first_meal_out` to `first_meal_in`,
        expressed in whole minutes), `overtime_minutes` (the amount by which
        `worked_minutes` exceeds the engagement's tier `ot_daily_threshold_minutes`,
        floored at zero), and `provisional_penalty_cents` (an estimate from
        `scheduled_hours`; see §3.7)."
        PRD §3.5: "The timecard is created with `review_status` = `SUBMITTED` and
        `payment_status` = `UNBATCHED`."

        Design: Corner/entities/timecard_computed_fields_server_derived
        """
        ctx = setup_standard()
        tc = create_timecard(ctx["eng"]["id"])
        assert_timecard(tc)
        # 660 elapsed minutes minus the 30-minute meal; 630 - 480 threshold.
        assert tc["worked_minutes"] == 630
        assert tc["overtime_minutes"] == 150
        assert tc["provisional_penalty_cents"] == 2500, (
            "scheduled_hours 10 > 6 forces one provisional MEAL unit x 2500")
        assert tc["review_status"] == "SUBMITTED"
        assert tc["payment_status"] == "UNBATCHED"

    def test_create_requires_engagement_active(self, api):
        """PRD §3.5: "The engagement must be `ACTIVE`; the production must be
        `SHOOTING`; a violation of either surfaces as `ERR_ENGAGEMENT_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/timecard_create_requires_engagement_active
        """
        agr = create_ratified_agreement()
        prod = create_shooting_production(agr["id"])
        perf = create_performer()
        eng = create_draft_engagement(prod["id"], agr["id"], perf["id"])
        payload = create_timecard_payload(
            eng["id"], first_meal_out="2026-08-10T13:30:00Z",
            first_meal_in="2026-08-10T14:00:00Z",
            wrap_time="2026-08-10T17:00:00Z", scheduled_hours=9)
        resp = api.create_timecard(payload, ACCOUNTANT)
        validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_NOT_ACTIVE)

    def test_create_rejection_persists_nothing(self, api):
        """PRD §3.5: "The engagement must be `ACTIVE`; the production must be
        `SHOOTING`; a violation of either surfaces as `ERR_ENGAGEMENT_NOT_ACTIVE`."
        A rejected submission persists no timecard.

        Design: Difficulty/cross_entity_state_dependency/timecard_create_requires_engagement_active
        """
        agr = create_ratified_agreement()
        prod = create_shooting_production(agr["id"])
        perf = create_performer()
        eng = create_draft_engagement(prod["id"], agr["id"], perf["id"])
        payload = create_timecard_payload(eng["id"])
        validate_error(api.create_timecard(payload, ACCOUNTANT),
                       ApiErrorId.ERR_ENGAGEMENT_NOT_ACTIVE)
        assert list_all_timecards() == [], "rejected create must not persist a timecard"


class TestProvisionalVsFinalPenalty:
    def _setup_on_time_meal_card(self, api):
        """Card with scheduled_hours 9 (provisional MEAL unit) but an on-time
        actual meal (330 minutes after call) and a 30-minute break."""
        ctx = setup_standard()
        tc = create_timecard(
            ctx["eng"]["id"],
            first_meal_out="2026-08-10T13:30:00Z",
            first_meal_in="2026-08-10T14:00:00Z",
            wrap_time="2026-08-10T17:00:00Z",
            scheduled_hours=9)
        return ctx, tc

    def test_provisional_estimate_from_scheduled_hours(self, api):
        """PRD §3.7: "At timecard submission and revision, the server computes
        `provisional_penalty_cents` from `scheduled_hours` alone: one MEAL unit if
        `scheduled_hours` exceeds 6, zero otherwise; REST units are always zero in
        the provisional estimate; TURNAROUND is not estimable at submission and is
        treated as zero."
        PRD §3.7: "The provisional estimate is `meal_penalty_cents` multiplied by
        the provisional MEAL unit count."

        Design: Difficulty/dual_variant_calc/timecard_penalty_provisional_vs_final
        """
        _ctx, tc = self._setup_on_time_meal_card(api)
        assert tc["provisional_penalty_cents"] == 2500, (
            "scheduled_hours 9 > 6 -> one provisional MEAL unit x 2500")

    def test_final_penalty_diverges_from_provisional(self, api):
        """PRD §3.7: "For identical timestamps, provisional and final penalties
        routinely differ, because the provisional estimate ignores actual meal
        timing."
        PRD §3.6: "If the delay exceeds 360 minutes, one unit of violation is
        recorded; otherwise zero."
        PRD §3.6: "For each violation category with units greater than zero, a
        `PenaltyAssessment` row is created with `status` = `CONFIRMED`".

        Design: Difficulty/dual_variant_calc/timecard_penalty_provisional_vs_final
        """
        _ctx, tc = self._setup_on_time_meal_card(api)
        approved = get_success_data(api.approve_timecard(tc["id"], CLERK))
        assert approved["final_penalty_cents"] == 0, (
            "actual meal delay 330 <= 360, rest 30 not < 30, no prior card")
        # worked 510 = 540 elapsed - 30 meal; OT 30 -> 100000 + 9375.
        assert approved["day_gross_cents"] == 109375
        assert list_all_penalty_assessments() == [], (
            "no violation type with units > 0 -> no PenaltyAssessment rows")


class TestDailyGrossComposition:
    def test_worked_and_overtime_minutes(self, api):
        """PRD §3.5: "the server computes `worked_minutes` (the difference between
        `wrap_time` and `call_time`, minus the meal break duration from
        `first_meal_out` to `first_meal_in`, expressed in whole minutes),
        `overtime_minutes` (the amount by which `worked_minutes` exceeds the
        engagement's tier `ot_daily_threshold_minutes`, floored at zero)".

        Design: Difficulty/combinatorial_formula/daily_gross_tiered_overtime_composition
        """
        ctx = setup_standard()
        tc = create_timecard(ctx["eng"]["id"])
        assert tc["worked_minutes"] == 630, "660 elapsed - 30 meal"
        assert tc["overtime_minutes"] == 150, "630 - 480 threshold"

    def test_day_gross_tiered_overtime_at_approval(self, api):
        """PRD §3.6: "the server looks up the engagement's tier in the governing
        agreement's `rate_tiers`, splits `worked_minutes` into regular minutes (the
        lesser of `worked_minutes` and the tier's `ot_daily_threshold_minutes`) and
        overtime minutes (the excess, floored at zero), converts the tier's
        `day_rate_cents` to an hourly rate by dividing by eight (since the day rate
        represents eight hours), then computes `day_gross_cents` as the sum of two
        independently rounded components — the regular component (regular minutes
        divided by sixty, multiplied by the hourly rate, rounded half-up to integer
        cents) plus the overtime component (overtime minutes divided by sixty,
        multiplied by the hourly rate, multiplied by the tier's `ot_multiplier`,
        rounded half-up to integer cents)."
        PRD §3.6: "If the delay exceeds 360 minutes, one unit of violation is
        recorded; otherwise zero. The penalty amount is the unit count multiplied
        by the agreement's `meal_penalty_cents`."

        Design: Difficulty/combinatorial_formula/daily_gross_tiered_overtime_composition
        """
        ctx = setup_standard()
        tc = create_timecard(ctx["eng"]["id"])
        approved = get_success_data(api.approve_timecard(tc["id"], CLERK))
        # 480/60 x 12500 = 100000; 150/60 x 12500 x 1.5 = 46875.
        assert approved["day_gross_cents"] == 146875
        assert approved["final_penalty_cents"] == 2500, (
            "meal delay 390 > 360 -> one MEAL unit x 2500")


class TestOvertimeThresholdBoundary:
    def _create_card_with_wrap(self, api, engagement_id, work_date, wrap_time):
        return create_timecard(
            engagement_id, work_date=work_date,
            call_time=f"{work_date}T08:00:00Z",
            first_meal_out=f"{work_date}T12:00:00Z",
            first_meal_in=f"{work_date}T12:30:00Z",
            wrap_time=f"{work_date}T{wrap_time}",
            scheduled_hours=8)

    def test_exactly_480_minutes_is_not_overtime(self, api):
        """PRD §3.5: "`overtime_minutes` (the amount by which `worked_minutes`
        exceeds the engagement's tier `ot_daily_threshold_minutes`, floored at
        zero)". A card at exactly the 480-minute threshold accrues no overtime:
        day_gross_cents == 100000 (the full day rate).

        Design: Difficulty/boundary_precision_check/overtime_threshold_exact_minute_boundary
        """
        ctx = setup_standard()
        tc480 = self._create_card_with_wrap(api, ctx["eng"]["id"],
                                            "2026-08-10", "16:30:00Z")
        approved = get_success_data(api.approve_timecard(tc480["id"], CLERK))
        assert approved["worked_minutes"] == 480
        assert approved["overtime_minutes"] == 0
        assert approved["day_gross_cents"] == 100000
        assert approved["final_penalty_cents"] == 0, (
            "meal delay 240 <= 360, rest 30, no prior card for turnaround")

    def test_481_minutes_yields_one_overtime_minute(self, api):
        """PRD §3.6: "the overtime component (overtime minutes divided by sixty,
        multiplied by the hourly rate, multiplied by the tier's `ot_multiplier`,
        rounded half-up to integer cents)". One minute past the threshold yields
        round_half_up(1/60 x 12500 x 1.5) = round_half_up(312.5) = 313, so
        day_gross_cents == 100313.

        Design: Difficulty/boundary_precision_check/overtime_threshold_exact_minute_boundary
        """
        ctx = setup_standard()
        tc480 = self._create_card_with_wrap(api, ctx["eng"]["id"],
                                            "2026-08-10", "16:30:00Z")
        tc481 = self._create_card_with_wrap(api, ctx["eng"]["id"],
                                            "2026-08-11", "16:31:00Z")
        get_success_data(api.approve_timecard(tc480["id"], CLERK))
        approved481 = get_success_data(api.approve_timecard(tc481["id"], CLERK))
        assert approved481["worked_minutes"] == 481
        assert approved481["overtime_minutes"] == 1
        assert approved481["day_gross_cents"] == 100313
        assert approved481["final_penalty_cents"] == 0, (
            "turnaround gap 15.5h >= 10h minimum; meal and rest clean")


class TestMealAndTurnaroundBoundaries:
    def test_meal_window_exactly_six_hours_no_violation(self, api):
        """PRD §3.6: "the delay from `call_time` to `first_meal_out`, in minutes,
        is compared against a six-hour window. If the delay exceeds 360 minutes,
        one unit of violation is recorded; otherwise zero."

        Design: Corner/calculations/meal_window_exactly_six_hours_no_violation
        """
        ctx = setup_standard()
        eng_id = ctx["eng"]["id"]
        tc_a = create_timecard(eng_id, work_date="2026-08-10",
                               call_time="2026-08-10T08:00:00Z",
                               first_meal_out="2026-08-10T14:00:00Z",
                               first_meal_in="2026-08-10T14:30:00Z",
                               wrap_time="2026-08-10T17:00:00Z",
                               scheduled_hours=8)
        tc_b = create_timecard(eng_id, work_date="2026-08-11",
                               call_time="2026-08-11T08:00:00Z",
                               first_meal_out="2026-08-11T14:01:00Z",
                               first_meal_in="2026-08-11T14:31:00Z",
                               wrap_time="2026-08-11T17:00:00Z",
                               scheduled_hours=8)
        approved_a = get_success_data(api.approve_timecard(tc_a["id"], CLERK))
        approved_b = get_success_data(api.approve_timecard(tc_b["id"], CLERK))
        assert approved_a["final_penalty_cents"] == 0, (
            "360-minute delay is not > 360")
        assert approved_b["final_penalty_cents"] == 2500, (
            "361-minute delay is one MEAL unit x 2500")
        # Both cards: worked 510, OT 30 -> 100000 + 9375.
        assert approved_a["day_gross_cents"] == 109375
        assert approved_b["day_gross_cents"] == 109375

    def test_turnaround_shortfall_and_exact_boundary(self, api):
        """PRD §3.6: "If the gap is strictly shorter than the required minimum, the
        shortfall in hours is rounded up to the next whole hour to yield the
        violation units; a gap exactly equal to the minimum is not a violation. The
        penalty amount is the unit count multiplied by the tier's `day_rate_cents`
        divided by eight and rounded half-up."

        Design: Corner/calculations/turnaround_shortfall_boundary_hours
        """
        ctx = setup_standard()
        eng_id = ctx["eng"]["id"]
        # Day 1: clean card, wrap 19:00.
        tc1 = create_timecard(eng_id, work_date="2026-08-10",
                              call_time="2026-08-10T08:00:00Z",
                              first_meal_out="2026-08-10T13:30:00Z",
                              first_meal_in="2026-08-10T14:00:00Z",
                              wrap_time="2026-08-10T19:00:00Z",
                              scheduled_hours=10)
        get_success_data(api.approve_timecard(tc1["id"], CLERK))
        # Day 2: call 04:00 -> 9h gap after day1 wrap, shortfall 1h -> 1 unit.
        tc2 = create_timecard(eng_id, work_date="2026-08-11",
                              call_time="2026-08-11T04:00:00Z",
                              first_meal_out="2026-08-11T09:00:00Z",
                              first_meal_in="2026-08-11T09:30:00Z",
                              wrap_time="2026-08-11T18:00:00Z",
                              scheduled_hours=12)
        # Day 3: call 04:00 -> exactly 10h after day2 wrap 18:00: no violation.
        tc3 = create_timecard(eng_id, work_date="2026-08-12",
                              call_time="2026-08-12T04:00:00Z",
                              first_meal_out="2026-08-12T09:00:00Z",
                              first_meal_in="2026-08-12T09:30:00Z",
                              wrap_time="2026-08-12T18:00:00Z",
                              scheduled_hours=12)
        approved2 = get_success_data(api.approve_timecard(tc2["id"], CLERK))
        approved3 = get_success_data(api.approve_timecard(tc3["id"], CLERK))

        assert approved2["final_penalty_cents"] == 12500, (
            "one TURNAROUND unit x round_half_up(100000/8)")
        # Day2: worked 810 (840 elapsed - 30 meal), OT 330 -> 100000 + 103125.
        assert approved2["day_gross_cents"] == 203125
        penalties = [p for p in list_all_penalty_assessments()
                     if p["timecard_id"] == tc2["id"]]
        assert len(penalties) == 1
        assert_penalty_assessment(penalties[0])
        assert penalties[0]["penalty_type"] == "TURNAROUND"
        assert penalties[0]["units"] == 1
        assert penalties[0]["amount_cents"] == 12500

        assert approved3["final_penalty_cents"] == 0, (
            "gap exactly equal to turnaround_min_hours is not a violation")
        assert approved3["day_gross_cents"] == 203125


class TestFlagReviseCycle:
    def test_flag_and_revise_cycle(self, api):
        """PRD §3.5: "Flagging by a `PayrollClerk` moves the timecard's
        `review_status` from `SUBMITTED` to `FLAGGED` and increments `version`".
        PRD §3.5: "Revision by a `ProductionAccountant` moves a `FLAGGED` timecard
        back to `SUBMITTED` and increments `version`; the request carries corrected
        `call_time`, `first_meal_out`, `first_meal_in`, `wrap_time`, and
        `scheduled_hours`, and the server recomputes `worked_minutes`,
        `overtime_minutes`, and `provisional_penalty_cents` from the revised
        inputs."

        Design: Difficulty/non_linear_state_machine/timecard_flag_revise_review_cycle
        """
        ctx = setup_standard()
        tc = create_timecard(ctx["eng"]["id"])

        flagged = get_success_data(api.flag_timecard(tc["id"], "meal time looks late",
                                                     CLERK))
        assert flagged["review_status"] == "FLAGGED"
        assert flagged["payment_status"] == "UNBATCHED", (
            "the review cycle never touches the payment dimension")

        revised = get_success_data(api.revise_timecard(
            tc["id"], revise_timecard_payload(), ACCOUNTANT))
        assert revised["review_status"] == "SUBMITTED"
        assert revised["provisional_penalty_cents"] == 2500, (
            "recomputed from revised scheduled_hours 10 > 6")

    def test_approve_after_revise_completes_cycle(self, api):
        """PRD §3.6: "Approval by a `PayrollClerk` moves the timecard's
        `review_status` from `SUBMITTED` to `APPROVED` and increments `version`.
        Approval requires the payment dimension to still be `UNBATCHED`".
        After approval the payment dimension remains UNBATCHED until a batch close
        sweeps the card.

        Design: Difficulty/non_linear_state_machine/timecard_flag_revise_review_cycle
        """
        ctx = setup_standard()
        tc = create_timecard(ctx["eng"]["id"])
        get_success_data(api.flag_timecard(tc["id"], "verify meal times", CLERK))
        get_success_data(api.revise_timecard(tc["id"], revise_timecard_payload(),
                                             ACCOUNTANT))
        approved = get_success_data(api.approve_timecard(tc["id"], CLERK))
        assert approved["review_status"] == "APPROVED"
        assert approved["payment_status"] == "UNBATCHED", (
            "approval does not advance the payment dimension")
        assert approved["final_penalty_cents"] == 2500
        assert approved["day_gross_cents"] == 146875


class TestInvalidTimecardTransitions:
    def test_approve_from_flagged_rejected(self, api):
        """PRD §3.6: "Approval by a `PayrollClerk` moves the timecard's
        `review_status` from `SUBMITTED` to `APPROVED` ... and any other state
        mismatch surfaces as `ERR_TIMECARD_INVALID_STATE`."

        Design: Corner/state_machines/timecard_approve_from_flagged_rejected
        """
        ctx = setup_standard()
        tc = create_timecard(ctx["eng"]["id"])
        get_success_data(api.flag_timecard(tc["id"], "verify meal times", CLERK))
        resp = api.approve_timecard(tc["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_TIMECARD_INVALID_STATE)
        assert get_timecard(tc["id"])["review_status"] == "FLAGGED"
        assert list_all_penalty_assessments() == [], (
            "a rejected approval creates no PenaltyAssessment rows")

    def test_double_approve_rejected_without_duplicate_assessments(self, api):
        """PRD §3.6: "Approval by a `PayrollClerk` moves the timecard's
        `review_status` from `SUBMITTED` to `APPROVED` ... and any other state
        mismatch surfaces as `ERR_TIMECARD_INVALID_STATE`."
        PRD §3.6: "For each violation category with units greater than zero, a
        `PenaltyAssessment` row is created with `status` = `CONFIRMED`" — exactly
        once per approval.

        Design: Corner/state_machines/timecard_double_approve_rejected
        """
        ctx = setup_standard()
        tc = create_approved_timecard(ctx["eng"]["id"])
        resp = api.approve_timecard(tc["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_TIMECARD_INVALID_STATE)
        penalties = list_all_penalty_assessments()
        assert len(penalties) == 1, "second approve must not duplicate assessments"
        assert penalties[0]["penalty_type"] == "MEAL"

    def test_flag_nonexistent_timecard_returns_404(self, api):
        """PRD §2.7: "When a request violates multiple rules, the rejection
        surfaces the highest-priority failure. The ordering, from first to last
        evaluated, is:" with "3. Existence of referenced identifiers (path
        parameters first, then foreign-key body fields, left to right); a missing
        identifier is rejected with `ERR_NOT_FOUND` (HTTP 404)" ahead of state
        gates.

        Design: Corner/validations/flag_nonexistent_timecard_returns_404_not_state_error
        """
        resp = api.flag_timecard(NON_EXISTENT_UUID, "x", CLERK)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_duplicate_work_date_rejected(self, api):
        """PRD §3.5: "Finally, at most one timecard per engagement per `work_date`
        is permitted; a duplicate is rejected with `ERR_DUPLICATE_WORK_DATE`."

        Design: Corner/validations/duplicate_work_date_rejected
        """
        ctx = setup_standard()
        create_timecard(ctx["eng"]["id"])
        payload = create_timecard_payload(
            ctx["eng"]["id"], call_time="2026-08-10T09:00:00Z",
            first_meal_out="2026-08-10T13:00:00Z",
            first_meal_in="2026-08-10T13:30:00Z",
            wrap_time="2026-08-10T18:00:00Z", scheduled_hours=8)
        resp = api.create_timecard(payload, ACCOUNTANT)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_WORK_DATE)


class TestPenaltyAssessmentLedger:
    def test_penalty_assessment_immutable_common_fields(self, api):
        """PRD §2.4: "A `PenaltyAssessment` carries only `id` and `created_at`; it
        has neither `updated_at` nor `version`."
        PRD §3.6: "For each violation category with units greater than zero, a
        `PenaltyAssessment` row is created with `status` = `CONFIRMED`: the row
        records the `timecard_id` of the timecard being approved, the
        `penalty_type` (`MEAL`, `REST`, or `TURNAROUND`), the violation `units`,
        and the `amount_cents` (units multiplied by the applicable unit price from
        the governing agreement)."

        Design: Corner/entities/penalty_assessment_immutable_common_fields
        """
        ctx = setup_with_approved_timecard()
        penalties = list_all_penalty_assessments()
        assert len(penalties) == 1
        row = penalties[0]
        assert_penalty_assessment(row)  # also asserts no version/updated_at keys
        assert row["timecard_id"] == ctx["tc"]["id"]
        assert row["penalty_type"] == "MEAL"
        assert row["units"] == 1
        assert row["amount_cents"] == 2500
        assert row["status"] == "CONFIRMED"


class TestTimecardListPagination:
    def test_pagination_envelope_and_limit(self, api):
        """PRD §2.3: "List endpoints accept optional `limit` and `offset` query
        parameters." and "The `meta` block of a list response includes `limit`,
        `offset`, `total_count`, and `has_more`."
        PRD §2.3: "Results are sorted by `created_at` ascending."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."

        Design: Corner/endpoints/timecard_list_pagination_envelope_and_limit
        """
        ctx = setup_with_approved_timecard()
        tc2 = create_timecard(ctx["eng"]["id"], work_date="2026-08-11",
                              call_time="2026-08-11T08:00:00Z",
                              first_meal_out="2026-08-11T13:30:00Z",
                              first_meal_in="2026-08-11T14:00:00Z",
                              wrap_time="2026-08-11T17:00:00Z",
                              scheduled_hours=8)
        get_success_data(api.approve_timecard(tc2["id"], CLERK))

        page1, meta1 = validate_paginated(
            api.list_timecards(CLERK, params={"limit": 1, "offset": 0}))
        assert len(page1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        assert meta1["limit"] == 1
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api.list_timecards(CLERK, params={"limit": 1, "offset": 1}))
        assert len(page2) == 1
        assert meta2["total_count"] == 2
        assert meta2["has_more"] is False
        assert meta2["offset"] == 1

        assert page1[0]["id"] != page2[0]["id"], "pages partition the result set"
        assert {page1[0]["id"], page2[0]["id"]} == {ctx["tc"]["id"], tc2["id"]}
