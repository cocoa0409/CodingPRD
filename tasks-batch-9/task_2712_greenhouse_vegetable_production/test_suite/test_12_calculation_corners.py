"""Corner cases of three derived figures: hive vigour, pest pressure and the waterfall.

Each test drives one calculation to the exact point where a constant is read or a
band boundary is crossed: a hive exactly one week old, a mite count sitting exactly
on its action threshold, and a pound pool that runs out part-way down the
priority-ordered list of weekly commitments.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_money,
    cold_chain_event,
    create_commitment_week,
    create_harvest_worker,
    create_hive_placement,
    create_pollination_check,
    create_retail_program,
    create_scout_worker,
    create_scouting_observation_payload,
    grade_lot,
    make_ipm_scout_headers,
    read_crop_cycle,
    read_lot,
    read_week,
    read_zone,
    register_lot,
    set_clock,
    setup_production_cycle,
    setup_transplanted_cycle,
    validate_success,
)

GM = TEST_USERS["grower_manager_headers"]


def _cycle_with_one_week_old_hives():
    """A PRODUCTION cycle carrying four hives placed exactly one week and one hour ago."""
    state = setup_production_cycle(production_clock="2026-08-24T06:00:00Z")
    state["cycle"] = create_hive_placement(
        state["cycle"]["id"], hive_count=4, placed_at="2026-08-24T08:00:00Z"
    )
    set_clock("2026-08-31T09:00:00Z")
    return state


def _observe(zone_id, cycle_id, scout_worker_id, **overrides):
    """File one scouting round and return the immutable observation."""
    payload = create_scouting_observation_payload(zone_id, cycle_id, **overrides)
    return validate_success(
        api_client.create_scouting_observation(
            payload, make_ipm_scout_headers(scout_worker_id)
        ),
        201,
    )


def _two_programs_competing_for_one_lot():
    """Two A_ONLY weeks committing 1000 lbs each against a single 1200 lb A pool."""
    state = setup_production_cycle(production_clock="2026-08-31T06:00:00Z")
    worker = create_harvest_worker()
    program_one = create_retail_program(
        retailer_name="Northline Grocers",
        program_code="PR-1",
        grade_spec="A_ONLY",
        weekly_commitment_lbs=1000.00,
        price_per_lb_usd=1.85,
        shortfall_penalty_per_lb_usd=0.40,
        priority_rank=1,
    )
    program_two = create_retail_program(
        retailer_name="Southgate Markets",
        program_code="PR-2",
        grade_spec="A_ONLY",
        weekly_commitment_lbs=1000.00,
        price_per_lb_usd=1.70,
        shortfall_penalty_per_lb_usd=0.30,
        priority_rank=2,
    )
    week_one = create_commitment_week(
        program_one["id"], iso_week="2026-W36", week_start_date="2026-08-31"
    )
    week_two = create_commitment_week(
        program_two["id"], iso_week="2026-W36", week_start_date="2026-08-31"
    )
    lot = register_lot(
        state["cycle"]["id"],
        worker["id"],
        harvest_date="2026-08-31",
        gross_weight_lbs=2000.00,
    )
    grade_lot(
        lot["id"], worker["id"], grade_a_lbs=1200.00, grade_b_lbs=700.00, cull_lbs=100.00
    )
    cold_chain_event(lot["id"], "PRECOOLED", 10.0)
    cold_chain_event(lot["id"], "COLD_HELD", 6.0)
    return {
        "program_one": program_one,
        "program_two": program_two,
        "week_one": week_one,
        "week_two": week_two,
        "lot": lot,
    }


def _run_waterfall(week_start_date="2026-08-31"):
    """Run the allocation waterfall and return the weeks it evaluated, in run order."""
    return validate_success(
        api_client.create_allocation_run({"week_start_date": week_start_date}, GM), 200
    )


class TestPollinationScoring:
    """Hive vigour one whole week after placement, in the mid visitation band."""

    def test_one_week_old_hive_in_the_mid_visitation_band_scores_eighty(self, api):
        """PRD §3.7: "The same visitation and a healthy 55-bee count on a one-week-old hive gives an index of 80.00, a risk score of 20.00, and no haircut at all."

        Design: Corner/calculations/pollination_strength_decays_one_week_and_the_mid_band_penalty_applies
        """
        state = _cycle_with_one_week_old_hives()

        checked = create_pollination_check(
            state["cycle"]["id"],
            observed_at="2026-08-31T09:00:00Z",
            flower_visit_pct=78,
            hive_activity_count=60,
        )

        assert checked["pollination_strength_index"] == pytest.approx(80.00, abs=0.01), (
            f"88.00 base strength less the 8 point mid band penalty is 80.00, got "
            f"{checked['pollination_strength_index']}"
        )
        assert checked["pollination_risk_score"] == pytest.approx(20.00, abs=0.01), (
            f"expected pollination_risk_score 20.00, got "
            f"{checked['pollination_risk_score']}"
        )

    def test_risk_below_the_threshold_takes_no_yield_haircut(self, api):
        """PRD §3.7: "`pollination_haircut_pct` then follows a three-way decision: it is `0.00` whenever the cultivar's `requires_pollination` is false, regardless of how poor the bees look; otherwise it is 12 when `pollination_risk_score` is at or above the risk threshold of 30; otherwise it is `0.00`."

        Design: Corner/calculations/pollination_strength_decays_one_week_and_the_mid_band_penalty_applies
        """
        state = _cycle_with_one_week_old_hives()

        create_pollination_check(
            state["cycle"]["id"],
            observed_at="2026-08-31T09:00:00Z",
            flower_visit_pct=78,
            hive_activity_count=60,
        )

        cycle = read_crop_cycle(state["cycle"]["id"])
        assert cycle["pollination_haircut_pct"] == pytest.approx(0.00, abs=0.01), (
            f"a risk score of 20.00 is below the threshold of 30, so no haircut is "
            f"taken, got {cycle['pollination_haircut_pct']}"
        )
        assert cycle["expected_total_yield_lbs"] == pytest.approx(
            cycle["baseline_total_yield_lbs"], abs=0.01
        ), (
            f"with no haircut the expectation stays at the baseline "
            f"{cycle['baseline_total_yield_lbs']}, got "
            f"{cycle['expected_total_yield_lbs']}"
        )


class TestPestActionThresholds:
    """Each pest carries its own action threshold, so identical counts differ."""

    def test_threshold_is_read_from_the_pest_code_under_inspection(self, api):
        """PRD §3.6: "`action_threshold` is looked up from the pest: 0.500 for `WHITEFLY`, 1.000 for `THRIPS`, 0.250 for `SPIDER_MITE`, and 0.750 for `APHID`."

        Design: Corner/calculations/pest_action_thresholds_are_read_per_pest_code
        """
        state = setup_transplanted_cycle(clock="2026-08-06T00:00:00Z")
        scout = create_scout_worker()

        thrips = _observe(
            state["zone"]["id"],
            state["cycle"]["id"],
            scout["id"],
            pest_code="THRIPS",
            pest_count_per_plant=0.900,
            observed_at="2026-08-06T07:00:00Z",
        )
        mites = _observe(
            state["zone"]["id"],
            state["cycle"]["id"],
            scout["id"],
            pest_code="SPIDER_MITE",
            pest_count_per_plant=0.250,
            observed_at="2026-08-06T07:30:00Z",
        )

        assert thrips["threshold_status"] == "BELOW", (
            f"0.900 thrips per plant sits under the 1.000 thrips threshold, got "
            f"{thrips['threshold_status']}"
        )
        assert thrips["release_required"] is False, (
            "a below-threshold thrips count calls for no release"
        )
        assert mites["threshold_status"] == "AT", (
            f"0.250 mites per plant lands exactly on the 0.250 mite threshold, got "
            f"{mites['threshold_status']}"
        )
        assert mites["release_required"] is True, (
            "a count sitting on the mite threshold calls for a release"
        )

    def test_first_at_threshold_observation_opens_the_compartment_alert(self, api):
        """PRD §3.6: "When the compartment's `open_pest_alert_count` was 0 before the observation and either its `reentry_clear_at` is null or the current logical clock has reached it, the counter rises to 1 and the compartment moves `NORMAL` → `SCOUT_ALERT`, with the compartment's `version` incrementing by one."

        Design: Corner/calculations/pest_action_thresholds_are_read_per_pest_code
        """
        state = setup_transplanted_cycle(clock="2026-08-06T00:00:00Z")
        scout = create_scout_worker()
        _observe(
            state["zone"]["id"],
            state["cycle"]["id"],
            scout["id"],
            pest_code="THRIPS",
            pest_count_per_plant=0.900,
            observed_at="2026-08-06T07:00:00Z",
        )
        before = read_zone(state["zone"]["id"])
        assert before["open_pest_alert_count"] == 0, (
            "the below-threshold thrips round must leave the compartment untouched"
        )
        assert before["ipm_posture"] == "NORMAL", (
            f"expected ipm_posture NORMAL before the mite round, got "
            f"{before['ipm_posture']}"
        )

        _observe(
            state["zone"]["id"],
            state["cycle"]["id"],
            scout["id"],
            pest_code="SPIDER_MITE",
            pest_count_per_plant=0.250,
            observed_at="2026-08-06T07:30:00Z",
        )

        after = read_zone(state["zone"]["id"])
        assert after["open_pest_alert_count"] == 1, (
            f"expected open_pest_alert_count 1, got {after['open_pest_alert_count']}"
        )
        assert after["ipm_posture"] == "SCOUT_ALERT", (
            f"expected ipm_posture SCOUT_ALERT, got {after['ipm_posture']}"
        )
        assert after["version"] == before["version"] + 1, (
            f"expected the compartment version to rise from {before['version']} to "
            f"{before['version'] + 1}, got {after['version']}"
        )


class TestAllocationWaterfallPriorityOrder:
    """One 1200 lb grade A pool against two 1000 lb weekly commitments."""

    def test_run_returns_both_weeks_in_priority_order_with_figures_restated(self, api):
        """PRD §3.10: "The run returns every week it evaluated, in the same `priority_rank` ascending then program `created_at` ascending order, with `allocated_lbs`, `fill_rate_pct`, `provisional_shortfall_lbs` and `provisional_penalty_usd` all recomputed."

        Design: Corner/calculations/waterfall_allocation_fills_the_higher_priority_week_before_the_next
        """
        state = _two_programs_competing_for_one_lot()

        evaluated = _run_waterfall()

        assert len(evaluated) == 2, (
            f"both weeks starting 2026-08-31 must be evaluated, got {evaluated}"
        )
        assert evaluated[0]["id"] == state["week_one"]["id"], (
            "the rank 1 week must be returned first"
        )
        assert evaluated[1]["id"] == state["week_two"]["id"], (
            "the rank 2 week must be returned second"
        )
        assert evaluated[0]["allocated_lbs"] == pytest.approx(1000.00, abs=0.01), (
            f"expected allocated_lbs 1000.00 on the rank 1 week, got "
            f"{evaluated[0]['allocated_lbs']}"
        )
        assert evaluated[0]["fill_rate_pct"] == pytest.approx(100.00, abs=0.01), (
            f"expected fill_rate_pct 100.00 on the rank 1 week, got "
            f"{evaluated[0]['fill_rate_pct']}"
        )
        assert evaluated[0]["provisional_shortfall_lbs"] == pytest.approx(0.00, abs=0.01)
        assert_money(
            evaluated[0]["provisional_penalty_usd"],
            0.00,
            "provisional_penalty_usd on the rank 1 week",
        )
        assert evaluated[1]["allocated_lbs"] == pytest.approx(200.00, abs=0.01), (
            f"only the 200 lbs left over reach the rank 2 week, got "
            f"{evaluated[1]['allocated_lbs']}"
        )
        assert evaluated[1]["fill_rate_pct"] == pytest.approx(20.00, abs=0.01), (
            f"expected fill_rate_pct 20.00 on the rank 2 week, got "
            f"{evaluated[1]['fill_rate_pct']}"
        )
        assert evaluated[1]["provisional_shortfall_lbs"] == pytest.approx(
            800.00, abs=0.01
        ), (
            f"expected provisional_shortfall_lbs 800.00 on the rank 2 week, got "
            f"{evaluated[1]['provisional_shortfall_lbs']}"
        )
        assert_money(
            evaluated[1]["provisional_penalty_usd"],
            240.00,
            "provisional_penalty_usd on the rank 2 week",
        )

    def test_pounds_are_not_spread_evenly_across_the_two_weeks(self, api):
        """PRD §3.10: "The waterfall then walks the targets in order, and each target is filled as completely as the remaining pounds allow before the next target receives anything — pounds are never spread evenly."

        Design: Corner/calculations/waterfall_allocation_fills_the_higher_priority_week_before_the_next
        """
        state = _two_programs_competing_for_one_lot()

        _run_waterfall()

        week_one = read_week(state["week_one"]["id"])
        week_two = read_week(state["week_two"]["id"])
        assert week_one["allocated_lbs"] == pytest.approx(
            week_one["committed_lbs"], abs=0.01
        ), (
            f"the rank 1 week must be filled to its full "
            f"{week_one['committed_lbs']} lbs, got {week_one['allocated_lbs']}"
        )
        assert week_two["allocated_lbs"] == pytest.approx(200.00, abs=0.01), (
            f"an even 600/600 split is forbidden; expected 200.00 on the rank 2 week, "
            f"got {week_two['allocated_lbs']}"
        )

    def test_tail_week_stays_open_carrying_its_shortfall(self, api):
        """PRD §3.10: "When the pounds run out part-way down the target order, the earlier high-priority weeks are filled completely and the tail weeks remain `OPEN` carrying a positive `provisional_shortfall_lbs`."

        Design: Corner/calculations/waterfall_allocation_fills_the_higher_priority_week_before_the_next
        """
        state = _two_programs_competing_for_one_lot()

        _run_waterfall()

        week_one = read_week(state["week_one"]["id"])
        week_two = read_week(state["week_two"]["id"])
        assert week_one["status"] == "ALLOCATED", (
            f"the fully filled rank 1 week reaches ALLOCATED, got {week_one['status']}"
        )
        assert week_one["provisional_shortfall_lbs"] == pytest.approx(0.00, abs=0.01), (
            f"a fully filled week carries no shortfall, got "
            f"{week_one['provisional_shortfall_lbs']}"
        )
        assert week_two["status"] == "OPEN", (
            f"the starved rank 2 week must stay OPEN, got {week_two['status']}"
        )
        assert week_two["provisional_shortfall_lbs"] == pytest.approx(800.00, abs=0.01), (
            f"expected provisional_shortfall_lbs 800.00, got "
            f"{week_two['provisional_shortfall_lbs']}"
        )

    def test_grade_a_only_programs_never_touch_the_grade_b_pool(self, api):
        """PRD §3.10: "The grades to draw from are grade `A` alone when the program's `grade_spec` is `A_ONLY`, and grade `A` followed by grade `B` when it is `A_AND_B`, with **grade A fully exhausted across every candidate lot before grade B is touched at all**."

        Design: Corner/calculations/waterfall_allocation_fills_the_higher_priority_week_before_the_next
        """
        state = _two_programs_competing_for_one_lot()

        _run_waterfall()

        lot = read_lot(state["lot"]["id"])
        assert lot["allocated_a_lbs"] == pytest.approx(1200.00, abs=0.01), (
            f"the whole 1200.00 lb grade A pool is drawn down, got "
            f"{lot['allocated_a_lbs']}"
        )
        assert lot["available_a_lbs"] == pytest.approx(0.00, abs=0.01), (
            f"expected available_a_lbs 0.00, got {lot['available_a_lbs']}"
        )
        assert lot["allocated_b_lbs"] == pytest.approx(0.00, abs=0.01), (
            f"neither A_ONLY program may draw grade B, got allocated_b_lbs "
            f"{lot['allocated_b_lbs']}"
        )
        assert lot["available_b_lbs"] == pytest.approx(700.00, abs=0.01), (
            f"the 700.00 lb grade B pool must be untouched, got "
            f"{lot['available_b_lbs']}"
        )
