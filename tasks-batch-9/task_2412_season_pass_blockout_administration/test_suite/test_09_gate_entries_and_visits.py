"""The turnstile: the gate guard ladder, the anti-passback buffer and visit records."""

from test_helpers import (
    BRONZE,
    GOLD,
    ApiErrorId,
    BlockoutSource,
    BlockoutStatus,
    GateCode,
    ProgramStatus,
    VisitStatus,
    assert_ordered_by,
    ReservationStatus,
    assert_day_counters,
    assert_grant_count_conserved,
    assert_revenue_summary,
    close_visit,
    book_reservation,
    build_active_pass,
    build_peak_day,
    build_program,
    clerk_headers,
    create_blockout,
    create_park_day,
    gate_agent_headers,
    get_park_day,
    get_pass,
    get_passholder,
    record_visit,
    revenue_summary,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    visit_payload,
)


def _visits_of(api, season_pass_id):
    response = api.list_visits(headers=clerk_headers(), params={"season_pass_id": season_pass_id})
    return validate_paginated(response)


def _cases_of(api, season_pass_id):
    response = api.list_sharing_cases(
        headers=clerk_headers(), params={"season_pass_id": season_pass_id}
    )
    return validate_paginated(response)


class TestAntipassbackPrecedesBlockout:
    """The safety band is evaluated above the business-temporal band."""

    def _blocked_day_after_one_entry(self, api):
        set_clock(api, "2026-08-05T08:00:00Z")
        program = build_program(api, tiers=(BRONZE,), status=ProgramStatus.SEASON_ACTIVE.value)
        day = create_park_day(api, program.id, "2026-08-05")
        pass_ctx = build_active_pass(api, program, tier_name="BRONZE")
        record_visit(api, pass_ctx.id, day["id"], "2026-08-05T09:00:00Z", GateCode.NORTH.value)
        assignment = create_blockout(api, program.tier_id("BRONZE"), day["id"])
        return program, day, pass_ctx, assignment

    def test_a_scan_at_exactly_ninety_minutes_reports_the_safety_violation(self, api):
        """Band nine answers before band ten, so the buffer masks the blockout.

        PRD: "9. **Business safety** — the transfer-prohibition hold, then the
        anti-passback buffer."

        Design: Difficulty/priority_pair_validation_conflict/gate_entry_antipassback_safety_precedes_blockout_temporal
        """
        _, day, pass_ctx, assignment = self._blocked_day_after_one_entry(api)

        response = api.create_visit(
            visit_payload(pass_ctx.id, day["id"], "2026-08-05T10:30:00Z", GateCode.SOUTH.value),
            headers=gate_agent_headers(),
        )

        validate_error(response, ApiErrorId.ERR_ANTIPASSBACK_VIOLATION.value, 422)
        _, meta = _visits_of(api, pass_ctx.id)
        assert meta["total_count"] == 1, (
            f"the refused scan must not create a visit, got {meta['total_count']!r} visits"
        )
        assert get_pass(api, pass_ctx.id)["visit_count"] == 1, (
            "the refused scan must not raise visit_count"
        )
        assert assignment["status"] == BlockoutStatus.ACTIVE.value, (
            f"the blockout should still be ACTIVE, got {assignment['status']!r}"
        )
        assert assignment["source"] == BlockoutSource.MANUAL.value, (
            f"an administrator-created blockout records MANUAL, got {assignment['source']!r}"
        )

    def test_one_minute_past_the_buffer_the_blockout_rule_becomes_visible(self, api):
        """With the buffer cleared, the blockout coverage rung answers.

        PRD: "8. An active blockout assignment covering the pass's `tier_id` and this
        `park_day_id` is refused with `ERR_BLOCKOUT_DATE`."

        Design: Difficulty/priority_pair_validation_conflict/gate_entry_antipassback_safety_precedes_blockout_temporal
        """
        _, day, pass_ctx, _ = self._blocked_day_after_one_entry(api)

        response = api.create_visit(
            visit_payload(pass_ctx.id, day["id"], "2026-08-05T10:31:00Z", GateCode.SOUTH.value),
            headers=gate_agent_headers(),
        )

        validate_error(response, ApiErrorId.ERR_BLOCKOUT_DATE.value, 422)
        _, meta = _visits_of(api, pass_ctx.id)
        assert meta["total_count"] == 1, (
            f"neither refused scan should have created a visit, got {meta['total_count']!r}"
        )


class TestAntipassbackClosedBuffer:
    """The ninety-minute buffer includes its own endpoint."""

    def _pass_with_one_entry(self, api):
        set_clock(api, "2026-08-05T08:00:00Z")
        program = build_program(api, tiers=(GOLD,), status=ProgramStatus.SEASON_ACTIVE.value)
        day = create_park_day(api, program.id, "2026-08-05")
        pass_ctx = build_active_pass(api, program, tier_name="GOLD")
        record_visit(api, pass_ctx.id, day["id"], "2026-08-05T09:00:00Z", GateCode.NORTH.value)
        return program, day, pass_ctx

    def test_the_second_scan_at_exactly_ninety_minutes_is_still_a_violation(self, api):
        """The endpoint of the buffer is inside it.

        PRD: "The buffer is a closed one: a second scan at exactly 90 minutes after the
        first is still a violation, and only a gap strictly greater than an hour and a
        half is permitted."

        Design: Difficulty/resource_temporal_overlap/gate_entry_antipassback_closed_buffer_on_pass
        """
        _, day, pass_ctx = self._pass_with_one_entry(api)

        response = api.create_visit(
            visit_payload(pass_ctx.id, day["id"], "2026-08-05T10:30:00Z", GateCode.SOUTH.value),
            headers=gate_agent_headers(),
        )

        validate_error(response, ApiErrorId.ERR_ANTIPASSBACK_VIOLATION.value, 422)
        _, meta = _visits_of(api, pass_ctx.id)
        assert meta["total_count"] == 1, (
            f"the pass should still have exactly one visit, got {meta['total_count']!r}"
        )

    def test_a_gap_strictly_greater_than_the_buffer_is_admitted(self, api):
        """Ninety-one minutes clears the buffer and opens a second visit.

        PRD: "If any earlier visit of the same pass has an `entry_at` falling within 90
        minutes before the requested `entry_at`, the entry is refused with
        `ERR_ANTIPASSBACK_VIOLATION` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/gate_entry_antipassback_closed_buffer_on_pass
        """
        _, day, pass_ctx = self._pass_with_one_entry(api)

        second = validate_success(
            api.create_visit(
                visit_payload(pass_ctx.id, day["id"], "2026-08-05T10:31:00Z", GateCode.SOUTH.value),
                headers=gate_agent_headers(),
            ),
            201,
        )

        assert second["status"] == VisitStatus.OPEN.value, (
            f"a successful entry opens the visit, got {second['status']!r}"
        )
        assert second["gate_code"] == GateCode.SOUTH.value, (
            f"the visit should record the turnstile bank used, got {second['gate_code']!r}"
        )
        rows, meta = _visits_of(api, pass_ctx.id)
        assert meta["total_count"] == 2, (
            f"the pass should now have two visits, got {meta['total_count']!r}"
        )
        assert_ordered_by(rows, "entry_at")
        assert get_pass(api, pass_ctx.id)["visit_count"] == 2, (
            "visit_count should count both entries"
        )
        assert get_passholder(api, pass_ctx.holder_id)["sharing_risk_score"] == 0, (
            "two matched entries on an ordinary day score nothing under the rolling window"
        )
        _, case_meta = _cases_of(api, pass_ctx.id)
        assert case_meta["total_count"] == 0, (
            f"a score of zero opens no investigation, got {case_meta['total_count']!r} cases"
        )


class TestEntryRedeemsTheBooking:
    """An entry inside the arrival window redeems the reservation that covers it."""

    def test_the_scan_redeems_the_confirmed_reservation_and_links_both_records(
        self, api, default_clock
    ):
        """The booking and the visit point at each other and the day recounts.

        PRD: "If the pass holds a reservation on that day whose `status` is `CONFIRMED`
        and whose half-open arrival window contains the `entry_at` instant, that
        reservation is redeemed: it moves `CONFIRMED → REDEEMED`, its `redeemed_visit_id` is
        set to the new visit's `id`, the visit's own `reservation_id` is set to the
        reservation's `id`, the day's `reserved_count`, `redeemed_count` and
        `remaining_slot_count` are recomputed, and the reservation's `version` increments by
        1."

        Design: Corner/state_machines/gate_entry_redeems_the_matching_confirmed_reservation
        """
        program = build_program(api, tiers=(BRONZE,), status=ProgramStatus.SEASON_ACTIVE.value)
        day = build_peak_day(api, program.id, "2026-09-10")
        pass_ctx = build_active_pass(api, program, tier_name="BRONZE")
        reservation = book_reservation(api, pass_ctx.id, day["id"], "09:00", "12:00")

        visit = record_visit(
            api, pass_ctx.id, day["id"], "2026-09-10T09:30:00Z", GateCode.NORTH.value
        )

        assert visit["status"] == VisitStatus.OPEN.value, (
            f"a successful entry opens the visit, got {visit['status']!r}"
        )
        assert visit["spend_cents"] == 0, (
            f"a new visit records no spend yet, got {visit['spend_cents']!r}"
        )
        assert visit["reservation_id"] == reservation["id"], (
            f"the visit should name the redeemed booking, got {visit['reservation_id']!r}"
        )
        redeemed = validate_success(
            api.get_reservation(reservation["id"], headers=clerk_headers())
        )
        assert redeemed["status"] == ReservationStatus.REDEEMED.value, (
            f"the booking should be REDEEMED, got {redeemed['status']!r}"
        )
        assert redeemed["redeemed_visit_id"] == visit["id"], (
            f"the booking should name the redeeming visit, got {redeemed['redeemed_visit_id']!r}"
        )
        day_row = get_park_day(api, day["id"])
        assert_day_counters(day_row, reserved=0, redeemed=1, released=0, no_show=0, remaining=4, grant=1)
        assert_grant_count_conserved(day_row)
        assert get_pass(api, pass_ctx.id)["visit_count"] == 1, (
            "the entry should raise the pass visit count to one"
        )


class TestPeakReservationRequirementFollowsTheTier:
    """The requirement is a tier setting read on the day, not a property of the day."""

    def _peak_day_with_two_unreserved_holders(self, api):
        program = build_program(api, tiers=(BRONZE, GOLD), status=ProgramStatus.SEASON_ACTIVE.value)
        day = build_peak_day(api, program.id, "2026-09-15")
        bronze = build_active_pass(
            api, program, tier_name="BRONZE", holder_overrides={"email": "req-bronze@example.com"}
        )
        gold = build_active_pass(
            api, program, tier_name="GOLD", holder_overrides={"email": "req-gold@example.com"}
        )
        return program, day, bronze, gold

    def test_the_tier_that_requires_a_reservation_is_turned_away(self, api, default_clock):
        """Rung nine fires for the BRONZE holder who holds no booking.

        PRD: "9. **The peak-day reservation requirement.** When the park day's `day_class`
        is `PEAK` or `CAPACITY_LOCKED`, and the pass's tier has `reservation_required_on_peak`
        set true, and the pass holds no reservation in `CONFIRMED` on that day, the entry is
        refused with `ERR_RESERVATION_REQUIRED` (HTTP 422)."

        Design: Corner/validations/visit_reservation_requirement_applies_only_when_the_tier_flag_is_set
        """
        _, day, bronze, _ = self._peak_day_with_two_unreserved_holders(api)

        response = api.create_visit(
            visit_payload(bronze.id, day["id"], "2026-09-15T10:00:00Z", GateCode.NORTH.value),
            headers=gate_agent_headers(),
        )

        validate_error(response, ApiErrorId.ERR_RESERVATION_REQUIRED.value, 422)
        assert get_pass(api, bronze.id)["visit_count"] == 0, (
            "a refused entry must not raise the visit count"
        )
        assert_day_counters(get_park_day(api, day["id"]), redeemed=0, reserved=0)

    def test_the_tier_whose_flag_is_false_walks_straight_in(self, api, default_clock):
        """On the very same day the GOLD holder needs no booking at all.

        PRD: "On a day that required no reservation and where none was held, the visit's
        `reservation_id` stays null."

        Design: Corner/validations/visit_reservation_requirement_applies_only_when_the_tier_flag_is_set
        """
        _, day, _, gold = self._peak_day_with_two_unreserved_holders(api)

        visit = record_visit(
            api, gold.id, day["id"], "2026-09-15T10:05:00Z", GateCode.NORTH.value
        )

        assert visit["status"] == VisitStatus.OPEN.value, (
            f"the unreserved GOLD entry should open a visit, got {visit['status']!r}"
        )
        assert visit["reservation_id"] is None, (
            f"no booking was redeemed, got reservation_id {visit['reservation_id']!r}"
        )
        assert get_pass(api, gold.id)["visit_count"] == 1, (
            "the accepted entry should raise the visit count to one"
        )
        assert_day_counters(get_park_day(api, day["id"]), redeemed=0, reserved=0, grant=0)
        assert get_passholder(api, gold.holder_id)["sharing_risk_score"] == 0, (
            "a single entry on a peak day scores nothing"
        )


class TestClosingAVisitBooksTheSpend:
    """The close action is the only place in-park spend enters the system."""

    def _open_gold_visit(self, api):
        program = build_program(api, tiers=(GOLD,), status=ProgramStatus.SEASON_ACTIVE.value)
        day = create_park_day(
            api, program.id, "2026-09-01", capacity_total=1000, forecast_attendance=100
        )
        pass_ctx = build_active_pass(api, program, tier_name="GOLD")
        visit = record_visit(
            api, pass_ctx.id, day["id"], "2026-09-01T10:00:00Z", GateCode.NORTH.value
        )
        return program, day, pass_ctx, visit

    def test_the_close_snapshots_the_entering_tier_s_discount_onto_the_visit(
        self, api, default_clock
    ):
        """The percentage is copied from the tier at close time, not referenced later.

        PRD: "The visit moves `OPEN → CLOSED`, `spend_cents` is stored,
        `discount_applied_pct` is snapshotted from the entering tier's
        `in_park_discount_pct` so that a later upgrade cannot rewrite history, the recorded
        `spend_cents` is net of that discount, the pass's `in_park_spend_cents` — the sum of
        `spend_cents` over its visits in `CLOSED` — is recomputed, the programme's
        spend-per-visit analytics are recomputed, and the visit's `version` increments by
        1."

        Design: Corner/endpoints/visit_close_action_applies_the_tier_discount_to_the_spend
        """
        _, day, pass_ctx, visit = self._open_gold_visit(api)

        closed = close_visit(api, visit["id"], 5000)

        assert closed["status"] == VisitStatus.CLOSED.value, (
            f"the close should move the visit to CLOSED, got {closed['status']!r}"
        )
        assert closed["spend_cents"] == 5000, (
            f"the tendered spend should be stored, got {closed['spend_cents']!r}"
        )
        assert float(closed["discount_applied_pct"]) == 0.15, (
            "the GOLD tier's in-park discount should be snapshotted, got "
            f"{closed['discount_applied_pct']!r}"
        )
        assert get_pass(api, pass_ctx.id)["in_park_spend_cents"] == 5000, (
            "the pass should carry the sum of its closed visits' spend"
        )
        assert_day_counters(get_park_day(api, day["id"]), redeemed=0, reserved=0)

    def test_the_spend_lands_in_the_programme_rollup_without_touching_base_revenue(
        self, api, default_clock
    ):
        """Spend is analytics, not contract value.

        PRD: "`total_in_park_spend_cents` is the sum of `spend_cents` over the spend set."

        Design: Corner/endpoints/visit_close_action_applies_the_tier_discount_to_the_spend
        """
        program, _, _, visit = self._open_gold_visit(api)

        close_visit(api, visit["id"], 5000)

        summary = revenue_summary(api, program.id)
        assert_revenue_summary(
            summary, spend=5000, spend_per_visit=5000, visits=1, base=30000
        )
