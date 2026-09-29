"""Derived arithmetic: smoothing, rollups, ramps, pooling and settlement money."""

from prd_bench_local_runner.testing import validate_paginated
from test_helpers.assertions import (
    assert_agent_coaching,
    assert_coverage_summary_shape,
    assert_cycle_ledgers,
    assert_hours,
    assert_interval_forecast,
    assert_interval_outsourcing,
    assert_partner_ledgers,
    assert_ratio,
    assert_settlement_amounts,
    assert_shift_adherence,
    assert_shift_axes,
    assert_shift_hours,
)
from test_helpers.constants import (
    ADHERENCE_ON_TRACK,
    ADHERENCE_OUT_OF_ADHERENCE,
    ALLOCATION_COMMITTED,
    ALLOCATION_PROPOSED,
    ALLOCATION_REVOKED,
    ALLOCATION_SETTLED,
    BILLING_COMMITMENT_FLOOR,
    BILLING_DELIVERED_ONLY,
    CLASS_STATUS_PLANNED,
    COACHING_ACTIVE,
    COACHING_NONE,
    EVENT_STATUS_CANCELLED,
    EVENT_STATUS_CONFIRMED,
    EVENT_STATUS_DRAFT,
    PARTNER_STATUS_ACTIVE,
    PARTNER_STATUS_PROBATION,
    PARTNER_STATUS_SUSPENDED,
    POSTURE_OPEN,
)
from test_helpers.fixtures import (
    CANONICAL_CLOCK,
    HORIZON_START,
    build_partner_week,
    build_published_week,
    charter_class,
    commit_allocation,
    file_performance_report,
    generate_allocations,
    generate_grid,
    lock_requirements,
    make_agent,
    make_forecast_group,
    make_hiring_class,
    make_labor_agreement,
    make_marketing_event,
    make_outsource_partner,
    make_planning_cycle,
    make_schedule_shift,
    make_shift_template,
    post_actuals,
    propose_allocation,
    publish_shift,
    read_agent,
    read_allocation,
    read_coverage_summary,
    read_cycle,
    read_group,
    read_hiring_class,
    read_interval,
    read_partner,
    record_observation,
    revoke_allocation,
    run_reforecast,
    set_clock,
    set_event_status,
    settle_allocation,
)
from test_helpers.test_users import (
    SOURCING_ALT_USER_ID,
    SOURCING_HEADERS,
    SOURCING_USER_ID,
)


class TestReforecastSmoothing:
    """The smoothing accumulator and the forward window it re-forecasts."""

    def test_multiplier_is_the_smoothed_accumulator_not_the_raw_ratio(self, api):
        """Two intervals that both ran twenty-five percent hot leave the multiplier at 1.1600.

        "Stepping through the sorted intervals, the system stores each interval's
        `observed_ratio` as its `actual_volume` divided by its `volume_forecast`
        rounded half up to four decimal places, then advances the accumulator to
        four-tenths of that same raw ratio plus six-tenths of the accumulator's
        previous value, and stores the new accumulator into that interval's
        `smoothed_ratio`, rounded half up to four decimal places."

        Design: Corner/calculations/reforecast_multiplier_from_smoothed_actuals
        """
        set_clock(api, CANONICAL_CLOCK)
        cycle = make_planning_cycle(api, name="W37-SMOOTH")
        group = make_forecast_group(api, cycle["id"])
        intervals = generate_grid(api, group["id"], HORIZON_START)
        first_posting = post_actuals(api, intervals[0]["id"], 600, 300)
        second_posting = post_actuals(api, intervals[1]["id"], 450, 300)
        assert_ratio(first_posting["observed_ratio"], 1.2500, "interval 0 observed_ratio")
        assert_ratio(second_posting["observed_ratio"], 1.2500, "interval 1 observed_ratio")
        before = read_cycle(api, cycle["id"])
        assert before["reforecast_generation"] == 0

        after = run_reforecast(
            api,
            cycle["id"],
            before["version"],
            "2026-09-07T09:00:00Z",
            forecast_group_id=group["id"],
        )

        assert after["reforecast_generation"] == 1
        assert_ratio(
            read_group(api, group["id"])["reforecast_multiplier"],
            1.1600,
            "reforecast_multiplier",
        )
        history_first = read_interval(api, intervals[0]["id"])
        history_second = read_interval(api, intervals[1]["id"])
        assert_ratio(history_first["smoothed_ratio"], 1.1000, "interval 0 smoothed_ratio")
        assert_ratio(history_second["smoothed_ratio"], 1.1600, "interval 1 smoothed_ratio")
        assert_interval_forecast(history_first, volume_forecast=480)
        assert_interval_forecast(history_second, volume_forecast=360)
        assert_interval_forecast(
            read_interval(api, intervals[2]["id"]),
            volume_forecast=278,
            required_agents=81,
        )
        assert_interval_forecast(
            read_interval(api, intervals[3]["id"]),
            volume_forecast=139,
            required_agents=41,
        )

    def test_history_is_replayed_in_interval_order_not_posting_order(self, api):
        """Posting the later interval first still smooths the earlier interval first.

        "A running accumulator is seeded at 1.0 on **every** run, so the outcome
        depends on the chronological order of the intervals and never on the order
        in which the actuals happened to be posted."

        Design: Corner/calculations/reforecast_replays_actuals_in_chronological_order
        """
        set_clock(api, CANONICAL_CLOCK)
        cycle = make_planning_cycle(api, name="W37-CHRONO")
        group = make_forecast_group(api, cycle["id"])
        intervals = generate_grid(api, group["id"], HORIZON_START)
        late_posting = post_actuals(api, intervals[1]["id"], 288, 300)
        early_posting = post_actuals(api, intervals[0]["id"], 600, 300)
        assert_ratio(late_posting["observed_ratio"], 0.8000, "interval 1 observed_ratio")
        assert_ratio(early_posting["observed_ratio"], 1.2500, "interval 0 observed_ratio")
        before = read_cycle(api, cycle["id"])

        after = run_reforecast(
            api,
            cycle["id"],
            before["version"],
            "2026-09-07T09:00:00Z",
            forecast_group_id=group["id"],
        )

        assert after["reforecast_generation"] == 1
        assert_ratio(
            read_group(api, group["id"])["reforecast_multiplier"],
            0.9800,
            "reforecast_multiplier",
        )
        assert_ratio(
            read_interval(api, intervals[0]["id"])["smoothed_ratio"],
            1.1000,
            "interval 0 smoothed_ratio",
        )
        assert_ratio(
            read_interval(api, intervals[1]["id"])["smoothed_ratio"],
            0.9800,
            "interval 1 smoothed_ratio",
        )
        assert_interval_forecast(
            read_interval(api, intervals[2]["id"]),
            volume_forecast=235,
            required_agents=69,
        )
        assert_interval_forecast(
            read_interval(api, intervals[3]["id"]),
            volume_forecast=118,
            required_agents=35,
        )


class TestForecastInputSets:
    """Which rows the forecasting chain is allowed to read."""

    def test_a_draft_driver_perturbs_nothing_until_it_is_confirmed(self, api):
        """A draft campaign leaves the grid alone; confirming it moves everything, cancelling it moves it back.

        "Each in-scope driver contributes its raw `uplift_pct` multiplied by its
        tier's confidence weight, those contributions are added together, and the
        sum is capped at 1.50 — no interval may ever be inflated by more than one
        hundred and fifty percent of its driver-free expectation no matter how many
        campaigns pile onto it."

        Design: Corner/calculations/draft_marketing_event_does_not_perturb_forecast
        """
        set_clock(api, CANONICAL_CLOCK)
        cycle = make_planning_cycle(api, name="W37-FWD")
        group = make_forecast_group(api, cycle["id"])
        intervals = generate_grid(api, group["id"], HORIZON_START)
        assert_interval_forecast(
            read_interval(api, intervals[0]["id"]),
            volume_forecast=480,
            required_agents=140,
        )

        event = make_marketing_event(
            api, cycle["id"], group["id"], name="Draft Push", uplift_pct=1.2000
        )

        assert event["status"] == EVENT_STATUS_DRAFT
        assert_interval_forecast(
            read_interval(api, intervals[0]["id"]),
            volume_forecast=480,
            aht_forecast_seconds=300,
            applied_event_uplift_pct=0.0000,
            required_agents=140,
        )

        set_event_status(api, event["id"], EVENT_STATUS_CONFIRMED)

        assert_interval_forecast(
            read_interval(api, intervals[0]["id"]),
            volume_forecast=1056,
            aht_forecast_seconds=405,
            applied_event_uplift_pct=1.2000,
            required_agents=415,
        )

        cancelled = set_event_status(api, event["id"], EVENT_STATUS_CANCELLED)

        assert cancelled["status"] == EVENT_STATUS_CANCELLED
        assert_interval_forecast(
            read_interval(api, intervals[0]["id"]),
            volume_forecast=480,
            aht_forecast_seconds=300,
            applied_event_uplift_pct=0.0000,
            required_agents=140,
        )


class TestCycleRollup:
    """The cycle-wide coverage and outsourcing summation."""

    def test_the_summary_sums_every_interval_of_the_cycle(self, api):
        """Two unstaffed CHAT intervals roll up to twenty required agents and a hundred and sixty-four unserved contacts.

        "A separate computed read rolls the whole cycle up: it returns
        `planning_cycle_id`, the current `posture`, `interval_count` as the number of
        interval plans in the cycle, `short_interval_count`, and cycle-wide sums
        named `total_required_agents`, `total_effective_scheduled_agents`,
        `total_coverage_gap`, `total_allocatable_volume`,
        `total_partner_committed_volume` and `total_unserved_volume`, each the
        arithmetic sum of the corresponding per-interval field."

        Design: Corner/calculations/coverage_summary_rolls_up_cycle_totals
        """
        world = build_partner_week(api, cycle_overrides={"name": "W37-SUMMARY"})
        for interval in world["intervals"]:
            assert_interval_forecast(
                read_interval(api, interval["id"]),
                volume_forecast=82,
                required_agents=10,
            )

        summary = read_coverage_summary(api, world["cycle"]["id"])

        assert_coverage_summary_shape(summary)
        assert summary["planning_cycle_id"] == world["cycle"]["id"]
        assert summary["posture"] == POSTURE_OPEN
        assert summary["interval_count"] == 2
        assert summary["short_interval_count"] == 2
        assert summary["total_required_agents"] == 20
        assert summary["total_effective_scheduled_agents"] == 0
        assert summary["total_coverage_gap"] == 20
        assert summary["total_allocatable_volume"] == 164
        assert summary["total_partner_committed_volume"] == 0
        assert summary["total_unserved_volume"] == 164

        empty = read_coverage_summary(
            api, world["cycle"]["id"], params={"service_date": "2026-09-08"}
        )

        assert empty["interval_count"] == 0
        assert empty["total_required_agents"] == 0
        assert empty["total_allocatable_volume"] == 0


class TestAdherenceArithmetic:
    """The four-decimal shift score and the seconds-weighted agent rollup."""

    def test_the_shift_score_rounds_half_up_at_the_fourth_decimal(self, api):
        """Three thousand non-adherent seconds out of twenty-seven thousand score 0.8889, not 0.8888.

        "`adherence_pct` is the shift's `scheduled_seconds` minus its
        `out_of_adherence_seconds` plus its `excused_seconds`, all divided by its
        `scheduled_seconds`, rounded half up to four decimal places and clamped into
        the band from 0.0000 to 1.0000 inclusive."

        Design: Corner/calculations/shift_adherence_pct_rounds_half_up_at_four_decimals
        """
        world = build_published_week(api, cycle_overrides={"name": "W37-PREC"})
        assert_shift_hours(world["shift"], scheduled_seconds=27000)

        observed = record_observation(api, world["shift"]["id"], 3000)

        assert_shift_adherence(
            observed, out_of_adherence_seconds=3000, excused_seconds=0, adherence_pct=0.8889
        )
        assert_shift_axes(observed, adherence_status=ADHERENCE_ON_TRACK)
        assert_agent_coaching(
            read_agent(api, world["agent"]["id"]),
            adherence_pct=0.8889,
            coaching_flag_count=0,
            coaching_status=COACHING_NONE,
        )

    def test_the_agent_score_pools_two_shifts_by_seconds(self, api):
        """A long shift at 0.8000 and a short one at 0.5000 pool to 0.6875, not to their 0.6500 mean.

        "An agent's `adherence_pct` is seconds-weighted across their scored shifts,
        not an average of percentages."

        Design: Corner/calculations/agent_adherence_pools_two_shifts_by_seconds
        """
        set_clock(api, CANONICAL_CLOCK)
        agreement = make_labor_agreement(api, code="LA-CORE")
        cycle = make_planning_cycle(api, name="W37-POOL")
        group = make_forecast_group(api, cycle["id"])
        generate_grid(api, group["id"], HORIZON_START)
        agent = make_agent(api, agreement["id"], employee_code="E-001")
        monday_template = make_shift_template(api, cycle["id"], code="T-MON")
        tuesday_template = make_shift_template(
            api, cycle["id"], code="T-TUE", duration_minutes=300, days_of_week=[1]
        )
        long_shift = make_schedule_shift(
            api, cycle["id"], agent["id"], monday_template["id"], "2026-09-07"
        )
        short_shift = make_schedule_shift(
            api, cycle["id"], agent["id"], tuesday_template["id"], "2026-09-08"
        )
        assert_shift_hours(long_shift, scheduled_seconds=27000)
        assert_shift_hours(short_shift, scheduled_seconds=16200)
        lock_requirements(api, cycle["id"])
        publish_shift(api, long_shift["id"])
        publish_shift(api, short_shift["id"])

        first_observation = record_observation(api, long_shift["id"], 5400)

        assert_shift_adherence(first_observation, adherence_pct=0.8000)
        assert_shift_axes(first_observation, adherence_status=ADHERENCE_OUT_OF_ADHERENCE)
        assert_agent_coaching(
            read_agent(api, agent["id"]), adherence_pct=0.8000, coaching_flag_count=1
        )

        second_observation = record_observation(api, short_shift["id"], 8100)

        assert_shift_adherence(second_observation, adherence_pct=0.5000)
        assert_shift_axes(second_observation, adherence_status=ADHERENCE_OUT_OF_ADHERENCE)
        assert_agent_coaching(
            read_agent(api, agent["id"]),
            adherence_pct=0.6875,
            coaching_flag_count=2,
            coaching_status=COACHING_ACTIVE,
        )


class TestHiringRamp:
    """The two strict date comparisons that place a cohort on its ramp."""

    def test_the_ramp_boundaries_are_strict_on_both_comparisons(self, api):
        """Three cohorts straddling the horizon end contribute 0.00, 10.50 and 21.00 full-time equivalents.

        "`effective_fte_at_horizon_end` then evaluates the ramp at the cycle's
        `horizon_end_date`: if that date falls strictly before `nesting_from_date`,
        the class contributes 0.00; otherwise, if it falls strictly before
        `productive_from_date`, the class contributes `expected_graduates`
        multiplied by one half, rounded half up to two decimal places; otherwise the
        class contributes the full `expected_graduates`, expressed to two decimal
        places."

        Design: Corner/calculations/hiring_class_ramp_fte_at_nesting_and_productive_boundaries
        """
        set_clock(api, CANONICAL_CLOCK)
        agreement = make_labor_agreement(api, code="LA-CORE")
        cycle = make_planning_cycle(api, name="W37-RAMP")

        after_horizon = make_hiring_class(
            api,
            cycle["id"],
            agreement["id"],
            cohort_name="C-LATE",
            start_date="2026-09-07",
            training_weeks=1,
            nesting_weeks=1,
        )
        nesting = make_hiring_class(
            api,
            cycle["id"],
            agreement["id"],
            cohort_name="C-NEST",
            start_date="2026-09-06",
            training_weeks=1,
            nesting_weeks=1,
        )
        productive = make_hiring_class(
            api,
            cycle["id"],
            agreement["id"],
            cohort_name="C-PROD",
            start_date="2026-08-30",
            training_weeks=1,
            nesting_weeks=1,
        )

        for cohort in (after_horizon, nesting, productive):
            assert cohort["status"] == CLASS_STATUS_PLANNED
            assert cohort["expected_graduates"] == 21, (
                "twenty-four seats at 0.1250 attrition floor to twenty-one graduates"
            )
        assert after_horizon["nesting_from_date"] == "2026-09-14"
        assert nesting["nesting_from_date"] == "2026-09-13"
        assert nesting["productive_from_date"] == "2026-09-20"
        assert productive["productive_from_date"] == "2026-09-13"
        assert_hours(after_horizon["effective_fte_at_horizon_end"], 0.00, "C-LATE FTE")
        assert_hours(nesting["effective_fte_at_horizon_end"], 10.50, "C-NEST FTE")
        assert_hours(productive["effective_fte_at_horizon_end"], 21.00, "C-PROD FTE")
        assert_cycle_ledgers(read_cycle(api, cycle["id"]), pipeline_fte=0.00)

        charter_class(api, after_horizon["id"])
        charter_class(api, nesting["id"])
        charter_class(api, productive["id"])

        assert_cycle_ledgers(read_cycle(api, cycle["id"]), pipeline_fte=31.50)
        assert_hours(
            read_hiring_class(api, nesting["id"])["effective_fte_at_horizon_end"],
            10.50,
            "C-NEST FTE after chartering",
        )


class TestPartnerPerformanceLadder:
    """The trailing window behind the rolling attainment and the status walk it drives."""

    def test_the_rolling_average_reads_only_the_last_three_reports(self, api):
        """A fourth report averages 0.7667 over the trailing three, not 0.7750 over all four.

        "The rolling attainment then reads the **last three** entries of that list in
        append order, using everything present when fewer than three reports exist:
        `rolling_sl_attainment_pct` is the sum of the attainment values in that
        window divided by the number of entries in it, rounded half up to four
        decimal places."

        Design: Corner/calculations/partner_rolling_performance_uses_trailing_window_of_three
        """
        set_clock(api, CANONICAL_CLOCK)
        partner = make_outsource_partner(
            api,
            legal_name="Partner Window",
            performance_threshold_pct=0.8500,
            billing_basis=BILLING_DELIVERED_ONLY,
        )
        assert_partner_ledgers(
            partner,
            status=PARTNER_STATUS_ACTIVE,
            rolling_sl_attainment_pct=None,
            performance_report_count=0,
        )
        assert partner["latest_sl_attainment_pcts"] == []

        first = file_performance_report(
            api, partner["id"], 0.8000, period_end_date="2026-08-09"
        )
        assert_partner_ledgers(
            first,
            status=PARTNER_STATUS_PROBATION,
            rolling_sl_attainment_pct=0.8000,
            consecutive_breach_count=1,
        )

        second = file_performance_report(
            api, partner["id"], 0.9000, period_end_date="2026-08-16"
        )
        assert_partner_ledgers(
            second,
            status=PARTNER_STATUS_ACTIVE,
            rolling_sl_attainment_pct=0.8500,
            consecutive_breach_count=0,
        )

        third = file_performance_report(
            api, partner["id"], 0.7000, period_end_date="2026-08-23"
        )
        assert_partner_ledgers(
            third,
            status=PARTNER_STATUS_PROBATION,
            rolling_sl_attainment_pct=0.8000,
            consecutive_breach_count=1,
        )

        fourth = file_performance_report(
            api, partner["id"], 0.7000, period_end_date="2026-08-30"
        )
        assert_partner_ledgers(
            fourth,
            status=PARTNER_STATUS_SUSPENDED,
            rolling_sl_attainment_pct=0.7667,
            consecutive_breach_count=2,
            performance_report_count=4,
        )
        assert len(read_partner(api, partner["id"])["latest_sl_attainment_pcts"]) == 4, (
            "the raw attainment list is append-only across all four reports"
        )


class TestPartnerVolumeLedger:
    """Which allocation statuses the interval's committed volume is allowed to count."""

    def test_only_committed_and_settled_allocations_occupy_the_interval(self, api):
        """A proposed thirty alongside a committed fifty occupies fifty, and settling keeps it there.

        "`partner_committed_volume` is the sum of `allocated_volume` over the
        interval's partner allocations whose status is `COMMITTED` or `SETTLED`;
        proposed and revoked allocations contribute nothing, which means settling a
        commitment leaves the interval's committed volume unchanged while revoking
        one releases it."

        Design: Corner/calculations/partner_committed_volume_counts_committed_and_settled_only
        """
        world = build_partner_week(api, cycle_overrides={"name": "W37-FILTER"})
        interval_id = world["intervals"][0]["id"]
        assert_interval_outsourcing(
            read_interval(api, interval_id), allocatable_volume=82
        )
        partner = make_outsource_partner(
            api, legal_name="Partner One", billing_basis=BILLING_DELIVERED_ONLY
        )
        proposed = propose_allocation(api, partner["id"], interval_id, 30)
        second = propose_allocation(api, partner["id"], interval_id, 50)
        assert proposed["status"] == ALLOCATION_PROPOSED
        assert_interval_outsourcing(
            read_interval(api, interval_id),
            partner_committed_volume=0,
            unserved_volume=82,
        )

        committed = commit_allocation(api, second["id"], partner["version"])

        assert committed["status"] == ALLOCATION_COMMITTED
        assert_interval_outsourcing(
            read_interval(api, interval_id),
            partner_committed_volume=50,
            unserved_volume=32,
        )

        settled = settle_allocation(api, second["id"], 40)

        assert settled["status"] == ALLOCATION_SETTLED
        assert_settlement_amounts(
            settled, shortfall_penalty_cents=31, settlement_amount_cents=469
        )
        assert_interval_outsourcing(
            read_interval(api, interval_id),
            partner_committed_volume=50,
            unserved_volume=32,
        )
        assert_partner_ledgers(
            read_partner(api, partner["id"]),
            committed_volume_outstanding=0,
            invoice_total_cents=469,
        )

        revoked = revoke_allocation(api, proposed["id"])

        assert revoked["status"] == ALLOCATION_REVOKED
        assert_interval_outsourcing(
            read_interval(api, interval_id),
            partner_committed_volume=50,
            unserved_volume=32,
        )


class TestAllocationWaterfall:
    """Cheapest-first filling and the contractual minimum that skips a candidate."""

    def test_the_waterfall_fills_the_cheapest_partner_and_skips_an_unaffordable_floor(
        self, api
    ):
        """Against eighty-two contacts the cheapest partner takes fifty, the middle one is skipped and the dearest takes thirty-two.

        "For each candidate it computes a cap — `interval_max_volume` when the
        partner is `ACTIVE`, `commitment_floor_volume` when the partner is on
        `PROBATION` — and takes the smaller of that cap and the remaining need. If
        the amount it could take is strictly less than that partner's
        `commitment_floor_volume`, the partner is **skipped entirely** rather than
        under-filled, because the contractual minimum cannot be honoured; the walk
        continues to the next candidate."

        Design: Corner/calculations/generate_fills_cheapest_partner_first_and_skips_unaffordable_floor
        """
        world = build_partner_week(api, cycle_overrides={"name": "W37-WATER"})
        interval_id = world["intervals"][0]["id"]
        cheapest = make_outsource_partner(
            api,
            legal_name="P-CHEAP",
            rate_per_contact_millicents=9000,
            interval_max_volume=50,
            commitment_floor_volume=10,
            billing_basis=BILLING_DELIVERED_ONLY,
        )
        middle = make_outsource_partner(
            api,
            legal_name="P-MID",
            rate_per_contact_millicents=10000,
            interval_max_volume=60,
            commitment_floor_volume=40,
            billing_basis=BILLING_DELIVERED_ONLY,
        )
        dearest = make_outsource_partner(
            api,
            legal_name="P-DEAR",
            rate_per_contact_millicents=12500,
            interval_max_volume=50,
            commitment_floor_volume=10,
            billing_basis=BILLING_DELIVERED_ONLY,
        )

        created = generate_allocations(api, interval_id)

        assert len(created) == 2, (
            f"the waterfall should create exactly two allocations, got {len(created)}"
        )
        assert created[0]["outsource_partner_id"] == cheapest["id"]
        assert created[0]["allocated_volume"] == 50
        assert created[1]["outsource_partner_id"] == dearest["id"]
        assert created[1]["allocated_volume"] == 32
        assert middle["id"] not in [row["outsource_partner_id"] for row in created], (
            "the middle partner's commitment floor of forty cannot be honoured by the "
            "thirty-two that remain, so it is skipped rather than under-filled"
        )
        for row in created:
            assert row["status"] == ALLOCATION_PROPOSED
            assert row["proposed_by_user_id"] == SOURCING_USER_ID
        assert_interval_outsourcing(
            read_interval(api, interval_id),
            partner_committed_volume=0,
            unserved_volume=82,
        )
        listed, meta = validate_paginated(
            api.list_partner_allocations(
                SOURCING_HEADERS, {"interval_plan_id": interval_id}
            )
        )
        assert meta["total_count"] == 2
        assert len(listed) == 2


class TestSettlementReconciliation:
    """The three stored amounts, the selected payable and the two ledgers they move."""

    def test_settlement_moves_the_selected_variant_into_the_invoice(self, api):
        """A commitment-floor partner delivering twenty-five of thirty is billed the full 375 cents.

        "The authoritative payable, `settlement_amount_cents`, is then selected by
        the partner's `billing_basis`: under `COMMITMENT_FLOOR` it is
        `settlement_floor_cents`, so the committed volume is billed regardless of
        delivery and under-delivery costs the buyer full price with no penalty
        credited; under `DELIVERED_ONLY` it is `settlement_delivered_cents` minus
        `shortfall_penalty_cents`, so only handled contacts are billed and the buyer
        is further credited a twenty-five-percent shortfall penalty."

        Design: Corner/calculations/partner_settlement_reconciles_outstanding_to_invoice
        """
        world = build_partner_week(api, cycle_overrides={"name": "W37-RECON"})
        interval_id = world["intervals"][0]["id"]
        partner = make_outsource_partner(
            api,
            legal_name="Partner Floor",
            rate_per_contact_millicents=12500,
            billing_basis=BILLING_COMMITMENT_FLOOR,
        )
        allocation = propose_allocation(api, partner["id"], interval_id, 30)
        committed = commit_allocation(api, allocation["id"], partner["version"])
        assert committed["committed_by_user_id"] == SOURCING_ALT_USER_ID
        assert_partner_ledgers(
            read_partner(api, partner["id"]),
            committed_volume_outstanding=30,
            invoice_total_cents=0,
        )

        settled = settle_allocation(api, allocation["id"], 25)

        assert settled["status"] == ALLOCATION_SETTLED
        assert_settlement_amounts(
            settled,
            settlement_floor_cents=375,
            settlement_delivered_cents=313,
            shortfall_penalty_cents=16,
            settlement_amount_cents=375,
        )
        assert_partner_ledgers(
            read_partner(api, partner["id"]),
            committed_volume_outstanding=0,
            invoice_total_cents=375,
        )
        assert read_allocation(api, allocation["id"])["delivered_volume"] == 25
