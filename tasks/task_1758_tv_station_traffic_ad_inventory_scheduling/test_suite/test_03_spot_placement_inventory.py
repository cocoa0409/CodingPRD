"""Spot placement: class-branched headroom, the political reserve fence,
validation-pipeline precedence, capacity boundaries, week-state gating,
break capacity semantics, and commercial separation."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_order_line,
    approve_order,
    create_advertiser,
    create_avail_unit,
    create_avail_week,
    create_order,
    create_program,
    create_received_copy,
    finalize_log_day,
    get_avail_unit,
    get_avail_week,
    get_spot,
    get_success_data,
    list_line_spots,
    place_spot_fresh,
    setup_scheduled_scenario,
    setup_second_advertiser_order,
    submit_order,
    validate_error,
    validate_success,
    create_log_day,
    place_spot_payload,
    preempt_payload,
)

SALESREP = TEST_USERS["salesrep_headers"]
TRAFFIC = TEST_USERS["trafficmanager_headers"]


class TestHeadroomClassBranch:
    def test_commercial_fenced_by_reserve_political_free(self, api):
        """PRD §3.5: "A `POLITICAL` candidate may use any free second in the break: it is accepted when its duration is no greater than the break's `total_seconds` minus its `booked_political_seconds` minus its `booked_commercial_seconds`. A `COMMERCIAL` candidate is fenced out of the political reserve: it is accepted only when the unit's `booked_commercial_seconds` plus the candidate's duration stays at or below the break's `total_seconds` minus its `reserved_political_seconds`."
        PRD §3.5: "When a commercial placement would fit only by dipping into the reserved political seconds, the rejection is `ERR_POLITICAL_RESERVE`; when capacity is exhausted outright, the rejection is `ERR_AVAIL_OVERFLOW`."

        Design: Difficulty/combinatorial_formula/avail_headroom_three_input_conditional_branch
        """
        program = create_program(
            title="Tue News Special", daypart_code="EARLY_NEWS", airs_weekday=2,
            rating_estimate=4.0, is_political_window=True,
        )
        week = create_avail_week("2026-08-03")
        unit = create_avail_unit(
            week["id"], program["id"], "2026-08-04",
            total_seconds=60, reserved_political_seconds=30,
        )
        commercial_adv = create_advertiser(name="A3c", product_category="RETAIL")
        political_adv = create_advertiser(name="A3p", product_category="POLITICAL")
        c_order = create_order(commercial_adv["id"])
        c_line = add_order_line(
            c_order["id"], program["id"], spots_per_week=2, gross_rate_cents=10000
        )
        submit_order(c_order["id"])
        approve_order(c_order["id"])
        p_order = create_order(political_adv["id"])
        p_line = add_order_line(
            p_order["id"], program["id"], spots_per_week=1, gross_rate_cents=10000
        )
        submit_order(p_order["id"])
        approve_order(p_order["id"])
        c_spots = list_line_spots(c_line["id"])
        p_spots = list_line_spots(p_line["id"])
        place_spot_fresh(c_spots[0]["id"], unit["id"])
        assert get_avail_unit(unit["id"])["booked_commercial_seconds"] == 30

        # Second commercial 30s: booked 30 + 30 > capacity 60-30=30 -> reserve fence.
        resp = api.place_spot(
            c_spots[1]["id"],
            place_spot_payload(unit["id"], get_avail_unit(unit["id"])["version"]),
            TRAFFIC,
        )
        validate_error(resp, ApiErrorId.ERR_POLITICAL_RESERVE)

        # Political 30s into the same unit: headroom 60-0-30 = 30, 30 <= 30.
        placed_p = place_spot_fresh(p_spots[0]["id"], unit["id"])
        assert placed_p["status"] == "SCHEDULED"
        assert placed_p["spot_class"] == "POLITICAL"
        unit_after = get_avail_unit(unit["id"])
        assert unit_after["booked_commercial_seconds"] == 30
        assert unit_after["booked_political_seconds"] == 30

    def test_political_spill_beyond_reserve_leaves_commercial_capacity(self, api):
        """PRD §2.6: "The political reserve is a one-way fence. It constrains commercial bookings only: a commercial spot may never push commercial bookings past the break's total seconds minus the reserved political seconds. Political spots face no such fence and may occupy any otherwise-free second in the break, whether inside or outside the reserve."
        PRD §2.6: "Seconds booked by political spots beyond the reserve therefore leave commercial capacity intact per station policy"

        Design: Difficulty/combinatorial_formula/avail_headroom_three_input_conditional_branch
        """
        program = create_program(
            title="Tue Special", daypart_code="EARLY_NEWS", airs_weekday=2,
            rating_estimate=4.0, is_political_window=True,
        )
        week = create_avail_week("2026-08-03")
        unit = create_avail_unit(
            week["id"], program["id"], "2026-08-04",
            total_seconds=60, reserved_political_seconds=30,
        )
        political_adv = create_advertiser(name="SP", product_category="POLITICAL")
        p_order = create_order(political_adv["id"])
        p_line = add_order_line(
            p_order["id"], program["id"], spots_per_week=1,
            spot_length_seconds=60, gross_rate_cents=10000,
        )
        submit_order(p_order["id"])
        approve_order(p_order["id"])
        p_spot = list_line_spots(p_line["id"])[0]
        # Political 60s uses every otherwise-free second: 60 <= 60-0-0.
        placed_p = place_spot_fresh(p_spot["id"], unit["id"])
        assert placed_p["status"] == "SCHEDULED"
        assert get_avail_unit(unit["id"])["booked_political_seconds"] == 60

        # Commercial capacity is still 60-30 = 30 despite 60 political seconds booked.
        commercial_adv = create_advertiser(name="SC", product_category="RETAIL")
        c_order = create_order(commercial_adv["id"])
        c_line = add_order_line(
            c_order["id"], program["id"], spots_per_week=1,
            spot_length_seconds=30, gross_rate_cents=10000,
        )
        submit_order(c_order["id"])
        approve_order(c_order["id"])
        c_spot = list_line_spots(c_line["id"])[0]
        placed_c = place_spot_fresh(c_spot["id"], unit["id"])
        assert placed_c["status"] == "SCHEDULED"
        unit_after = get_avail_unit(unit["id"])
        assert unit_after["booked_commercial_seconds"] == 30
        assert unit_after["booked_political_seconds"] == 60


class TestValidationPipelinePrecedence:
    def test_state_outranks_date_window_on_place(self, api):
        """PRD §2.10: "Every request passes through a fixed validation pipeline, and when several checks would fail, the earliest one in this order determines the error returned."
        PRD §2.10: "Fourth, state legality: the target entity must be in a state from which the requested transition exists — this covers terminal-state lockdowns as well as preemption or finalization attempts against already-finalized logs — else `ERR_INVALID_STATE`. Fifth, date-window coherence per §2.5, else `ERR_DATE_WINDOW`."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_place
        """
        advertiser = create_advertiser(name="A9", product_category="RETAIL")
        advertiser_x = create_advertiser(name="A9x", product_category="RETAIL")
        program = create_program(
            title="Sat Prime 9", daypart_code="PRIME", airs_weekday=6, rating_estimate=5.0
        )
        week_a = create_avail_week("2026-08-03")
        unit_a = create_avail_unit(
            week_a["id"], program["id"], "2026-08-08", total_seconds=120
        )
        week_b = create_avail_week("2026-08-10")
        unit_b = create_avail_unit(
            week_b["id"], program["id"], "2026-08-15", total_seconds=120
        )
        order = create_order(advertiser["id"], "2026-08-03", "2026-08-09")
        line = add_order_line(order["id"], program["id"], spots_per_week=1, gross_rate_cents=9000)
        submit_order(order["id"])
        approve_order(order["id"])
        spot = list_line_spots(line["id"])[0]
        place_spot_fresh(spot["id"], unit_a["id"])

        # Temporal-only control: pending spot, order flight ends 2026-08-05,
        # target air date 2026-08-08 -> date-window error alone.
        order_x = create_order(advertiser_x["id"], "2026-08-03", "2026-08-05")
        line_x = add_order_line(
            order_x["id"], program["id"], spots_per_week=1, gross_rate_cents=9000
        )
        submit_order(order_x["id"])
        approve_order(order_x["id"])
        spot_x = list_line_spots(line_x["id"])[0]
        resp_control = api.place_spot(
            spot_x["id"],
            place_spot_payload(unit_a["id"], get_avail_unit(unit_a["id"])["version"]),
            TRAFFIC,
        )
        validate_error(resp_control, ApiErrorId.ERR_DATE_WINDOW)

        # Dual failure: the spot is already SCHEDULED (state) AND the target
        # air date 2026-08-15 lies outside the flight ending 2026-08-09
        # (temporal) -> the state error wins.
        resp_dual = api.place_spot(
            spot["id"],
            place_spot_payload(unit_b["id"], get_avail_unit(unit_b["id"])["version"]),
            TRAFFIC,
        )
        validate_error(resp_dual, ApiErrorId.ERR_INVALID_STATE)
        assert get_spot(spot["id"])["status"] == "SCHEDULED"
        assert get_avail_unit(unit_b["id"])["booked_commercial_seconds"] == 0

    def test_state_outranks_date_window_on_cancelled_spot(self, api):
        """PRD §2.10: "Every request passes through a fixed validation pipeline, and when several checks would fail, the earliest one in this order determines the error returned."
        PRD §2.10: "Fourth, state legality: the target entity must be in a state from which the requested transition exists — this covers terminal-state lockdowns as well as preemption or finalization attempts against already-finalized logs — else `ERR_INVALID_STATE`. Fifth, date-window coherence per §2.5, else `ERR_DATE_WINDOW`."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_place
        """
        advertiser = create_advertiser(name="A9z", product_category="RETAIL")
        program = create_program(
            title="Sat Prime 9z", daypart_code="PRIME", airs_weekday=6, rating_estimate=5.0
        )
        week = create_avail_week("2026-08-03")
        create_avail_unit(week["id"], program["id"], "2026-08-08", total_seconds=120)
        week_b = create_avail_week("2026-08-10")
        unit_b = create_avail_unit(
            week_b["id"], program["id"], "2026-08-15", total_seconds=120
        )
        order = create_order(advertiser["id"], "2026-08-03", "2026-08-09")
        line = add_order_line(order["id"], program["id"], spots_per_week=1, gross_rate_cents=9000)
        submit_order(order["id"])
        approve_order(order["id"])
        spot = list_line_spots(line["id"])[0]
        # Cancelling the APPROVED order tears down the pending spot.
        validate_success(api.cancel_order(order["id"], SALESREP))
        assert get_spot(spot["id"])["status"] == "CANCELLED"

        # The spot is CANCELLED (state) and 2026-08-15 is outside the flight
        # (temporal) -> ERR_INVALID_STATE, the earlier pipeline stage.
        resp = api.place_spot(
            spot["id"],
            place_spot_payload(unit_b["id"], get_avail_unit(unit_b["id"])["version"]),
            TRAFFIC,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_reserve_outranks_separation_on_place(self, api):
        """PRD §2.10: "Seventh, political inventory protection: a commercial placement that would consume reserved political seconds, or a political-priority preemption attempted against a political spot, is rejected with `ERR_POLITICAL_RESERVE`. Eighth, avail capacity and make-good uniqueness: exhausted headroom or a duplicate outstanding make-good for the same preempted spot yields `ERR_AVAIL_OVERFLOW`. Ninth, commercial separation inside the break, else `ERR_SEPARATION_VIOLATION`."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_constraint_on_place
        """
        advertiser = create_advertiser(name="A10", product_category="RETAIL")
        program = create_program(
            title="Tue News 10", daypart_code="EARLY_NEWS", airs_weekday=2,
            rating_estimate=4.0, is_political_window=True,
        )
        week = create_avail_week("2026-08-03")
        unit = create_avail_unit(
            week["id"], program["id"], "2026-08-04",
            total_seconds=60, reserved_political_seconds=30,
        )
        order = create_order(advertiser["id"])
        line = add_order_line(order["id"], program["id"], spots_per_week=2, gross_rate_cents=10000)
        submit_order(order["id"])
        approve_order(order["id"])
        spots = list_line_spots(line["id"])
        place_spot_fresh(spots[0]["id"], unit["id"])
        assert get_avail_unit(unit["id"])["booked_commercial_seconds"] == 30

        # The second spot both dips into the reserve (30+30 > 30) and lands
        # adjacent to its same-category sibling -> reserve (earlier) wins.
        resp = api.place_spot(
            spots[1]["id"],
            place_spot_payload(unit["id"], get_avail_unit(unit["id"])["version"]),
            TRAFFIC,
        )
        validate_error(resp, ApiErrorId.ERR_POLITICAL_RESERVE)
        assert get_spot(spots[1]["id"])["status"] == "PENDING_PLACEMENT"
        assert get_avail_unit(unit["id"])["booked_commercial_seconds"] == 30

    def test_separation_violation_isolated_without_reserve(self, api):
        """PRD §3.5: "Within a single break, two spots whose advertisers share a `product_category` may not air adjacently: at least one other spot must stand between them in the break's airing order."
        PRD §3.5: "any same-category pair at adjacent positions rejects the placement with `ERR_SEPARATION_VIOLATION`"

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_constraint_on_place
        """
        ctx = setup_scheduled_scenario(
            airs_weekday=2, air_date="2026-08-04", total_seconds=180,
            spots_per_week=2, place_count=1, gross_rate_cents=10000,
        )
        unit = ctx["units"][0]
        second = ctx["spots"][1]
        # Abundant capacity (150s free), reserve 0: separation is the sole failure.
        resp = api.place_spot(
            second["id"],
            place_spot_payload(unit["id"], get_avail_unit(unit["id"])["version"]),
            TRAFFIC,
        )
        validate_error(resp, ApiErrorId.ERR_SEPARATION_VIOLATION)
        assert get_spot(second["id"])["status"] == "PENDING_PLACEMENT"


class TestHeadroomBoundary:
    def test_equality_accepted_overflow_by_one_spot_rejected(self, api):
        """PRD §3.5: "The boundary is inclusive in both branches: a duration exactly equal to the remaining capacity succeeds, and one second more fails."
        PRD §3.5: "When a commercial placement would fit only by dipping into the reserved political seconds, the rejection is `ERR_POLITICAL_RESERVE`; when capacity is exhausted outright, the rejection is `ERR_AVAIL_OVERFLOW`."

        Design: Difficulty/boundary_precision_check/headroom_equality_accepted_overflow_by_one_spot_rejected
        """
        advertiser = create_advertiser(name="A11")
        program = create_program(
            title="Sun Overnight", daypart_code="OVERNIGHT", airs_weekday=7,
            rating_estimate=0.5,
        )
        week = create_avail_week("2026-08-03")
        unit = create_avail_unit(week["id"], program["id"], "2026-08-09", total_seconds=60)
        order = create_order(advertiser["id"])
        line_a = add_order_line(
            order["id"], program["id"], spot_length_seconds=60, gross_rate_cents=5000
        )
        line_b = add_order_line(
            order["id"], program["id"], spot_length_seconds=30, gross_rate_cents=3000
        )
        submit_order(order["id"])
        approve_order(order["id"])
        spot_a = list_line_spots(line_a["id"])[0]
        spot_b = list_line_spots(line_b["id"])[0]

        placed = place_spot_fresh(spot_a["id"], unit["id"])
        assert placed["status"] == "SCHEDULED", "60s into an empty 60s unit: equality accepted"
        assert get_avail_unit(unit["id"])["booked_commercial_seconds"] == 60

        resp = api.place_spot(
            spot_b["id"],
            place_spot_payload(unit["id"], get_avail_unit(unit["id"])["version"]),
            TRAFFIC,
        )
        validate_error(resp, ApiErrorId.ERR_AVAIL_OVERFLOW)
        assert get_avail_unit(unit["id"])["booked_commercial_seconds"] == 60

    def test_political_branch_equality_then_overflow(self, api):
        """PRD §3.5: "A `POLITICAL` candidate may use any free second in the break: it is accepted when its duration is no greater than the break's `total_seconds` minus its `booked_political_seconds` minus its `booked_commercial_seconds`."
        PRD §3.5: "The boundary is inclusive in both branches: a duration exactly equal to the remaining capacity succeeds, and one second more fails."

        Design: Difficulty/boundary_precision_check/headroom_equality_accepted_overflow_by_one_spot_rejected
        """
        advertiser = create_advertiser(name="A11p", product_category="POLITICAL")
        program = create_program(
            title="Sun Pol", daypart_code="OVERNIGHT", airs_weekday=7,
            rating_estimate=0.5, is_political_window=True,
        )
        week = create_avail_week("2026-08-03")
        unit = create_avail_unit(week["id"], program["id"], "2026-08-09", total_seconds=60)
        order = create_order(advertiser["id"])
        line_a = add_order_line(
            order["id"], program["id"], spot_length_seconds=60, gross_rate_cents=5000
        )
        line_b = add_order_line(
            order["id"], program["id"], spot_length_seconds=120, gross_rate_cents=9000
        )
        submit_order(order["id"])
        approve_order(order["id"])
        spot_a = list_line_spots(line_a["id"])[0]
        spot_b = list_line_spots(line_b["id"])[0]

        placed = place_spot_fresh(spot_a["id"], unit["id"])
        assert placed["status"] == "SCHEDULED"
        assert get_avail_unit(unit["id"])["booked_political_seconds"] == 60

        # Political headroom is now 60-60-0 = 0; the 120s candidate exceeds it.
        resp = api.place_spot(
            spot_b["id"],
            place_spot_payload(unit["id"], get_avail_unit(unit["id"])["version"]),
            TRAFFIC,
        )
        validate_error(resp, ApiErrorId.ERR_AVAIL_OVERFLOW)
        assert get_avail_unit(unit["id"])["booked_political_seconds"] == 60


class TestWeekStateGating:
    def test_locked_week_rejects_new_placement(self, api):
        """PRD §3.5: "The spot's owning order must be `APPROVED`, and the owning week must still be `OPEN` — a week locked by log finalization rejects new placements with `ERR_INVALID_STATE`."
        PRD §3.7: "Finalizing a log day also locks its owning week: the week's status moves from `OPEN` to `LOCKED`, freezing new placements into the week per §3.5"

        Design: Difficulty/cross_entity_state_dependency/placement_gated_by_availweek_open
        """
        ctx = setup_scheduled_scenario(
            spots_per_week=2, place_count=1, gross_rate_cents=7000,
            log_date="2026-08-03",
        )
        unit = ctx["units"][0]
        assert get_avail_unit(unit["id"])["booked_commercial_seconds"] == 30
        finalize_log_day(ctx["log"]["id"])
        assert get_avail_week(ctx["week"]["id"])["status"] == "LOCKED"

        second = ctx["spots"][1]
        resp = api.place_spot(
            second["id"],
            place_spot_payload(unit["id"], get_avail_unit(unit["id"])["version"]),
            TRAFFIC,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_spot(second["id"])["status"] == "PENDING_PLACEMENT"
        assert get_avail_unit(unit["id"])["booked_commercial_seconds"] == 30

    def test_lock_is_scoped_to_the_owning_week(self, api):
        """PRD §3.5: "The spot's owning order must be `APPROVED`, and the owning week must still be `OPEN` — a week locked by log finalization rejects new placements with `ERR_INVALID_STATE`."
        PRD §3.2: "Each week is identified by the `week_start_date` of its opening Monday and begins life in `OPEN` status, accepting placements. Later, the week moves to `LOCKED` when a log day inside it is finalized"

        Design: Difficulty/cross_entity_state_dependency/placement_gated_by_availweek_open
        """
        advertiser = create_advertiser(name="A14w")
        program = create_program(
            title="Mon Daytime 14w", daypart_code="DAYTIME", airs_weekday=1, rating_estimate=2.0
        )
        week1 = create_avail_week("2026-08-03")
        unit1 = create_avail_unit(week1["id"], program["id"], "2026-08-03", total_seconds=60)
        week2 = create_avail_week("2026-08-10")
        unit2 = create_avail_unit(week2["id"], program["id"], "2026-08-10", total_seconds=60)
        order = create_order(advertiser["id"], "2026-08-03", "2026-08-16")
        line = add_order_line(order["id"], program["id"], spots_per_week=2, gross_rate_cents=7000)
        submit_order(order["id"])
        approve_order(order["id"])
        create_received_copy(advertiser["id"], 30)
        spots = list_line_spots(line["id"])
        place_spot_fresh(spots[0]["id"], unit1["id"])
        log1 = create_log_day(week1["id"], "2026-08-03")
        finalize_log_day(log1["id"])
        assert get_avail_week(week1["id"])["status"] == "LOCKED"

        placed = place_spot_fresh(spots[1]["id"], unit2["id"])
        assert placed["status"] == "SCHEDULED", "week2 is still OPEN and accepts placements"
        assert get_avail_week(week2["id"])["status"] == "OPEN"


class TestBreakCapacitySemantics:
    def test_aggregate_seconds_shared_until_exhausted(self, api):
        """PRD §3.5: "A `COMMERCIAL` candidate is fenced out of the political reserve: it is accepted only when the unit's `booked_commercial_seconds` plus the candidate's duration stays at or below the break's `total_seconds` minus its `reserved_political_seconds`."
        PRD §3.5: "When a commercial placement would fit only by dipping into the reserved political seconds, the rejection is `ERR_POLITICAL_RESERVE`; when capacity is exhausted outright, the rejection is `ERR_AVAIL_OVERFLOW`."

        Design: Difficulty/resource_temporal_overlap/break_capacity_aggregate_seconds
        """
        advertiser = create_advertiser(name="A16", product_category="RETAIL")
        program = create_program(
            title="Wed Prime 16", daypart_code="PRIME", airs_weekday=3, rating_estimate=5.0
        )
        week = create_avail_week("2026-08-03")
        unit = create_avail_unit(week["id"], program["id"], "2026-08-05", total_seconds=60)
        order = create_order(advertiser["id"])
        line = add_order_line(order["id"], program["id"], spots_per_week=2, gross_rate_cents=6000)
        submit_order(order["id"])
        approve_order(order["id"])
        _, _, _, b_spots = setup_second_advertiser_order(
            program["id"], category="AUTOMOTIVE", gross_rate_cents=6000
        )
        a_spots = list_line_spots(line["id"])

        place_spot_fresh(a_spots[0]["id"], unit["id"])
        place_spot_fresh(b_spots[0]["id"], unit["id"])
        unit_mid = get_avail_unit(unit["id"])
        assert unit_mid["booked_commercial_seconds"] == 60, "two 30s spots share the 60s break"
        # Third spot sits two positions away from its same-category sibling, so
        # separation passes; the aggregate alone rejects it.
        resp = api.place_spot(
            a_spots[1]["id"],
            place_spot_payload(unit["id"], unit_mid["version"]),
            TRAFFIC,
        )
        validate_error(resp, ApiErrorId.ERR_AVAIL_OVERFLOW)
        assert get_spot(a_spots[0]["id"])["status"] == "SCHEDULED"
        assert get_spot(b_spots[0]["id"])["status"] == "SCHEDULED"

    def test_aggregate_pool_is_shared_across_spot_classes(self, api):
        """PRD §3.5: "A `POLITICAL` candidate may use any free second in the break: it is accepted when its duration is no greater than the break's `total_seconds` minus its `booked_political_seconds` minus its `booked_commercial_seconds`."
        PRD §3.5: "when capacity is exhausted outright, the rejection is `ERR_AVAIL_OVERFLOW`"

        Design: Difficulty/resource_temporal_overlap/break_capacity_aggregate_seconds
        """
        program = create_program(
            title="Wed Mix", daypart_code="PRIME", airs_weekday=3, rating_estimate=5.0,
            is_political_window=True,
        )
        week = create_avail_week("2026-08-03")
        unit = create_avail_unit(week["id"], program["id"], "2026-08-05", total_seconds=60)
        commercial_adv = create_advertiser(name="M16c", product_category="RETAIL")
        c_order = create_order(commercial_adv["id"])
        c_line = add_order_line(
            c_order["id"], program["id"], spots_per_week=1, gross_rate_cents=6000
        )
        submit_order(c_order["id"])
        approve_order(c_order["id"])
        political_adv = create_advertiser(name="M16p", product_category="POLITICAL")
        p_order = create_order(political_adv["id"])
        p_line_30 = add_order_line(
            p_order["id"], program["id"], spots_per_week=1, gross_rate_cents=6000
        )
        p_line_15 = add_order_line(
            p_order["id"], program["id"], spots_per_week=1,
            spot_length_seconds=15, gross_rate_cents=3000,
        )
        submit_order(p_order["id"])
        approve_order(p_order["id"])

        place_spot_fresh(list_line_spots(c_line["id"])[0]["id"], unit["id"])
        place_spot_fresh(list_line_spots(p_line_30["id"])[0]["id"], unit["id"])
        unit_mid = get_avail_unit(unit["id"])
        assert unit_mid["booked_commercial_seconds"] == 30
        assert unit_mid["booked_political_seconds"] == 30

        # Political headroom: 60 - 30 - 30 = 0; the 15s candidate exceeds it.
        resp = api.place_spot(
            list_line_spots(p_line_15["id"])[0]["id"],
            place_spot_payload(unit["id"], unit_mid["version"]),
            TRAFFIC,
        )
        validate_error(resp, ApiErrorId.ERR_AVAIL_OVERFLOW)


class TestCommercialSeparation:
    def test_adjacency_rejected_distance_two_accepted(self, api):
        """PRD §3.5: "Airing order is derived by sorting the break's `SCHEDULED` spots by `created_at` ascending — creation order is the fixed tie-break, and the spot `id` is never consulted — and the candidate is evaluated as if appended at the last position, immediately after the final occupant. Numbering positions from 1, the placement is accepted only when every same-category occupant sits more than one position away from the candidate; any same-category pair at adjacent positions rejects the placement with `ERR_SEPARATION_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/break_adjacency_positional_separation
        """
        advertiser = create_advertiser(name="A17", product_category="RETAIL")
        program = create_program(
            title="Thu Prime 17", daypart_code="PRIME", airs_weekday=4, rating_estimate=5.0
        )
        week = create_avail_week("2026-08-03")
        unit = create_avail_unit(week["id"], program["id"], "2026-08-06", total_seconds=180)
        order = create_order(advertiser["id"])
        line = add_order_line(order["id"], program["id"], spots_per_week=2, gross_rate_cents=6000)
        submit_order(order["id"])
        approve_order(order["id"])
        _, _, _, auto_spots = setup_second_advertiser_order(
            program["id"], category="AUTOMOTIVE", gross_rate_cents=6000
        )
        retail = list_line_spots(line["id"])

        place_spot_fresh(retail[0]["id"], unit["id"])
        # Adjacent same-category candidate at position 2 -> rejected.
        resp = api.place_spot(
            retail[1]["id"],
            place_spot_payload(unit["id"], get_avail_unit(unit["id"])["version"]),
            TRAFFIC,
        )
        validate_error(resp, ApiErrorId.ERR_SEPARATION_VIOLATION)

        # Interleave an AUTOMOTIVE spot at position 2, then the RETAIL
        # candidate at position 3 sits distance 2 from position 1 -> accepted.
        place_spot_fresh(auto_spots[0]["id"], unit["id"])
        placed = place_spot_fresh(retail[1]["id"], unit["id"])
        assert placed["status"] == "SCHEDULED"
        assert get_avail_unit(unit["id"])["booked_commercial_seconds"] == 90

    def test_separation_is_scoped_within_a_single_break(self, api):
        """PRD §3.5: "Within a single break, two spots whose advertisers share a `product_category` may not air adjacently: at least one other spot must stand between them in the break's airing order."

        Design: Difficulty/resource_temporal_overlap/break_adjacency_positional_separation
        """
        ctx = setup_scheduled_scenario(
            airs_weekday=4, air_date="2026-08-06", total_seconds=60,
            num_units=2, spots_per_week=2, place_count=1, gross_rate_cents=6000,
        )
        units = ctx["units"]
        second = ctx["spots"][1]
        placed = place_spot_fresh(second["id"], units[1]["id"])
        assert placed["status"] == "SCHEDULED", (
            "a same-category spot in a different break of the same program is unconstrained"
        )
        assert get_avail_unit(units[0]["id"])["booked_commercial_seconds"] == 30
        assert get_avail_unit(units[1]["id"])["booked_commercial_seconds"] == 30


class TestPlacementReferenceAndCounters:
    def test_program_mismatch_rejected(self, api):
        """PRD §3.5: "And the unit must belong to the same program the line buys — a unit whose `program_id` differs from the line's `program_id` is rejected with `ERR_REFERENCE_MISMATCH`."

        Design: Corner/validations/placement_program_mismatch_rejected
        """
        program_x = create_program(
            title="PX", daypart_code="DAYTIME", airs_weekday=1, rating_estimate=2.0
        )
        program_y = create_program(
            title="PY", daypart_code="EARLY_NEWS", airs_weekday=1, rating_estimate=3.0
        )
        week = create_avail_week("2026-08-03")
        unit_y = create_avail_unit(week["id"], program_y["id"], "2026-08-03", total_seconds=60)
        advertiser = create_advertiser(name="RM")
        order = create_order(advertiser["id"])
        line = add_order_line(order["id"], program_x["id"], spots_per_week=1)
        submit_order(order["id"])
        approve_order(order["id"])
        spot = list_line_spots(line["id"])[0]
        resp = api.place_spot(
            spot["id"],
            place_spot_payload(unit_y["id"], get_avail_unit(unit_y["id"])["version"]),
            TRAFFIC,
        )
        validate_error(resp, ApiErrorId.ERR_REFERENCE_MISMATCH)
        assert get_spot(spot["id"])["status"] == "PENDING_PLACEMENT"

    def test_booked_counter_tracks_place_and_preempt(self, api):
        """PRD §2.6: "Both counters start at zero when the unit is created and are maintained thereafter by placement, preemption, cancellation, and reconciliation side effects: placing a spot adds its duration to the bucket matching its class, and preempting or cancelling a scheduled spot releases its duration back."
        PRD §3.5: "A successful placement writes the spot's `avail_unit_id`, copies the unit's air date into the spot's `scheduled_air_date`, adds the line's `spot_length_seconds` to the unit's booked counter for the spot's class bucket, and advances both the spot's `version` and the avail unit's `version`."

        Design: Corner/cross_cutting_layers/derived_fields_reconciled_on_preempt_and_replace
        """
        ctx = setup_scheduled_scenario(airs_weekday=6, air_date="2026-08-08")
        unit = ctx["units"][0]
        spot = ctx["placed"][0]
        assert get_avail_unit(unit["id"])["booked_commercial_seconds"] == 30
        resp = api.preempt_spot(spot["id"], preempt_payload("OVERSOLD"), TRAFFIC)
        validate_success(resp)
        assert get_avail_unit(unit["id"])["booked_commercial_seconds"] == 0
