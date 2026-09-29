"""Derived numbers: segment arithmetic, constant tables, precision and input sets.

Every figure here is recomputed by hand from the stamps and the declared
constants, so a plausible-but-wrong rounding or filter shows up immediately.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions as a
from test_helpers import fixtures as fx
from test_helpers.api_client import DriveThruApiClient
from test_helpers.test_users import ADMIN_HEADERS


# ------------------------------------------------ the five measured segments
def _car_at_the_window(api: DriveThruApiClient):
    """A SINGLE-lane car stamped 11:00:00 / 11:00:20 / 11:01:00 / 11:02:00."""
    fx.setup_single_unbounded_band(api)
    ctx = fx.setup_store(
        api,
        "C-2398-24",
        staff_name="Corner Lena",
        name="Corner Segment Store",
    )
    fx.set_clock(api, fx.at(11, 0, 0))
    loop = fx.open_loop(api, ctx)
    fx.set_clock(api, fx.at(11, 0, 20))
    fx.greet_loop(api, ctx, loop["id"])
    fx.set_clock(api, fx.at(11, 1, 0))
    fx.complete_order(api, ctx, loop["id"], order_items_count=4)
    fx.set_clock(api, fx.at(11, 2, 0))
    at_window = fx.arrive_at_window(api, ctx, loop["id"])
    fx.set_clock(api, fx.at(11, 4, 10))
    return ctx, loop, at_window


class TestLoopSegmentDurations:
    """Each segment is the difference of its own two stamps."""

    def test_every_segment_comes_out_of_its_own_pair_of_stamps(
        self, api: DriveThruApiClient
    ):
        """PRD §3.3: "Either way, window arrival stamps `window_arrive_at` and
        computes `pull_forward_seconds` as `window_arrive_at` minus
        `order_complete_at` — note that this segment deliberately *includes* any merge
        wait, so `merge_wait_seconds` is a component of `pull_forward_seconds` rather
        than a separate charge."
        And: "It stamps `depart_at`, computes `window_seconds` as `depart_at` minus
        `window_arrive_at`, computes `total_seconds` as `depart_at` minus `arrive_at`,
        and computes `adjusted_total_seconds`."

        Design: Corner/calculations/calc_loop_segment_durations_correct_result
        """
        ctx, loop, _at_window = _car_at_the_window(api)

        a.assert_pinned_targets(loop, 25, 95, 40, 75, total=235)

        departed = fx.depart_loop(api, ctx, loop["id"])

        # 20 / 40 / 60 / 130 out of the four stamped intervals, 250 end to end.
        a.assert_loop_segments(
            departed,
            greet_seconds=20,
            order_seconds=40,
            pull_forward_seconds=60,
            window_seconds=130,
            total_seconds=250,
            adjusted_total_seconds=250,
            merge_wait_seconds=None,
        )
        # 60 is window_arrive_at minus order_complete_at, not minus greet_at.
        assert departed["pull_forward_seconds"] != 100, departed

    def test_the_breach_flags_accumulate_as_each_stamp_lands(
        self, api: DriveThruApiClient
    ):
        """PRD §3.3: "`breach_flags` is the subset of `[GREET, ORDER, PULL_FORWARD,
        WINDOW]` — always reported in exactly that order — whose measured seconds are
        *strictly greater* than the corresponding pinned target: `GREET` when
        `greet_seconds` exceeds `greet_target_pinned`, `ORDER` when `order_seconds`
        exceeds `order_target_pinned`, `PULL_FORWARD` when `pull_forward_seconds`
        exceeds `pull_forward_target_pinned`, `WINDOW` when `window_seconds` exceeds
        `window_target_pinned`."

        Design: Corner/calculations/calc_loop_segment_durations_correct_result
        """
        ctx, loop, at_window = _car_at_the_window(api)

        # 60 seconds against a 40-second pinned target is the first breach.
        a.assert_breach_flags(at_window, ["PULL_FORWARD"])

        departed = fx.depart_loop(api, ctx, loop["id"])
        a.assert_breach_flags(departed, ["PULL_FORWARD", "WINDOW"])
        # 20 <= 25 and 40 <= 95, so neither early segment is flagged.
        assert "GREET" not in departed["breach_flags"], departed
        assert "ORDER" not in departed["breach_flags"], departed


# --------------------------------------------------- the ALTERNATE merge bias
def _dual_pad_with_three_ordered_cars(api: DriveThruApiClient):
    """Two LANE_A cars and one LANE_B car, all waiting to merge."""
    fx.setup_single_unbounded_band(api)
    ctx = fx.setup_store(
        api,
        "C-2398-25",
        lane_config="DUAL_PARALLEL",
        merge_slots_capacity=3,
        staff_name="Corner Otto",
        name="Corner Alternate Bias Store",
    )
    fx.set_clock(api, fx.at(11, 0, 0))
    first = fx.open_loop(api, ctx, lane="LANE_A")
    fx.set_clock(api, fx.at(11, 0, 5))
    third = fx.open_loop(api, ctx, lane="LANE_A")
    fx.set_clock(api, fx.at(11, 0, 10))
    second = fx.open_loop(api, ctx, lane="LANE_B")
    for loop_id, greet_at in (
        (first["id"], fx.at(11, 0, 20)),
        (third["id"], fx.at(11, 0, 25)),
        (second["id"], fx.at(11, 0, 30)),
    ):
        fx.set_clock(api, greet_at)
        fx.greet_loop(api, ctx, loop_id)
    for loop_id, order_at in (
        (first["id"], fx.at(11, 1, 0)),
        (third["id"], fx.at(11, 2, 0)),
        (second["id"], fx.at(11, 3, 0)),
    ):
        fx.set_clock(api, order_at)
        fx.complete_order(api, ctx, loop_id, order_items_count=3)
    return ctx, first, second, third


class TestAlternateMergeBias:
    """Lane fairness outranks how long a car has been waiting."""

    def test_the_first_award_has_no_lane_preference_and_takes_the_earliest_order(
        self, api: DriveThruApiClient
    ):
        """PRD §3.4: "Under `ALTERNATE`, the selector honours lane fairness: it looks
        up the store's merge slot with the greatest `sequence_index` regardless of
        that slot's `slot_state` (null if the store has none yet), and derives a
        preferred lane from it — `LANE_B` if that last slot's `source_lane` was
        `LANE_A`, `LANE_A` if it was `LANE_B`, and no preference at all if there is no
        last slot or its `source_lane` was `SINGLE`."

        Design: Corner/calculations/calc_merge_award_alternate_bias_prefers_opposite_lane
        """
        ctx, first, _second, _third = _dual_pad_with_three_ordered_cars(api)

        a.assert_merge_capacity(fx.get_restaurant(api, ctx.restaurant_id), free=3)

        slot = fx.award_merge_slot(api, ctx)
        assert slot["timer_loop_id"] == first["id"], slot
        assert slot["source_lane"] == "LANE_A", slot
        assert slot["sequence_index"] == 1, slot
        assert slot["award_reason"] == "ALTERNATE", slot

        winner = validate_success(api.get_timer_loop(first["id"], ADMIN_HEADERS))
        assert winner["served_after_loop_id"] is None, winner

    def test_the_second_award_crosses_to_the_other_lane_and_skips_a_longer_wait(
        self, api: DriveThruApiClient
    ):
        """PRD §3.4: "Candidates in the preferred lane rank ahead of candidates that
        are not, and within each of those two groups the earliest `order_complete_at`
        ranks first; when there is no preferred lane, all candidates rank purely by
        earliest `order_complete_at`."
        And: "At the same moment the winning loop's `served_after_loop_id` is set to
        the `timer_loop_id` of whichever slot held the greatest `sequence_index`
        *before* this award, or null if this is the store's first award — that
        self-reference is the re-sequencing audit trail showing which car this one
        merged behind."

        Design: Corner/calculations/calc_merge_award_alternate_bias_prefers_opposite_lane
        """
        ctx, first, second, third = _dual_pad_with_three_ordered_cars(api)

        slot1 = fx.award_merge_slot(api, ctx)
        slot2 = fx.award_merge_slot(api, ctx)

        assert slot2["timer_loop_id"] == second["id"], slot2
        assert slot2["source_lane"] == "LANE_B", slot2
        assert slot2["sequence_index"] == 2, slot2
        assert slot2["award_reason"] == "ALTERNATE", slot2
        # The other LANE_A car ordered a minute earlier and still ranks behind.
        assert slot2["timer_loop_id"] != third["id"], slot2

        winner = validate_success(api.get_timer_loop(second["id"], ADMIN_HEADERS))
        assert winner["served_after_loop_id"] == first["id"], winner

        assert slot1["slot_state"] == "RESERVED", slot1
        assert slot2["slot_state"] == "RESERVED", slot2
        a.assert_merge_capacity(fx.get_restaurant(api, ctx.restaurant_id), free=1)


class TestIncidentConstantTables:
    """Severity, penalty and cost are read off the declared tables."""

    def test_an_allergen_defect_takes_the_critical_row_of_both_tables(
        self, api: DriveThruApiClient
    ):
        """PRD §3.6: "An `ALLERGEN` defect is `CRITICAL`; a `WRONG_ITEM` or
        `MISSING_ITEM` defect is `MAJOR`; a `WRONG_SIZE` defect is `MINOR`."
        And: "`settlement_state` starts at `ACCRUED`, and because the store's accrued
        figure counts both `ACCRUED` and `CHARGED` incidents, the food cost enters
        `remake_cost_accrued_cents` the moment the defect is logged rather than when
        it is settled."

        Design: Corner/calculations/calc_incident_severity_and_cost_allergen_constants
        """
        fx.setup_single_unbounded_band(api)
        ctx = fx.setup_store(
            api,
            "C-2398-26",
            staff_name="Corner Sofia",
            name="Corner Allergen Store",
        )
        loop = fx.drive_loop(
            api,
            ctx,
            arrive_at=fx.at(11, 0, 0),
            greet_at=fx.at(11, 0, 20),
            order_complete_at=fx.at(11, 1, 0),
            window_arrive_at=None,
        )

        incident = fx.log_incident(api, ctx, loop["id"], incident_type="ALLERGEN")

        assert incident["severity"] == "CRITICAL", incident
        assert incident["penalty_seconds"] == 90, incident
        assert incident["remake_cost_cents"] == 1200, incident
        assert incident["settlement_state"] == "ACCRUED", incident
        assert incident["incident_state"] == "LOGGED", incident
        assert incident["restaurant_id"] == ctx.restaurant_id, incident

        held = validate_success(api.get_timer_loop(loop["id"], ADMIN_HEADERS))
        a.assert_loop_states(held, accuracy_state="REMAKE_OPEN")

        store = fx.get_restaurant(api, ctx.restaurant_id)
        a.assert_rollup(
            store,
            open_remake_count=1,
            remake_cost_accrued_cents=1200,
            required_oot_count=1,
            service_posture="SURGE",
        )
        # One open remake is below the two the accuracy hold needs.
        assert store["service_posture"] != "ACCURACY_HOLD", store


class TestOotRequirementCap:
    """The requirement is a sum with a hard ceiling."""

    def test_the_accuracy_bump_cannot_push_the_requirement_past_four(
        self, api: DriveThruApiClient
    ):
        """PRD §3.2: "`required_oot_count` is the sum of the band's minimum and the
        two bumps, capped at 4 — no store ever demands a fifth outside order-taker."
        And: "A **lane bump** of 1 applies when the store's `lane_config` is
        `DUAL_PARALLEL` *and* `cars_per_hour_effective` is at least 12 cars per hour;
        otherwise the lane bump is 0."

        Design: Corner/calculations/calc_oot_requirement_capped_at_max_four
        """
        fx.create_tier_band(
            api,
            {
                "tier": "TIER_1",
                "cars_per_hour_floor": 0,
                "target_relief_pct": 0.00,
                "min_oot_count": 4,
                "merge_award_bias": "ALTERNATE",
            },
        )
        ctx = fx.setup_store(
            api,
            "C-2398-27",
            lane_config="DUAL_PARALLEL",
            staff_name="Corner Halim",
            name="Corner Cap Store",
        )
        before = fx.get_restaurant(api, ctx.restaurant_id)
        # PRD §3.1: registration does NOT run the recompute chain, so
        # required_oot_count starts at 0 regardless of the band's min_oot_count.
        a.assert_rollup(before, required_oot_count=0, cars_per_hour_effective=0.0)

        loop = fx.drive_loop(
            api,
            ctx,
            lane="LANE_A",
            arrive_at=fx.at(11, 0, 0),
            greet_at=fx.at(11, 0, 20),
            order_complete_at=fx.at(11, 1, 0),
            window_arrive_at=None,
        )
        incident = fx.log_incident(api, ctx, loop["id"], incident_type="WRONG_ITEM")
        assert incident["severity"] == "MAJOR", incident
        assert incident["penalty_seconds"] == 45, incident
        assert incident["remake_cost_cents"] == 750, incident

        store = fx.get_restaurant(api, ctx.restaurant_id)
        # 4 + accuracy bump 1 + lane bump 0, clamped back to 4.
        a.assert_rollup(
            store,
            open_remake_count=1,
            required_oot_count=4,
            deployed_oot_count=0,
            cars_per_hour_effective=0.0,
            service_posture="SURGE",
        )


# --------------------------------------- three cars, three different precisions
def _three_cars_closed_across_three_tiers(api: DriveThruApiClient):
    """Each departure lifts the car rate, so each next car pins a higher target."""
    fx.setup_four_tier_bands(api)
    ctx = fx.setup_store(
        api,
        "C-2398-28",
        staff_name="Corner Yara",
        name="Corner Precision Store",
    )
    first = fx.drive_loop(
        api,
        ctx,
        arrive_at=fx.at(11, 0, 0),
        greet_at=fx.at(11, 0, 20),
        order_complete_at=fx.at(11, 1, 0),
        window_arrive_at=fx.at(11, 2, 0),
        depart_at=fx.at(11, 4, 10),
        order_items_count=3,
    )
    second = fx.drive_loop(
        api,
        ctx,
        arrive_at=fx.at(11, 4, 20),
        greet_at=fx.at(11, 4, 40),
        order_complete_at=fx.at(11, 5, 20),
        window_arrive_at=fx.at(11, 6, 20),
        depart_at=fx.at(11, 8, 25),
        order_items_count=3,
    )
    third = fx.drive_loop(
        api,
        ctx,
        arrive_at=fx.at(11, 8, 35),
        greet_at=fx.at(11, 8, 55),
        order_complete_at=fx.at(11, 9, 35),
        window_arrive_at=fx.at(11, 10, 35),
        depart_at=fx.at(11, 12, 37),
        order_items_count=3,
    )
    fx.set_clock(api, fx.at(11, 15, 0))
    return ctx, first, second, third


class TestReportPrecisionRules:
    """One response, three different rounding rules."""

    def test_each_successive_car_pins_the_target_of_its_own_tier(
        self, api: DriveThruApiClient
    ):
        """PRD §3.3: "Each of the four profile targets is multiplied by one plus the
        combined relief and rounded half up to a whole second *individually*,
        producing `greet_target_pinned`, `order_target_pinned`,
        `pull_forward_target_pinned` and `window_target_pinned`."

        Design: Corner/calculations/calc_report_avg_metric_seconds_precision_one_decimal
        """
        _ctx, first, second, third = _three_cars_closed_across_three_tiers(api)

        # Relief 0.00, then 0.03 with one car in the trailing window, then 0.07.
        a.assert_pinned_targets(first, 25, 95, 40, 75, total=235)
        a.assert_pinned_targets(second, 26, 98, 41, 77, total=242)
        a.assert_pinned_targets(third, 27, 102, 43, 80, total=252)

        a.assert_loop_segments(first, total_seconds=250)
        a.assert_loop_segments(second, total_seconds=245)
        a.assert_loop_segments(third, total_seconds=242)

    def test_the_average_the_mean_and_the_attainment_each_keep_their_own_precision(
        self, api: DriveThruApiClient
    ):
        """PRD §3.8: "`avg_metric_seconds` is the sum of the variant's metric across
        the input set divided by `cars_served`, rounded half up to one decimal place.
        `mean_pinned_target_seconds` is the sum of `target_total_seconds_pinned`
        across the same input set divided by `cars_served`, held **exactly and
        unrounded** — it is an intermediate, and rounding it here would corrupt the
        attainment figure."
        And: "`attainment_pct` is 100 multiplied by `target_total_seconds_effective`
        and divided by `avg_metric_seconds`, rounded half up to two decimal places."

        Design: Corner/calculations/calc_report_avg_metric_seconds_precision_one_decimal
        """
        ctx, _first, _second, _third = _three_cars_closed_across_three_tiers(api)

        report = fx.create_report(api, ctx, fx.at(11, 0, 0), fx.at(11, 15, 0))

        # 737 / 3 is 245.666..., 729 / 3 is exactly 243, and 243 * 1.07 is 260.01.
        a.assert_report_metrics(
            report,
            cars_served=3,
            cars_per_hour=12.0,
            window_tier="TIER_3",
            avg_metric_seconds=245.7,
            mean_pinned_target_seconds=243,
            target_total_seconds_effective=260,
            attainment_pct=105.82,
            attainment_band="GREEN",
            coaching_pool_points=6,
        )


# ------------------------------- the open-remake count and the variant input set
def _one_clean_car_and_one_with_an_open_remake(api: DriveThruApiClient):
    """Both cars departed inside the window; only one of them is countable."""
    fx.setup_four_tier_bands(api)
    ctx = fx.setup_store(
        api,
        "C-2398-29",
        staff_name="Corner Marek",
        name="Corner Remake Scope Store",
    )
    clean = fx.drive_loop(
        api,
        ctx,
        arrive_at=fx.at(11, 0, 0),
        greet_at=fx.at(11, 0, 20),
        order_complete_at=fx.at(11, 1, 0),
        window_arrive_at=fx.at(11, 2, 0),
        depart_at=fx.at(11, 4, 10),
        order_items_count=3,
    )
    defective = fx.drive_loop(
        api,
        ctx,
        arrive_at=fx.at(11, 5, 0),
        greet_at=fx.at(11, 5, 20),
        order_complete_at=fx.at(11, 6, 0),
        window_arrive_at=None,
    )
    incident = fx.log_incident(api, ctx, defective["id"], incident_type="WRONG_ITEM")
    fx.set_clock(api, fx.at(11, 7, 0))
    fx.arrive_at_window(api, ctx, defective["id"])
    fx.set_clock(api, fx.at(11, 9, 5))
    departed = fx.depart_loop(api, ctx, defective["id"])
    fx.set_clock(api, fx.at(11, 10, 0))
    return ctx, clean, departed, incident


class TestReportOpenRemakeScope:
    """The incident count is scoped by arrival, not by the variant's input set."""

    def test_the_excluded_car_still_costs_the_window_its_coaching_points(
        self, api: DriveThruApiClient
    ):
        """PRD §3.8: "A **`PROVISIONAL`** report's input set is the store's timer loops
        whose `timing_state` is `CLOSED` and whose **`depart_at`** falls at or after
        `window_start_at` and strictly before `window_end_at`, *excluding* any loop
        whose `accuracy_state` is `REMAKE_OPEN`."
        And: "`open_remake_incident_count` is computed independently of the variant's
        input set: it counts the accuracy incidents whose `incident_state` is `LOGGED`
        or `REMADE` and whose loop's `arrive_at` falls at or after `window_start_at`
        and strictly before `window_end_at`."

        Design: Corner/calculations/calc_report_open_remake_count_independent_of_variant_input_set
        """
        ctx, clean, departed, incident = _one_clean_car_and_one_with_an_open_remake(api)

        a.assert_pinned_targets(clean, 25, 95, 40, 75, total=235)
        a.assert_pinned_targets(departed, 26, 98, 41, 77, total=242)
        a.assert_loop_segments(clean, total_seconds=250)
        a.assert_loop_segments(departed, total_seconds=245, adjusted_total_seconds=290)
        assert incident["penalty_seconds"] == 45, incident
        a.assert_loop_states(clean, accuracy_state="VERIFIED")
        a.assert_loop_states(departed, accuracy_state="REMAKE_OPEN")

        report = fx.create_report(api, ctx, fx.at(11, 0, 0), fx.at(11, 10, 0))

        a.assert_report_metrics(
            report,
            metric_basis="TOTAL",
            cars_served=1,
            avg_metric_seconds=250.0,
            mean_pinned_target_seconds=235,
            open_remake_incident_count=1,
            coaching_pool_points=1,
        )

    def test_the_window_tier_comes_from_the_window_rate_not_the_store_rate(
        self, api: DriveThruApiClient
    ):
        """PRD §3.8: "`window_tier` is the `tier` of the band whose
        `cars_per_hour_floor` is at or below `cars_per_hour` and whose
        `cars_per_hour_ceiling` is null or strictly above it. This is **this window's**
        tier, derived from the window's own rate — it is emphatically **not** the
        store's `volume_tier`, which reflects the trailing ten minutes at request time
        and is frequently a different band."

        Design: Corner/calculations/calc_report_open_remake_count_independent_of_variant_input_set
        """
        ctx, _clean, _departed, _incident = _one_clean_car_and_one_with_an_open_remake(
            api
        )

        store = fx.get_restaurant(api, ctx.restaurant_id)
        # Two cars physically closed in the trailing ten minutes.
        a.assert_rollup(store, cars_closed_trailing=2, volume_tier="TIER_3")

        report = fx.create_report(api, ctx, fx.at(11, 0, 0), fx.at(11, 10, 0))

        # One countable car in a 600-second window is 6.0 cars per hour.
        a.assert_report_metrics(
            report,
            cars_per_hour=6.0,
            window_tier="TIER_2",
            target_total_seconds_effective=242,
            attainment_pct=96.80,
            attainment_band="AMBER",
        )
        assert report["window_tier"] != store["volume_tier"], report


# ---------------------------------- which applied override is the one in force
def _store_with_two_applied_overrides_and_one_merely_approved(
    api: DriveThruApiClient,
):
    """Three overrides over the same hour: 0.20 applied, 0.40 approved, 0.20 applied."""
    fx.setup_single_unbounded_band(api)
    ctx = fx.setup_store(
        api,
        "C-2398-30",
        staffing_basis="OBSERVED",
        staff_name="Corner Devi",
        name="Corner Override Selection Store",
    )
    fx.set_clock(api, fx.at(11, 0, 0))
    first = fx.applied_override(
        api,
        ctx,
        fx.at(11, 0, 0),
        fx.at(12, 0, 0),
        projected_cars_delta_pct=0.20,
        source="WEATHER",
    )
    fx.set_clock(api, fx.at(11, 0, 5))
    proposed = fx.propose_override(
        api,
        ctx,
        fx.at(11, 0, 0),
        fx.at(12, 0, 0),
        projected_cars_delta_pct=0.40,
        source="LOCAL_EVENT",
    )
    second = fx.approve_override(api, proposed["id"])
    fx.set_clock(api, fx.at(11, 0, 10))
    third = fx.applied_override(
        api,
        ctx,
        fx.at(11, 0, 0),
        fx.at(12, 0, 0),
        projected_cars_delta_pct=0.20,
        source="SYSTEM_OUTAGE",
        target_relief_pct_override=0.05,
    )
    fx.set_clock(api, fx.at(11, 0, 15))
    return ctx, first, second, third


class TestOverrideInForceSelection:
    """State filters the candidates; the ranking picks exactly one."""

    def test_the_earlier_of_two_tied_applied_overrides_sets_the_relief(
        self, api: DriveThruApiClient
    ):
        """PRD §3.7: "When more than one applied override covers the instant in
        question, exactly one is selected as the one in force: candidates are the
        store's applied overrides whose closed interval contains that instant, both
        ends inclusive; they are ranked by `projected_cars_delta_pct` descending, and
        ties are broken by the earlier `created_at` — never by `id`."
        PRD §3.3: "The **override relief** is 0.00 when no forecast override is in
        force at the current clock reading; otherwise, when the in-force override
        supplies an explicit `target_relief_pct_override`, that value is used
        verbatim; otherwise it is that override's `projected_cars_delta_pct`
        multiplied by one half, floored at 0.00 and then capped at 0.20 — so a
        negative forecast delta contributes no relief and a very large positive one
        contributes at most a fifth."

        Design: Corner/calculations/calc_active_override_selection_filters_state_then_ranks
        """
        ctx, first, second, third = (
            _store_with_two_applied_overrides_and_one_merely_approved(api)
        )
        assert first["fo_state"] == "APPLIED", first
        assert second["fo_state"] == "APPROVED", second
        assert third["fo_state"] == "APPLIED", third

        loop = fx.open_loop(api, ctx)

        # Relief 0.10 from the winner's 0.20 delta halved.
        a.assert_pinned_targets(loop, 28, 105, 44, 83, total=260)
        # 282 would be the merely-approved 0.40 override, 247 the tie-break loser.
        assert loop["target_total_seconds_pinned"] != 282, loop
        assert loop["target_total_seconds_pinned"] != 247, loop

    def test_the_observed_basis_leaves_the_car_rate_alone(
        self, api: DriveThruApiClient
    ):
        """PRD §3.7: "`projected_cars_delta_pct` is a signed fraction between -0.50 and
        1.00 inclusive, describing how much the car rate is expected to move; it is
        applied to `cars_per_hour_observed` only when the store's `staffing_basis` is
        `FORECAST_ADJUSTED`."

        Design: Corner/calculations/calc_active_override_selection_filters_state_then_ranks
        """
        ctx, _first, _second, _third = (
            _store_with_two_applied_overrides_and_one_merely_approved(api)
        )

        store = fx.get_restaurant(api, ctx.restaurant_id)
        assert store["staffing_basis"] == "OBSERVED", store
        a.assert_rollup(
            store,
            cars_per_hour_observed=0.0,
            cars_per_hour_effective=0.0,
            volume_tier="TIER_1",
        )


class TestReportMetricBasis:
    """The variant field alone selects the metric."""

    def test_the_two_variants_record_two_different_metric_bases(
        self, api: DriveThruApiClient
    ):
        """PRD §3.8: "`variant` selects both the input set and the metric, and
        `metric_basis` records the choice: it is `TOTAL` for a `PROVISIONAL` report and
        `ADJUSTED_TOTAL` for a `FINAL` one."

        Design: Corner/calculations/calc_report_metric_basis_selected_by_variant_field
        """
        fx.setup_four_tier_bands(api)
        ctx = fx.setup_store(
            api,
            "C-2398-31",
            staff_name="Corner Ilse",
            name="Corner Metric Basis Store",
        )
        loop = fx.drive_loop(
            api,
            ctx,
            arrive_at=fx.at(11, 0, 0),
            greet_at=fx.at(11, 0, 20),
            order_complete_at=fx.at(11, 1, 0),
            window_arrive_at=fx.at(11, 2, 0),
            depart_at=fx.at(11, 4, 10),
            order_items_count=3,
        )
        a.assert_loop_segments(loop, total_seconds=250, adjusted_total_seconds=250)
        fx.set_clock(api, fx.at(11, 5, 0))

        provisional = fx.create_report(
            api, ctx, fx.at(11, 0, 0), fx.at(11, 5, 0), variant="PROVISIONAL"
        )
        final = fx.create_report(
            api, ctx, fx.at(11, 0, 0), fx.at(11, 5, 0), variant="FINAL"
        )

        assert provisional["metric_basis"] == "TOTAL", provisional
        assert final["metric_basis"] == "ADJUSTED_TOTAL", final
        for report in (provisional, final):
            # The one penalty-free car qualifies under both anchors.
            a.assert_report_metrics(
                report,
                cars_served=1,
                window_tier="TIER_3",
                avg_metric_seconds=250.0,
                mean_pinned_target_seconds=235,
                target_total_seconds_effective=251,
                attainment_pct=100.40,
                attainment_band="GREEN",
                coaching_pool_points=6,
            )


# ------------------------- the final report reconciles a settled penalty
def _closed_car_with_a_settled_penalty(api: DriveThruApiClient):
    """A car whose remake was delivered and charged before it left the window."""
    fx.setup_four_tier_bands(api)
    ctx = fx.setup_store(
        api,
        "C-2398-32",
        staff_name="Corner Anton",
        name="Corner Reconciliation Store",
    )
    remaker = fx.add_staff_member(
        api,
        ctx.restaurant_id,
        "Corner Bea",
        oot_certified=False,
        window_certified=True,
    )
    loop = fx.drive_loop(
        api,
        ctx,
        arrive_at=fx.at(11, 0, 0),
        greet_at=fx.at(11, 0, 20),
        order_complete_at=fx.at(11, 1, 0),
        window_arrive_at=None,
        order_items_count=4,
    )
    incident = fx.log_incident(api, ctx, loop["id"], incident_type="WRONG_ITEM")
    fx.deliver_remake(api, ctx, incident["id"], remaker["id"])
    settled = fx.close_incident(api, incident["id"])
    fx.set_clock(api, fx.at(11, 2, 0))
    fx.arrive_at_window(api, ctx, loop["id"])
    fx.set_clock(api, fx.at(11, 4, 10))
    departed = fx.depart_loop(api, ctx, loop["id"])
    fx.set_clock(api, fx.at(11, 5, 0))
    provisional = fx.create_published_report(
        api, ctx, fx.at(11, 0, 0), fx.at(11, 5, 0), variant="PROVISIONAL"
    )
    final = fx.create_report(
        api,
        ctx,
        fx.at(11, 0, 0),
        fx.at(11, 5, 0),
        variant="FINAL",
        supersedes_report_id=provisional["id"],
    )
    return ctx, departed, settled, provisional, final


class TestFinalReportReconciliation:
    """The same window, rescored against the penalty the guest actually felt."""

    def test_the_final_metric_folds_in_the_charged_penalty(
        self, api: DriveThruApiClient
    ):
        """PRD §3.8: "A **`FINAL`** report's input set is the store's timer loops whose
        `timing_state` is `CLOSED` or `ABANDONED` and whose **`arrive_at`** — arrival,
        not departure — falls at or after `window_start_at` and strictly before
        `window_end_at`, *including* loops whose `accuracy_state` is `REMAKE_OPEN`."
        PRD §3.6: "The loop's `accuracy_state` returns to `VERIFIED`, but the
        incident's `penalty_seconds` **stay inside** `adjusted_total_seconds`, because
        the defect really did happen and really did cost the guest time."

        Design: Corner/calculations/calc_final_report_reconciles_penalty_delta_against_published_provisional
        """
        _ctx, departed, settled, provisional, final = _closed_car_with_a_settled_penalty(
            api
        )

        assert settled["incident_state"] == "CLOSED", settled
        assert settled["settlement_state"] == "CHARGED", settled
        assert settled["penalty_seconds"] == 45, settled
        a.assert_loop_segments(departed, total_seconds=250, adjusted_total_seconds=295)
        a.assert_loop_states(departed, accuracy_state="VERIFIED")

        a.assert_report_metrics(
            provisional,
            avg_metric_seconds=250.0,
            attainment_pct=100.40,
            attainment_band="GREEN",
            open_remake_incident_count=0,
            coaching_pool_points=6,
        )
        # 250 plus the 45 penalty seconds, scored against the same 251 target.
        a.assert_report_metrics(
            final,
            avg_metric_seconds=295.0,
            window_tier="TIER_3",
            mean_pinned_target_seconds=235,
            target_total_seconds_effective=251,
            attainment_pct=85.08,
            attainment_band="RED",
            open_remake_incident_count=0,
            coaching_pool_points=0,
        )

    def test_publishing_the_final_report_retires_the_provisional_one(
        self, api: DriveThruApiClient
    ):
        """PRD §3.6: "The store's `remake_cost_accrued_cents` is unchanged by closing —
        moving from `ACCRUED` to `CHARGED` keeps the money in the ledger, since the
        accrued figure sums both states."
        PRD §3.8: "Publishing moves the report `DRAFT → PUBLISHED` and requires the
        report to be in `DRAFT`, `cars_served` to be at least 1, and the store not to
        be frozen."

        Design: Corner/calculations/calc_final_report_reconciles_penalty_delta_against_published_provisional
        """
        ctx, _departed, _settled, provisional, final = (
            _closed_car_with_a_settled_penalty(api)
        )

        published = fx.publish_report(api, final["id"])
        assert published["report_state"] == "PUBLISHED", published

        predecessor = validate_success(
            api.get_throughput_report(provisional["id"], ADMIN_HEADERS)
        )
        assert predecessor["report_state"] == "SUPERSEDED", predecessor

        store = fx.get_restaurant(api, ctx.restaurant_id)
        a.assert_rollup(
            store, open_remake_count=0, remake_cost_accrued_cents=750
        )
