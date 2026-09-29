"""Optimistic version guards, the rolling risk window and immediate consistency."""

from test_helpers import (
    BRONZE,
    ApiErrorId,
    BlockoutSource,
    BlockoutStatus,
    DayClass,
    PaymentMode,
    PlanStatus,
    ProgramStatus,
    ReservationStatus,
    VisitStatus,
    advance_program,
    assert_day_counters,
    assert_day_posture,
    assert_revenue_summary,
    blockout_payload,
    book_reservation,
    build_active_pass,
    build_program,
    clerk_headers,
    close_visit,
    create_park_day,
    create_passholder,
    create_program,
    create_tier,
    forecast_park_day,
    gate_agent_headers,
    get_park_day,
    get_pass,
    get_passholder,
    payment_plan_payload,
    process_pass,
    program_admin_headers,
    record_visit,
    revenue_summary,
    sell_pass,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestThePlanVersionGuardCatchesAStaleRead:
    """The version captured at sale is already stale once processing has written."""

    def _sold_and_processed(self, api):
        program = build_program(api, tiers=(BRONZE,), status=ProgramStatus.SALES_OPEN.value)
        holder = create_passholder(api, email="stale-plan@example.com")
        sold = sell_pass(
            api,
            program.id,
            program.tier_id("BRONZE"),
            holder["id"],
            payment_mode=PaymentMode.PAYMENT_PLAN.value,
        )
        processed = process_pass(api, sold["id"])
        return program, sold, processed

    def test_the_version_read_at_sale_is_refused_after_processing(self, api, default_clock):
        """Processing bumped the counter, so the older figure no longer matches.

        PRD: "Enrolling a season pass in a payment plan requires the request to carry
        `expected_season_pass_version`, holding the `version` of the target season pass as
        the client last observed it. The field is not optional. If it does not equal the
        pass's current `version`, the request is rejected with `ERR_STALE_PASS_VERSION`
        (HTTP 412)."

        Design: Corner/cross-cutting complexity layers/stale_expected_season_pass_version_returns_412
        """
        _, sold, processed = self._sold_and_processed(api)
        assert processed["version"] > sold["version"], (
            "processing should have advanced the pass version, got "
            f"{processed['version']!r} against {sold['version']!r}"
        )

        response = api.create_payment_plan(
            sold["id"],
            payment_plan_payload(3000, 4, "2026-09-01", sold["version"]),
            headers=clerk_headers(),
        )

        validate_error(response, ApiErrorId.ERR_STALE_PASS_VERSION.value, 412)
        _, meta = validate_paginated(
            api.list_payment_plans(
                headers=clerk_headers(), params={"season_pass_id": sold["id"]}
            )
        )
        assert meta["total_count"] == 0, (
            f"the refused enrolment must not store a plan, got {meta['total_count']!r}"
        )
        assert get_pass(api, sold["id"])["version"] == processed["version"], (
            "a rejected write must not advance the pass version"
        )

    def test_the_fresh_version_enrols_and_is_itself_consumed(self, api, default_clock):
        """Each accepted write advances the counter, so the same figure cannot be replayed.

        PRD: "A second enrolment legitimately supersedes an existing active plan — that is
        how a plan is re-amortised — so no state precondition blocks it; the stale version is
        the only signal that the clerk computed the new schedule against an outstanding
        balance that has since moved, and an installment settlement, an applied upgrade or a
        superseding plan each advance the pass's `version`."

        Design: Corner/cross-cutting complexity layers/stale_expected_season_pass_version_returns_412
        """
        _, sold, processed = self._sold_and_processed(api)

        plan = validate_success(
            api.create_payment_plan(
                sold["id"],
                payment_plan_payload(3000, 4, "2026-09-01", processed["version"]),
                headers=clerk_headers(),
            ),
            201,
        )

        assert plan["plan_status"] == PlanStatus.ACTIVE.value, (
            f"the accepted enrolment opens ACTIVE, got {plan['plan_status']!r}"
        )
        assert plan["monthly_amount_cents"] == 2625, (
            f"10500 financed over four rows is 2625 each, got {plan['monthly_amount_cents']!r}"
        )
        assert get_pass(api, sold["id"])["version"] == processed["version"] + 1, (
            "the accepted enrolment should advance the pass version exactly once"
        )

        replay = api.create_payment_plan(
            sold["id"],
            payment_plan_payload(3000, 4, "2026-09-01", processed["version"]),
            headers=clerk_headers(),
        )
        validate_error(replay, ApiErrorId.ERR_STALE_PASS_VERSION.value, 412)


class TestTheBlockoutVersionGuardCatchesAReForecast:
    """A forecast between the read and the write invalidates the captured version."""

    def _re_forecast_day(self, api):
        program = create_program(api)
        tier = create_tier(api, program["id"], name="BRONZE", tier_rank=1)
        created = create_park_day(api, program["id"], "2026-09-01")
        forecast = forecast_park_day(api, created["id"], 900)
        return program, tier, created, forecast

    def test_the_version_captured_before_the_forecast_is_refused(self, api, default_clock):
        """The operator has not yet seen the day the forecast produced.

        PRD: "Creating a manual blockout assignment requires the request to carry
        `expected_park_day_version`, holding the `version` of the target park day as the
        client last observed it. The field is not optional. If it does not equal the park
        day's current `version`, the request is rejected with `ERR_STALE_PARK_DAY_VERSION`
        (HTTP 412)."

        Design: Corner/cross-cutting complexity layers/stale_expected_park_day_version_returns_412
        """
        _, tier, created, forecast = self._re_forecast_day(api)
        assert_day_posture(forecast, utilization=0.9000, day_class=DayClass.PEAK.value)

        response = api.create_blockout_assignment(
            blockout_payload(tier["id"], created["id"], created["version"]),
            headers=program_admin_headers(),
        )

        validate_error(response, ApiErrorId.ERR_STALE_PARK_DAY_VERSION.value, 412)
        _, meta = validate_paginated(
            api.list_blockout_assignments(
                headers=program_admin_headers(), params={"park_day_id": created["id"]}
            )
        )
        assert meta["total_count"] == 0, (
            f"the refused blockout must not be stored, got {meta['total_count']!r}"
        )

    def test_the_version_the_forecast_produced_is_accepted(self, api, default_clock):
        """With the current figure the write lands and moves the day on again.

        PRD: "A manual creation records `source` as `MANUAL` and `status` as `ACTIVE`,
        leaving `lift_reason` null while the assignment remains active. Because a new
        blockout instantly removes a tier's access to that day, any reservation of that tier
        on that day still in `CONFIRMED` becomes `CANCELLED_BY_BLOCKOUT`, the day's counters
        are recomputed, and the day's `version` increments by 1."

        Design: Corner/cross-cutting complexity layers/stale_expected_park_day_version_returns_412
        """
        _, tier, created, forecast = self._re_forecast_day(api)

        assignment = validate_success(
            api.create_blockout_assignment(
                blockout_payload(tier["id"], created["id"], forecast["version"]),
                headers=program_admin_headers(),
            ),
            201,
        )

        assert assignment["status"] == BlockoutStatus.ACTIVE.value, (
            f"the accepted assignment opens ACTIVE, got {assignment['status']!r}"
        )
        assert assignment["source"] == BlockoutSource.MANUAL.value, (
            f"a hand-made assignment records MANUAL, got {assignment['source']!r}"
        )
        assert assignment["lift_reason"] is None, (
            f"an active assignment has no lift reason, got {assignment['lift_reason']!r}"
        )
        assert get_park_day(api, created["id"])["version"] == forecast["version"] + 1, (
            "the accepted blockout should advance the day version exactly once"
        )


class TestTheRiskWindowRollsForward:
    """The frequency signal is measured against the logical clock, so it ages out."""

    def _five_entries_in_the_window(self, api):
        program = build_program(api, tiers=(BRONZE,), status=ProgramStatus.SALES_OPEN.value)
        early_days = [
            create_park_day(api, program.id, f"2026-09-0{day}") for day in range(1, 6)
        ]
        late_day = create_park_day(api, program.id, "2026-09-14")
        pass_ctx = build_active_pass(api, program, tier_name="BRONZE")
        advance_program(api, program.id, ProgramStatus.SEASON_ACTIVE.value)
        set_clock(api, "2026-09-05T23:00:00Z")
        for index, day in enumerate(early_days, start=1):
            record_visit(api, pass_ctx.id, day["id"], f"2026-09-0{index}T10:00:00Z")
        return program, pass_ctx, late_day

    def test_five_entries_inside_the_trailing_week_score_thirty(self, api, default_clock):
        """Two entries beyond the free allowance of three are worth fifteen each.

        PRD: "The park allows three free entries a week before frequency itself becomes
        suspicious, so the score is 15 points for each window entry beyond the third — 15
        multiplied by the window entry count less three, treated as zero if the subtraction
        would go negative — plus 35 points for each window mismatch."

        Design: Corner/cross-cutting complexity layers/rolling_window_sharing_score_resets_when_entries_age_out
        """
        _, pass_ctx, _ = self._five_entries_in_the_window(api)

        holder = get_passholder(api, pass_ctx.holder_id)

        assert holder["sharing_risk_score"] == 30, (
            f"five clean entries score 15 * (5 - 3), got {holder['sharing_risk_score']!r}"
        )
        _, meta = validate_paginated(
            api.list_sharing_cases(
                headers=gate_agent_headers(), params={"season_pass_id": pass_ctx.id}
            )
        )
        assert meta["total_count"] == 0, (
            f"30 is below the auto-open score of 65, got {meta['total_count']!r} cases"
        )

    def test_after_the_clock_moves_on_a_single_fresh_entry_scores_zero(self, api, default_clock):
        """Only entries inside the trailing seven days count, so the score falls back.

        PRD: "Count the visits of this pass whose `entry_at` falls in the seven days up to
        and including the logical clock's current instant — that is, at or after the instant
        seven days before the clock and at or before the clock itself — and call that the
        window entry count."

        Design: Corner/cross-cutting complexity layers/rolling_window_sharing_score_resets_when_entries_age_out
        """
        _, pass_ctx, late_day = self._five_entries_in_the_window(api)

        set_clock(api, "2026-09-14T09:00:00Z")
        record_visit(api, pass_ctx.id, late_day["id"], "2026-09-14T10:00:00Z")

        holder = get_passholder(api, pass_ctx.holder_id)
        assert holder["sharing_risk_score"] == 0, (
            "one entry inside the window is inside the free allowance, got "
            f"{holder['sharing_risk_score']!r}"
        )
        assert get_pass(api, pass_ctx.id)["visit_count"] == 6, (
            f"the visit history is retained in full, got {get_pass(api, pass_ctx.id)['visit_count']!r}"
        )
        _, meta = validate_paginated(
            api.list_sharing_cases(
                headers=gate_agent_headers(), params={"season_pass_id": pass_ctx.id}
            )
        )
        assert meta["total_count"] == 0, (
            f"the reset prevents an auto-open, got {meta['total_count']!r} cases"
        )


class TestDerivedFiguresAreCurrentInTheSameSequence:
    """Every write answers with its own derived values and the next read agrees."""

    def _open_park(self, api):
        program = build_program(api, tiers=(BRONZE,), status=ProgramStatus.SALES_OPEN.value)
        day = create_park_day(api, program.id, "2026-09-01")
        pass_ctx = build_active_pass(api, program, tier_name="BRONZE")
        advance_program(api, program.id, ProgramStatus.SEASON_ACTIVE.value)
        return program, day, pass_ctx

    def test_the_booking_and_the_entry_are_visible_on_the_very_next_read(
        self, api, default_clock
    ):
        """No retry, no delay: the counters have already moved when the read arrives.

        PRD: "A new reservation opens in `status` `CONFIRMED`, leaves `redeemed_visit_id`
        null, raises the day's `reserved_count` by one, raises the day's monotonic
        `grant_count` by one, and recomputes `remaining_slot_count`."

        PRD: "If the pass holds a reservation on that day whose `status` is `CONFIRMED` and
        whose half-open arrival window contains the `entry_at` instant, that reservation is
        redeemed: it moves `CONFIRMED → REDEEMED`, its `redeemed_visit_id` is set to the new
        visit's `id`, the visit's own `reservation_id` is set to the reservation's `id`, the
        day's `reserved_count`, `redeemed_count` and `remaining_slot_count` are recomputed,
        and the reservation's `version` increments by 1."

        Design: Corner/consistency model/derived_fields_are_current_in_the_same_response
        """
        _, day, pass_ctx = self._open_park(api)

        booking = book_reservation(api, pass_ctx.id, day["id"], "09:00", "12:00")

        assert booking["status"] == ReservationStatus.CONFIRMED.value, (
            f"the write's own response carries the outcome, got {booking['status']!r}"
        )
        assert_day_counters(get_park_day(api, day["id"]), reserved=1, remaining=99, grant=1)

        visit = record_visit(api, pass_ctx.id, day["id"], "2026-09-01T09:30:00Z")

        assert visit["reservation_id"] == booking["id"], (
            f"the entry response already names the redeemed booking, got {visit['reservation_id']!r}"
        )
        assert_day_counters(get_park_day(api, day["id"]), reserved=0, redeemed=1, grant=1)

    def test_closing_the_visit_is_already_reflected_in_the_revenue_read(
        self, api, default_clock
    ):
        """The spend analysis is computed on demand from the rows as they now stand.

        PRD: "The visit moves `OPEN → CLOSED`, `spend_cents` is stored,
        `discount_applied_pct` is snapshotted from the entering tier's `in_park_discount_pct`
        so that a later upgrade cannot rewrite history, the recorded `spend_cents` is net of
        that discount, the pass's `in_park_spend_cents` — the sum of `spend_cents` over its
        visits in `CLOSED` — is recomputed, the programme's spend-per-visit analytics are
        recomputed, and the visit's `version` increments by 1."

        PRD: "`total_in_park_spend_cents` is the sum of `spend_cents` over the spend set."

        Design: Corner/consistency model/derived_fields_are_current_in_the_same_response
        """
        program, day, pass_ctx = self._open_park(api)
        book_reservation(api, pass_ctx.id, day["id"], "09:00", "12:00")
        visit = record_visit(api, pass_ctx.id, day["id"], "2026-09-01T09:30:00Z")

        closed = close_visit(api, visit["id"], 3000)

        assert closed["status"] == VisitStatus.CLOSED.value, (
            f"the close response carries the new status, got {closed['status']!r}"
        )
        assert closed["spend_cents"] == 3000, (
            f"the spend is stored as tendered, got {closed['spend_cents']!r}"
        )
        assert float(closed["discount_applied_pct"]) == 0.05, (
            "the entering tier's discount is snapshotted, got "
            f"{closed['discount_applied_pct']!r}"
        )
        assert get_pass(api, pass_ctx.id)["in_park_spend_cents"] == 3000, (
            "the pass's spend rollup should already agree with the closed visit"
        )
        assert_revenue_summary(
            revenue_summary(api, program.id),
            spend=3000,
            spend_per_visit=3000,
            visits=1,
            visits_per_active_pass=1.00,
        )
