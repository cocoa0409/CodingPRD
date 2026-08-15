"""Voucher pay computation: estimate vs final variants, tiers, meals, rounding."""
from test_helpers import (
    TEST_USERS,
    add_time_event,
    check_in_booking,
    confirm_booking,
    create_actor,
    create_bump,
    create_casting_call,
    create_production,
    get_voucher_for_booking,
    issue_voucher,
    lock_call,
    set_clock,
    setup_wrapped_day,
    start_shooting,
    validate_success,
    wrap_out_booking,
)

ASSOC = TEST_USERS["associate_headers"]


def _two_actor_day(rate=10000, duration=720, meals=(), wrap_at="2026-08-10T17:31:00Z",
                   union_slots=1, nonunion_slots=1):
    """One SAG_AFTRA and one NONUNION booking through a full shoot day on the
    same call; identical event timelines. Returns (voucherU, voucherN)."""
    prod = create_production(active=True)
    call = create_casting_call(
        prod["id"],
        publish=True,
        union_slots=union_slots,
        nonunion_slots=nonunion_slots,
        union_rate_cents=rate,
        nonunion_rate_cents=rate,
        scheduled_duration_minutes=duration,
        location="Lot 5",
    )
    actor_u = create_actor("SAG_AFTRA", legal_name="U Tier")
    actor_n = create_actor("NONUNION", legal_name="N Tier")
    b_u = confirm_booking(call["id"], actor_u["id"])
    b_n = confirm_booking(call["id"], actor_n["id"])
    lock_call(call["id"])
    start_shooting(call["id"])
    check_in_booking(b_u["id"], at="2026-08-10T07:00:00Z")
    check_in_booking(b_n["id"], at="2026-08-10T07:00:00Z")
    for booking in (b_u, b_n):
        for meal_out, meal_in in meals:
            add_time_event(booking["id"], "MEAL_OUT", meal_out)
            add_time_event(booking["id"], "MEAL_IN", meal_in)
    set_clock(wrap_at)
    wrap_out_booking(b_u["id"])
    wrap_out_booking(b_n["id"])
    return (
        get_voucher_for_booking(b_u["id"]),
        get_voucher_for_booking(b_n["id"]),
    )


class TestEstimateVsFinal:
    def _scenario(self, api):
        """NONUNION rate 10000, duration 600; check-in 07:00; timely meal
        12:00-12:30; wrap 16:00 (net 510); one PENDING bump of 2500."""
        prod, call, actor, booking, voucher = setup_wrapped_day(
            meals=[("2026-08-10T12:00:00Z", "2026-08-10T12:30:00Z")],
            wrap_at="2026-08-10T16:00:00Z",
        )
        create_bump(voucher["id"], amount_cents=2500, requester="assoc-1")
        return voucher

    def test_estimate_uses_scheduled_wrap_and_pending_bumps(self, api):
        """PRD §3.6: "The voucher's estimate — available in any state before
        `PAID` — is forward-looking: it substitutes the scheduled wrap (the
        booking's `call_time` plus the call's `scheduled_duration_minutes`) for
        actual events, assumes exactly one timely thirty-minute meal, so the
        scheduled net is `scheduled_duration_minutes` minus 30 and never below
        zero, runs the same tier formula with `meal_penalty_count` zero, and
        counts both `PENDING` and `APPROVED` bumps in its bump total, with the
        same per-component rounding."

        Design: Difficulty/dual_variant_calc/voucher_estimate_vs_final_divergence
        """
        voucher = self._scenario(api)
        est = validate_success(api.get_voucher_estimate(voucher["id"], ASSOC), 200)
        # scheduled net 570: base 10000 + ot1 90m -> 2813 + PENDING bump 2500
        assert est["estimated_gross_cents"] == 15313
        assert est["estimated_net_work_minutes"] == 570

    def test_final_uses_actual_replay_and_approved_bumps_only(self, api):
        """PRD §3.6: "`bumps_total_cents` is the sum of `amount_cents` across the
        voucher's `APPROVED` bump adjustments — pending claims do not yet count."
        PRD §3.6: "`net_work_minutes` then subtracts from the gross elapsed time
        the durations of the timely meals only — a penalized meal remains paid
        time and is not deducted."

        Design: Difficulty/dual_variant_calc/voucher_estimate_vs_final_divergence
        """
        voucher = self._scenario(api)
        issued = issue_voucher(voucher["id"], issuer="assoc-1")
        # actual net 510: base 10000 + ot1 30m -> 938; PENDING bump excluded
        assert issued["net_work_minutes"] == 510
        assert issued["gross_total_cents"] == 10938
        assert issued["bumps_total_cents"] == 0
        # The forward-looking estimate for the same voucher diverges upward.
        est = validate_success(api.get_voucher_estimate(voucher["id"], ASSOC), 200)
        assert est["estimated_gross_cents"] != issued["gross_total_cents"]


class TestTieredOvertime:
    def test_union_tier_boundaries(self, api):
        """PRD §3.6: "For a union booking, regular minutes are the smaller of n
        and 480; first-tier overtime minutes are the portion of n beyond 480,
        capped at 120; second-tier overtime minutes are the portion of n beyond
        600."

        Design: Difficulty/combinatorial_formula/tiered_overtime_branch_by_union_status
        """
        voucher_u, _voucher_n = _two_actor_day(
            rate=9600,
            meals=[("2026-08-10T12:00:00Z", "2026-08-10T12:30:00Z")],
            wrap_at="2026-08-10T17:31:00Z",
        )
        issued = issue_voucher(voucher_u["id"], issuer="assoc-1")
        assert issued["net_work_minutes"] == 601
        assert issued["ot_tier1_minutes"] == 120
        assert issued["ot_tier2_minutes"] == 1
        # hourly 1200: base 9600 + ot1 3600 + ot2 40
        assert issued["gross_total_cents"] == 13240

    def test_nonunion_tier_boundaries(self, api):
        """PRD §3.6: "For a non-union booking the regular portion is likewise
        capped at 480, but first-tier overtime runs to a cap of 240 minutes and
        second-tier accrues only beyond 720 minutes."

        Design: Difficulty/combinatorial_formula/tiered_overtime_branch_by_union_status
        """
        _voucher_u, voucher_n = _two_actor_day(
            rate=9600,
            meals=[("2026-08-10T12:00:00Z", "2026-08-10T12:30:00Z")],
            wrap_at="2026-08-10T17:31:00Z",
        )
        issued = issue_voucher(voucher_n["id"], issuer="assoc-1")
        assert issued["net_work_minutes"] == 601
        assert issued["ot_tier1_minutes"] == 121
        assert issued["ot_tier2_minutes"] == 0
        # hourly 1200: base 9600 + ot1 3630
        assert issued["gross_total_cents"] == 13230


class TestRoundingOrder:
    def _scenario(self, api):
        """NONUNION rate 10005; check-in 07:00; LATE meal 13:01-13:21; wrap 15:24
        (elapsed 504; late meal not deducted -> net 504; penalty 1)."""
        return setup_wrapped_day(
            meals=[("2026-08-10T13:01:00Z", "2026-08-10T13:21:00Z")],
            wrap_at="2026-08-10T15:24:00Z",
            union_rate_cents=10005,
            nonunion_rate_cents=10005,
            scheduled_duration_minutes=480,
            location="Lot 6",
        )

    def test_per_component_rounding_then_sum_gross(self, api):
        """PRD §2.8: "Intermediate arithmetic may carry fractional cents, but each
        payable component of a voucher is rounded half up to whole cents on its
        own, and the components are then summed — the system never sums unrounded
        components and rounds once at the end."

        Design: Difficulty/combinatorial_formula/per_component_rounding_then_sum
        """
        _p, _c, _a, _b, voucher = self._scenario(api)
        issued = issue_voucher(voucher["id"], issuer="assoc-1")
        assert issued["net_work_minutes"] == 504
        assert issued["meal_penalty_count"] == 1
        # per-component rounding: 10005 + 750 + 625 = 11380 (sum-then-round of
        # the unrounded components would give 11381 and is wrong).
        assert issued["gross_total_cents"] == 11380

    def test_per_component_rounding_components(self, api):
        """PRD §3.6: "`base_wages_cents` is the regular minutes divided by sixty
        and multiplied by the hourly rate, rounded half up to whole cents."
        PRD §3.6: "`ot_wages_cents` is the sum of two independently rounded
        components: first-tier minutes divided by sixty, multiplied by the hourly
        rate and by one and a half, rounded half up; plus second-tier minutes
        divided by sixty, multiplied by the hourly rate and by two, rounded half
        up."
        PRD §3.6: "`meal_penalty_cents` is half the hourly rate, rounded half up
        to whole cents, multiplied by `meal_penalty_count`."

        Design: Difficulty/combinatorial_formula/per_component_rounding_then_sum
        """
        _p, _c, _a, _b, voucher = self._scenario(api)
        issued = issue_voucher(voucher["id"], issuer="assoc-1")
        # hourly = 10005/8 = 1250.625
        assert issued["base_wages_cents"] == 10005      # 480/60 * 1250.625
        assert issued["ot_wages_cents"] == 750          # 24/60 * 1250.625 * 1.5 = 750.375
        assert issued["meal_penalty_cents"] == 625      # 625.3125 -> 625, x1
        assert (
            issued["gross_total_cents"]
            == issued["base_wages_cents"]
            + issued["ot_wages_cents"]
            + issued["meal_penalty_cents"]
            + issued["bumps_total_cents"]
        )


class TestMealTimeliness:
    def _scenario(self, api):
        """Two NONUNION bookings on one call; check-in 07:00; wrap 15:30.
        Booking A meal 13:00-13:30 (exactly 360 elapsed minutes); booking B meal
        13:01-13:31 (361 elapsed minutes)."""
        prod = create_production(active=True)
        call = create_casting_call(
            prod["id"],
            publish=True,
            union_slots=0,
            nonunion_slots=2,
            scheduled_duration_minutes=600,
            location="Lot 7",
        )
        actor_a = create_actor("NONUNION", legal_name="N Timely")
        actor_b = create_actor("NONUNION", legal_name="N Late")
        b_a = confirm_booking(call["id"], actor_a["id"])
        b_b = confirm_booking(call["id"], actor_b["id"])
        lock_call(call["id"])
        start_shooting(call["id"])
        check_in_booking(b_a["id"], at="2026-08-10T07:00:00Z")
        check_in_booking(b_b["id"], at="2026-08-10T07:00:00Z")
        add_time_event(b_a["id"], "MEAL_OUT", "2026-08-10T13:00:00Z")
        add_time_event(b_a["id"], "MEAL_IN", "2026-08-10T13:30:00Z")
        add_time_event(b_b["id"], "MEAL_OUT", "2026-08-10T13:01:00Z")
        add_time_event(b_b["id"], "MEAL_IN", "2026-08-10T13:31:00Z")
        set_clock("2026-08-10T15:30:00Z")
        wrap_out_booking(b_a["id"])
        wrap_out_booking(b_b["id"])
        return get_voucher_for_booking(b_a["id"]), get_voucher_for_booking(b_b["id"])

    def test_meal_at_exactly_360_minutes_is_timely(self, api):
        """PRD §3.6: "Meal timeliness is judged on gross elapsed time, never on
        net: the first meal is timely when its `MEAL_OUT` occurs no more than 360
        minutes — six hours — after check-in, and each later meal is timely when
        its `MEAL_OUT` occurs no more than 360 minutes after the previous meal's
        `MEAL_IN`; a meal beginning at exactly the 360-minute mark counts as
        timely."

        Design: Difficulty/combinatorial_formula/meal_timeliness_evaluation_order
        """
        voucher_a, _voucher_b = self._scenario(api)
        issued = issue_voucher(voucher_a["id"], issuer="assoc-1")
        assert issued["meal_penalty_count"] == 0
        assert issued["net_work_minutes"] == 480  # timely 30m meal deducted from 510
        assert issued["gross_total_cents"] == 10000

    def test_meal_at_361_minutes_is_late_and_not_deducted(self, api):
        """PRD §3.6: "`net_work_minutes` then subtracts from the gross elapsed
        time the durations of the timely meals only — a penalized meal remains
        paid time and is not deducted."
        PRD §3.6: "`meal_penalty_count` tallies the out-of-window meals."

        Design: Difficulty/combinatorial_formula/meal_timeliness_evaluation_order
        """
        _voucher_a, voucher_b = self._scenario(api)
        issued = issue_voucher(voucher_b["id"], issuer="assoc-1")
        assert issued["meal_penalty_count"] == 1
        assert issued["net_work_minutes"] == 510  # penalty meal not deducted
        assert issued["ot_tier1_minutes"] == 30
        # base 10000 + ot1 938 + penalty 625
        assert issued["gross_total_cents"] == 11563


class TestOvertimeBoundary:
    def test_overtime_zero_at_exactly_480_minutes(self, api):
        """PRD §3.6: "For a union booking, regular minutes are the smaller of n
        and 480; first-tier overtime minutes are the portion of n beyond 480,
        capped at 120; second-tier overtime minutes are the portion of n beyond
        600." — at n == 480 no minute lies beyond 480, so both tiers are zero.

        Design: Difficulty/boundary_precision_check/overtime_zero_at_exactly_480_minutes
        """
        _p, _c, _a, _b, voucher = setup_wrapped_day(
            union_status="SAG_AFTRA",
            union_slots=1,
            nonunion_slots=0,
            scheduled_duration_minutes=480,
            location="Lot 15",
            meals=[("2026-08-10T12:00:00Z", "2026-08-10T12:30:00Z")],
            wrap_at="2026-08-10T15:30:00Z",
        )
        issued = issue_voucher(voucher["id"], issuer="assoc-1")
        assert issued["net_work_minutes"] == 480  # elapsed 510 minus timely 30m meal
        assert issued["ot_tier1_minutes"] == 0
        assert issued["ot_tier2_minutes"] == 0
        assert issued["ot_wages_cents"] == 0

    def test_gross_equals_day_rate_at_480_boundary(self, api):
        """PRD §3.6: "the daily rate buys an eight-hour day" — with exactly 480
        net minutes the gross is exactly the day rate with no overtime
        component.

        Design: Difficulty/boundary_precision_check/overtime_zero_at_exactly_480_minutes
        """
        _p, _c, _a, _b, voucher = setup_wrapped_day(
            union_status="SAG_AFTRA",
            union_slots=1,
            nonunion_slots=0,
            scheduled_duration_minutes=480,
            location="Lot 15",
            meals=[("2026-08-10T12:00:00Z", "2026-08-10T12:30:00Z")],
            wrap_at="2026-08-10T15:30:00Z",
        )
        issued = issue_voucher(voucher["id"], issuer="assoc-1")
        assert issued["gross_total_cents"] == 10000
        assert issued["base_wages_cents"] == 10000
        assert issued["meal_penalty_count"] == 0


class TestMealEdgeCases:
    def test_correction_event_substitution_replay(self, api, associate_headers):
        """PRD §3.6: "The effective event set takes all of the booking's time
        events and excludes any event that another event's `corrects_event_id`
        supersedes; a correction is itself effective unless a later correction
        supersedes it in turn, so chains of corrections resolve to their last
        link."
        PRD §3.4: "superseding it without erasing it."

        Design: Corner/calculations/correction_event_substitution_replay
        """
        prod, call, actor, booking, voucher = setup_wrapped_day(
            meals=[("2026-08-10T13:01:00Z", "2026-08-10T13:31:00Z")],
            wrap_at="2026-08-10T15:30:00Z",
            location="Lot 50",
        )
        # Correct the late meal to a timely one (12:00-12:30).
        events = validate_success(
            api.list_time_events(associate_headers, params={"booking_id": booking["id"]}),
            200,
        )
        original_out = next(e for e in events if e["event_type"] == "MEAL_OUT")
        original_in = next(e for e in events if e["event_type"] == "MEAL_IN")
        add_time_event(
            booking["id"], "MEAL_OUT", "2026-08-10T12:00:00Z",
            corrects_event_id=original_out["id"],
        )
        add_time_event(
            booking["id"], "MEAL_IN", "2026-08-10T12:30:00Z",
            corrects_event_id=original_in["id"],
        )

        issued = issue_voucher(voucher["id"], issuer="assoc-1")
        assert issued["meal_penalty_count"] == 0  # corrected meal timely: 300 <= 360
        assert issued["net_work_minutes"] == 480  # timely 30m meal deducted from 510
        assert issued["gross_total_cents"] == 10000

        # Superseded events remain stored (2 auto + 2 original + 2 corrections).
        all_events = validate_success(
            api.list_time_events(associate_headers, params={"booking_id": booking["id"]}),
            200,
        )
        assert len(all_events) == 6

    def test_short_day_no_meal_no_penalty(self, api):
        """PRD §3.6: "`meal_penalty_count` tallies the out-of-window meals, adds
        one further violation when the gross elapsed time exceeds 360 minutes and
        no meal was taken at all, and caps the total at 3 violations." — a
        330-minute day never exceeds the window, so no violation accrues.

        Design: Corner/calculations/short_day_no_meal_no_penalty
        """
        _p, _c, _a, _b, voucher = setup_wrapped_day(
            scheduled_duration_minutes=330,
            location="Lot 51",
            wrap_at="2026-08-10T12:30:00Z",
        )
        issued = issue_voucher(voucher["id"], issuer="assoc-1")
        assert issued["meal_penalty_count"] == 0
        assert issued["net_work_minutes"] == 330
        assert issued["gross_total_cents"] == 6875  # 330/60 * 1250

    def test_long_day_missing_meal_penalty(self, api):
        """PRD §3.6: "`meal_penalty_count` tallies the out-of-window meals, adds
        one further violation when the gross elapsed time exceeds 360 minutes and
        no meal was taken at all, and caps the total at 3 violations."

        Design: Corner/calculations/long_day_missing_meal_penalty
        """
        _p, _c, _a, _b, voucher = setup_wrapped_day(
            location="Lot 52",
            wrap_at="2026-08-10T15:30:00Z",  # elapsed 510, zero meals
        )
        issued = issue_voucher(voucher["id"], issuer="assoc-1")
        assert issued["meal_penalty_count"] == 1
        assert issued["net_work_minutes"] == 510
        assert issued["ot_tier1_minutes"] == 30
        assert issued["gross_total_cents"] == 11563  # 10000 + 938 + 625
