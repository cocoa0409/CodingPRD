"""Multi-step formulas whose rounding points and evaluation order are pinned.

Three chains are exercised: per-segment target pinning, the report chain that
derives a window's own tier, and the coaching priority score.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions as a
from test_helpers import fixtures as fx
from test_helpers.api_client import DriveThruApiClient
from test_helpers.test_users import ADMIN_HEADERS, COACH_HEADERS


# --------------------------------------------------- per-segment target pinning
def _store_with_an_explicit_relief_override(api: DriveThruApiClient):
    """A quiet store carrying an applied override that names its relief outright."""
    fx.setup_four_tier_bands(api)
    ctx = fx.setup_store(
        api,
        "S-2398-C",
        staff_name="Omar Diaz",
        name="Cascade Single Lane",
    )
    fx.set_clock(api, fx.at(11, 0, 0))
    override = fx.applied_override(
        api,
        ctx,
        fx.at(11, 0, 0),
        fx.at(13, 0, 0),
        projected_cars_delta_pct=0.00,
        source="LOCAL_EVENT",
        target_relief_pct_override=0.09,
    )
    return ctx, override


class TestLoopTargetPinning:
    """Relief is applied to each segment target on its own, then summed."""

    def test_each_segment_target_is_rounded_before_the_total_is_summed(self, api):
        """PRD §3.3: "Each of the four profile targets is multiplied by one plus
        the combined relief and rounded half up to a whole second
        *individually*, producing `greet_target_pinned`, `order_target_pinned`,
        `pull_forward_target_pinned` and `window_target_pinned`. Only then are
        those four already-rounded whole-second values summed to give
        `target_total_seconds_pinned`."

        Design: Difficulty/combinatorial_formula/loop_target_pinning_per_segment_rounding_order
        """
        ctx, _override = _store_with_an_explicit_relief_override(api)

        loop = validate_success(
            api.create_timer_loop(
                {
                    "restaurant_id": ctx.restaurant_id,
                    "daypart_profile_id": ctx.profile_id,
                    "lane": "SINGLE",
                },
                ctx.leader_headers,
            ),
            expected_status=201,
        )
        # 25 -> 27.25, 95 -> 103.55, 40 -> 43.60, 75 -> 81.75, each rounded alone.
        a.assert_pinned_targets(loop, 27, 104, 44, 82, total=257)

    def test_sum_then_round_once_is_not_the_pinned_total(self, api):
        """PRD §3.3: "Summing the relieved targets first and rounding once at
        the end yields a different number and is wrong."

        Design: Difficulty/combinatorial_formula/loop_target_pinning_per_segment_rounding_order
        """
        ctx, _override = _store_with_an_explicit_relief_override(api)

        loop = validate_success(
            api.create_timer_loop(
                {
                    "restaurant_id": ctx.restaurant_id,
                    "daypart_profile_id": ctx.profile_id,
                    "lane": "SINGLE",
                },
                ctx.leader_headers,
            ),
            expected_status=201,
        )
        assert loop["target_total_seconds_pinned"] == 257, loop
        # 235 relieved by 0.09 and rounded once would be 256.
        assert loop["target_total_seconds_pinned"] != 256, loop

    def test_explicit_relief_override_is_used_verbatim_over_a_quiet_store(self, api):
        """PRD §3.3: "otherwise, when the in-force override supplies an explicit
        `target_relief_pct_override`, that value is used verbatim"

        Design: Difficulty/combinatorial_formula/loop_target_pinning_per_segment_rounding_order
        """
        ctx, override = _store_with_an_explicit_relief_override(api)

        assert override["fo_state"] == "APPLIED", override
        store = fx.get_restaurant(api, ctx.restaurant_id)
        # TIER_1 grants no relief of its own, so the 0.09 stands alone.
        a.assert_rollup(store, cars_per_hour_effective=0.0, volume_tier="TIER_1")

        loop = validate_success(
            api.create_timer_loop(
                {
                    "restaurant_id": ctx.restaurant_id,
                    "daypart_profile_id": ctx.profile_id,
                    "lane": "SINGLE",
                },
                ctx.leader_headers,
            ),
            expected_status=201,
        )
        a.assert_pinned_targets(loop, 27, 104, 44, 82, total=257)
        a.assert_loop_states(loop, timing_state="OPEN", accuracy_state="PENDING")
        assert loop["car_sequence"] == 1, loop

        profile = validate_success(api.get_daypart_profile(ctx.profile_id, ADMIN_HEADERS))
        assert profile["total_target_seconds"] == 235, profile


# ------------------------------------------------------- report window-tier chain
def _store_whose_trailing_window_has_aged_out(api: DriveThruApiClient):
    """One car served, then ten more minutes of quiet so the store falls to TIER_1."""
    fx.setup_four_tier_bands(api)
    ctx = fx.setup_store(
        api,
        "S-2398-D",
        staff_name="Rita Boone",
        name="Northside Single Lane",
    )
    loop = fx.drive_loop(
        api,
        ctx,
        arrive_at=fx.at(11, 0, 0),
        greet_at=fx.at(11, 0, 20),
        order_complete_at=fx.at(11, 1, 0),
        window_arrive_at=fx.at(11, 2, 0),
        depart_at=fx.at(11, 3, 50),
        order_items_count=3,
    )
    fx.set_clock(api, fx.at(11, 14, 0))
    return ctx, loop["id"]


class TestReportWindowTierChain:
    """A report's tier comes from its own window, not from the store's rollup."""

    def test_window_tier_is_read_from_the_windows_own_car_rate(self, api):
        """PRD §3.8: "This is **this window's** tier, derived from the window's
        own rate — it is emphatically **not** the store's `volume_tier`, which
        reflects the trailing ten minutes at request time and is frequently a
        different band."

        Design: Difficulty/combinatorial_formula/coaching_pool_points_circular_window_tier_evaluation_order
        """
        ctx, _loop_id = _store_whose_trailing_window_has_aged_out(api)

        store = fx.get_restaurant(api, ctx.restaurant_id)
        a.assert_rollup(store, cars_closed_trailing=0, volume_tier="TIER_1")

        report = fx.create_report(api, ctx, fx.at(11, 3, 0), fx.at(11, 4, 0))
        a.assert_report_metrics(
            report, cars_served=1, cars_per_hour=60.0, window_tier="TIER_4"
        )
        assert report["window_tier"] != store["volume_tier"], report

    def test_effective_target_and_attainment_follow_the_window_tier_relief(self, api):
        """PRD §3.8: "`target_total_seconds_effective` is
        `mean_pinned_target_seconds` multiplied by one plus that relief, rounded
        half up to a whole second."

        Design: Difficulty/combinatorial_formula/coaching_pool_points_circular_window_tier_evaluation_order
        """
        ctx, _loop_id = _store_whose_trailing_window_has_aged_out(api)

        report = fx.create_report(api, ctx, fx.at(11, 3, 0), fx.at(11, 4, 0))
        a.assert_report_metrics(
            report,
            avg_metric_seconds=230.0,
            mean_pinned_target_seconds=235,
            target_total_seconds_effective=263,
            attainment_pct=114.35,
            attainment_band="GOLD",
        )
        # The answer the store's stale TIER_1 relief would have produced.
        assert report["attainment_pct"] != 102.17, report
        assert report["attainment_band"] != "GREEN", report

    def test_coaching_pool_points_award_the_gold_band(self, api):
        """PRD §3.8: "`coaching_pool_points` is the coaching budget the window
        earned: take the band award — 10 points for `GOLD`, 6 for `GREEN`, 3 for
        `AMBER`, 0 for `RED` — add a volume award equal to `cars_served` divided
        by 25 and rounded **down** to a whole number but capped at 6 points,
        then subtract 2 points for each incident counted in
        `open_remake_incident_count`."

        Design: Difficulty/combinatorial_formula/coaching_pool_points_circular_window_tier_evaluation_order
        """
        ctx, _loop_id = _store_whose_trailing_window_has_aged_out(api)

        report = fx.create_report(api, ctx, fx.at(11, 3, 0), fx.at(11, 4, 0))
        a.assert_report_metrics(
            report,
            attainment_band="GOLD",
            open_remake_incident_count=0,
            coaching_pool_points=10,
        )
        assert report["coaching_pool_points"] != 6, report


# --------------------------------------------------------- coaching priority score
def _published_amber_report_with_one_open_remake(api: DriveThruApiClient):
    """A slow-window car with a size defect, scored FINAL and published."""
    fx.setup_four_tier_bands(api)
    ctx = fx.setup_store(
        api,
        "S-2398-E",
        staff_name="Pia Nowak",
        name="Marietta Single Lane",
    )
    loop = fx.drive_loop(
        api,
        ctx,
        arrive_at=fx.at(11, 0, 0),
        greet_at=fx.at(11, 0, 20),
        order_complete_at=fx.at(11, 1, 15),
        window_arrive_at=fx.at(11, 2, 25),
        depart_at=fx.at(11, 4, 10),
        order_items_count=4,
    )
    fx.log_incident(api, ctx, loop["id"], incident_type="WRONG_SIZE")
    fx.set_clock(api, fx.at(11, 5, 0))
    report = fx.create_report(
        api, ctx, fx.at(11, 0, 0), fx.at(11, 5, 0), variant="FINAL"
    )
    fx.publish_report(api, report["id"])
    return ctx, loop["id"], report["id"]


class TestCoachingPriorityScore:
    """The score is three saturating components, added then capped."""

    def test_segment_gap_is_the_mean_measured_minus_the_mean_pinned_target(self, api):
        """PRD §3.9: "For the four timing segments it is the mean of the
        matching measured duration across the input set (`greet_seconds` for
        `GREET`, `order_seconds` for `ORDER`, `pull_forward_seconds` for
        `PULL_FORWARD`, `window_seconds` for `WINDOW`) minus the mean of the
        matching pinned target across the same input set
        (`greet_target_pinned`, `order_target_pinned`,
        `pull_forward_target_pinned` and `window_target_pinned` respectively),
        floored at 0 so a segment that beat its target contributes no gap."

        Design: Difficulty/combinatorial_formula/coaching_priority_score_nested_min_weighted_saturation
        """
        ctx, loop_id, report_id = _published_amber_report_with_one_open_remake(api)

        loop = validate_success(api.get_timer_loop(loop_id, COACH_HEADERS))
        a.assert_loop_segments(loop, window_seconds=105, adjusted_total_seconds=270)
        assert loop["window_target_pinned"] == 75, loop

        coaching = validate_success(
            api.create_coaching_intervention(
                {
                    "throughput_report_id": report_id,
                    "staff_member_id": ctx.staff_id,
                    "focus_segment": "WINDOW",
                },
                COACH_HEADERS,
            ),
            expected_status=201,
        )
        a.assert_coaching_scoring(coaching, segment_gap_seconds=30)

    def test_priority_score_sums_the_three_saturating_components(self, api):
        """PRD §3.9: "The gap component is worth up to 60 points and is 60
        multiplied by the smaller of 1.0 and `segment_gap_seconds` divided by 30
        seconds — a segment running half a minute or more behind target
        saturates it. The accuracy component is worth up to 25 points and is 25
        multiplied by the smaller of 1.0 and the report's
        `open_remake_incident_count` divided by 3 — three or more open remakes
        in the window saturate it. The band component is worth up to 15 points
        and is 15 multiplied by a band weight of 0.0 for `GOLD`, 0.2 for
        `GREEN`, 0.6 for `AMBER` and 1.0 for `RED`."

        Design: Difficulty/combinatorial_formula/coaching_priority_score_nested_min_weighted_saturation
        """
        ctx, _loop_id, report_id = _published_amber_report_with_one_open_remake(api)

        coaching = validate_success(
            api.create_coaching_intervention(
                {
                    "throughput_report_id": report_id,
                    "staff_member_id": ctx.staff_id,
                    "focus_segment": "WINDOW",
                },
                COACH_HEADERS,
            ),
            expected_status=201,
        )
        # 60.00 saturated + 25 * (1/3) + 15 * 0.6
        a.assert_coaching_scoring(
            coaching, priority_score=77.33, tier="TIER_C_RETRAIN"
        )
        assert coaching["ci_state"] == "DRAFT", coaching
        assert coaching["revision_count"] == 0, coaching
        assert coaching["restaurant_id"] == ctx.restaurant_id, coaching

    def test_the_report_figures_the_score_reads_are_the_amber_chain(self, api):
        """PRD §3.8: "`attainment_band` is `GOLD` when `attainment_pct` is at
        least 110, otherwise `GREEN` when it is at least 100, otherwise `AMBER`
        when it is at least 90, otherwise `RED`."

        Design: Difficulty/combinatorial_formula/coaching_priority_score_nested_min_weighted_saturation
        """
        _ctx, _loop_id, report_id = _published_amber_report_with_one_open_remake(api)

        report = validate_success(api.get_throughput_report(report_id, COACH_HEADERS))
        a.assert_report_metrics(
            report,
            window_tier="TIER_3",
            target_total_seconds_effective=251,
            attainment_pct=92.96,
            attainment_band="AMBER",
            open_remake_incident_count=1,
            coaching_pool_points=1,
        )
