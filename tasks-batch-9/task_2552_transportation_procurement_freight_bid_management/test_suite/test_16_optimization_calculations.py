"""The aggregation orders and pinned roundings behind a scenario's headline figures.

Two of these arithmetics have a plausible wrong reading that the numbers here are
chosen to separate: the cost ratio is a ratio of sums rather than a mean of
per-lane ratios, and the event baseline drops a lane that has no incumbent while
still counting its volume. The other two pin the waterfall's grant rule — a
runner-up takes the remainder, not its own commitment, and a withdrawn bid is not
a candidate at all.
"""

from test_helpers import (
    BID_A,
    CARRIER_ID_REF,
    DEFAULT_CLOCK,
    DUAL_MODE_CARRIER,
    LANE_A_WITH_INCUMBENT,
    LANE_B_REEFER,
    TEST_DEFAULTS,
    api_client,
    close_round,
    create_event_with_locked_lanes,
    create_qualified_carrier,
    invite_and_accept,
    list_allocations,
    make_carrier_rep_headers,
    open_round,
    publish_guide,
    read_lane,
    read_lane_bid,
    run_optimization,
    second_carrier_overrides,
    set_clock,
    setup_closed_round_with_bid,
    submit_bid,
    validate_success,
)

# ── The two-lane portfolio, both lanes carrying an incumbent baseline ─────────

#: Lane B as lane A's sibling in the baseline: 600 miles at 2.1000 incumbent.
LANE_B_WITH_INCUMBENT = dict(
    LANE_B_REEFER,
    incumbent_carrier_id=CARRIER_ID_REF,
    incumbent_rate_per_mile=2.1000,
)

# round(1147 x 2.4000, 2) + 137.55, times 550 planned loads.
LANE_A_BASELINE_USD = 1589692.50
# round(600 x 2.1000, 2) + 90.00, times 120 planned loads.
LANE_B_BASELINE_USD = 162000.00
BOTH_LANE_BASELINE_USD = 1751692.50
SCOPE_VOLUME_LOADS = 670

#: A flat 2.0000 all-in quote on lane A and 1.9000 on lane B.
FLAT_BID_A = {"rate_per_mile": 2.0000}
FLAT_BID_B = {
    "rate_per_mile": 1.9000,
    "committed_volume_loads": TEST_DEFAULTS["BID_B_COMMITTED_VOLUME_LOADS"],
    "transit_days_offered": TEST_DEFAULTS["BID_B_TRANSIT_DAYS_OFFERED"],
}

# 2294.00 linehaul + round(137.55 x 1.15, 2) accessorial, and 1140.00 + 103.50.
LANE_A_COST_PER_LOAD = 2452.18
LANE_B_COST_PER_LOAD = 1243.50
LANE_A_PLAN_LOADS = TEST_DEFAULTS["LANE_A_ANNUAL_VOLUME_LOADS"]
LANE_B_PLAN_LOADS = TEST_DEFAULTS["LANE_B_ANNUAL_VOLUME_LOADS"]
LANE_A_ALLOCATED_COST_USD = 1348699.00
LANE_B_ALLOCATED_COST_USD = 149220.00
BOTH_LANE_TOTAL_COST_USD = 1497919.00

# 1497919.00 / 1751692.50 to six places, and the objective it produces.
RATIO_OF_SUMS_OBJECTIVE = 41.09
#: What averaging the two per-lane ratios would have produced instead.
MEAN_OF_RATIOS_OBJECTIVE = 39.46

# ── One lane, two carriers, two routing seats ────────────────────────────────

#: The incumbent's quote: 2.1152 per mile with only 300 loads committed.
INCUMBENT_BID = dict(BID_A, committed_volume_loads=300)
#: The challenger's quote: dearer per mile but offering 400 loads.
CHALLENGER_BID = {
    "rate_per_mile": 2.2000,
    "fuel_surcharge_included": True,
    "committed_volume_loads": 400,
    "transit_days_offered": 3,
}
CHALLENGER_OVERRIDES = second_carrier_overrides(
    scac_code="BFLX", diversity_classification="MWBE"
)

INCUMBENT_COST_PER_LOAD = 2584.31
CHALLENGER_COST_PER_LOAD = 2681.58
INCUMBENT_EVALUATED_TOTAL_USD = 775293.00
CHALLENGER_EVALUATED_TOTAL_USD = 1072632.00
INCUMBENT_RANK_SCORE = 736528.35
CHALLENGER_RANK_SCORE = 1019000.40

PRIMARY_GRANT_LOADS = 300
REMAINDER_GRANT_LOADS = 250
PRIMARY_PCT = 54.55
REMAINDER_PCT = 45.45
REMAINDER_COST_USD = 670395.00
TWO_SEAT_TOTAL_COST_USD = 1445688.00
TWO_SEAT_OBJECTIVE = 42.65

# After the incumbent withdraws, the challenger takes the whole seat it offered.
SOLE_GRANT_LOADS = 400
SOLE_GRANT_PCT = 72.73
SOLE_COVERAGE_PCT = 72.73
SOLE_TOTAL_COST_USD = 1072632.00


def _two_lane_closed_round():
    """Both lanes with an incumbent, one flat bid on each, round closed."""
    return setup_closed_round_with_bid(
        bid_overrides=[dict(FLAT_BID_A), dict(FLAT_BID_B)],
        carrier_overrides=dict(DUAL_MODE_CARRIER),
        lane_overrides=[dict(LANE_A_WITH_INCUMBENT), dict(LANE_B_WITH_INCUMBENT)],
    )


def _two_carrier_lane():
    """One locked lane, two accepted bidders, one bid each, still open.

    The incumbent quotes the lower service-adjusted cost but commits only 300 of
    the lane's 550 loads; the challenger is dearer and commits 400.
    """
    set_clock(DEFAULT_CLOCK)
    incumbent = create_qualified_carrier()
    challenger = create_qualified_carrier(carrier_overrides=CHALLENGER_OVERRIDES)
    event, lanes = create_event_with_locked_lanes(
        lane_overrides=[
            dict(LANE_A_WITH_INCUMBENT, incumbent_carrier_id=incumbent["id"])
        ]
    )
    invite_and_accept(event["id"], incumbent["id"])
    invite_and_accept(event["id"], challenger["id"])
    bid_round = open_round(event["id"])
    incumbent_bid = submit_bid(
        bid_round["id"], lanes[0]["id"], incumbent["id"], **INCUMBENT_BID
    )
    challenger_bid = submit_bid(
        bid_round["id"], lanes[0]["id"], challenger["id"], **CHALLENGER_BID
    )
    return {
        "incumbent": incumbent,
        "challenger": challenger,
        "event": event,
        "lane": lanes[0],
        "bid_round": bid_round,
        "incumbent_bid": incumbent_bid,
        "challenger_bid": challenger_bid,
    }


class TestObjectiveScoreIsARatioOfSums:
    """A 4.58x volume gap between two lanes makes the aggregation order visible."""

    def test_the_objective_score_weights_the_lanes_by_size_not_equally(self):
        """41.09 is the ratio of sums; 39.46 is the mean of per-lane ratios.

        PRD §3.6: "Sum the `allocated_cost_usd` of the picks that fall on those lanes,
        sum the `baseline_cost_usd` of those lanes, divide the first sum by the second,
        and round to 6 decimal places."
        PRD §3.6: "This is a **ratio of sums, never a mean of per-lane ratios**:
        averaging each lane's own cost-to-baseline ratio gives every lane equal weight
        regardless of size and yields a materially different, incorrect number."
        PRD §3.6: "Take the cost ratio subtracted from `1.000000`, so that lower award
        cost scores higher, and multiply by `cost_weight`."
        PRD §3.6: "Add the four products, multiply the total by `100.00`, and round to 2
        decimal places."

        Design: Corner/calculations/objective_score_is_a_ratio_of_sums_across_two_unequally_sized_lanes
        """
        ctx = _two_lane_closed_round()
        assert float(ctx["event"]["baseline_cost_usd"]) == BOTH_LANE_BASELINE_USD
        assert ctx["event"]["total_scope_volume_loads"] == SCOPE_VOLUME_LOADS

        run = run_optimization(ctx["event"]["id"], scenario_label="RATIO_OF_SUMS")
        assert run["status"] == "COMPLETED"
        assert run["proposed_primary_count"] == 2
        assert run["proposed_backup_count"] == 0
        assert run["infeasible_lane_ids"] == []

        assert float(run["total_cost_usd"]) == BOTH_LANE_TOTAL_COST_USD
        assert float(run["coverage_pct"]) == 100.00
        assert float(run["diversity_pct"]) == 0.00, (
            "the single carrier is classified NONE, so no allocated volume is diverse"
        )
        assert float(run["objective_score"]) == RATIO_OF_SUMS_OBJECTIVE
        assert float(run["objective_score"]) != MEAN_OF_RATIOS_OBJECTIVE, (
            "averaging the two per-lane cost ratios understates the objective score"
        )

    def test_each_lane_is_granted_its_plan_volume_at_its_own_rounded_cost(self):
        """The two picks are what the two sums are built from, cent for cent.

        PRD §3.6: "A positive grant produces a pick carrying the next
        `routing_position` in sequence, `allocated_volume_loads` equal to the grant,
        `allocated_pct` equal to the grant multiplied by `100.00`, divided by
        `annual_volume_loads` and rounded to 2 decimal places, and `allocated_cost_usd`
        equal to the bid's `cost_per_load_usd` multiplied by the grant and rounded to 2
        decimal places."
        PRD §3.5: "Add `linehaul_per_load_usd` and `accessorial_per_load_usd`. Both are
        already rounded to 2 decimal places, and `cost_per_load_usd` is the sum of those
        two already-rounded figures."
        PRD §3.6: "`total_cost_usd` is the sum of the picks' `allocated_cost_usd`,
        rounded to 2 decimal places."

        Design: Corner/calculations/objective_score_is_a_ratio_of_sums_across_two_unequally_sized_lanes
        """
        ctx = _two_lane_closed_round()
        assert float(ctx["bids"][0]["cost_per_load_usd"]) == LANE_A_COST_PER_LOAD
        assert float(ctx["bids"][1]["cost_per_load_usd"]) == LANE_B_COST_PER_LOAD

        run = run_optimization(ctx["event"]["id"], scenario_label="RATIO_OF_SUMS")
        publish_guide(run["id"])

        by_lane = {
            allocation["lane_id"]: allocation
            for allocation in list_allocations(bid_event_id=ctx["event"]["id"])
        }
        assert len(by_lane) == 2

        lane_a = by_lane[ctx["lanes"][0]["id"]]
        assert lane_a["routing_position"] == "PRIMARY"
        assert lane_a["allocated_volume_loads"] == LANE_A_PLAN_LOADS
        assert float(lane_a["allocated_cost_usd"]) == LANE_A_ALLOCATED_COST_USD

        lane_b = by_lane[ctx["lanes"][1]["id"]]
        assert lane_b["routing_position"] == "PRIMARY"
        assert lane_b["allocated_volume_loads"] == LANE_B_PLAN_LOADS
        assert float(lane_b["allocated_cost_usd"]) == LANE_B_ALLOCATED_COST_USD

        assert (
            float(lane_a["allocated_cost_usd"]) + float(lane_b["allocated_cost_usd"])
            == BOTH_LANE_TOTAL_COST_USD
        )


class TestEventBaselineExcludesTheUnpricedLane:
    """A lane with no incumbent is in scope for volume and out of it for savings."""

    def test_the_flagged_lane_counts_toward_scope_but_not_toward_the_baseline(self):
        """670 loads of scope against a baseline that names only the priced lane.

        PRD §3.3: "`baseline_cost_usd` is the sum of `baseline_cost_usd` over those
        same lanes, **excluding any lane whose `data_quality_flags` contain
        `NO_INCUMBENT_BASELINE`**, rounded to 2 decimal places."
        PRD §3.3: "`total_scope_volume_loads` is the sum of `annual_volume_loads` over
        the event's lanes whose `status` is `VALIDATED`, `LOCKED`, `AWARDED` or
        `UNDER_REBID`."
        PRD §3.3: "`NO_INCUMBENT_BASELINE` fires when either `incumbent_carrier_id` or
        `incumbent_rate_per_mile` is null; one without the other is not a usable
        baseline."
        PRD §3.3: "When `incumbent_rate_per_mile` is null the baseline is `0.00`
        outright."

        Design: Corner/calculations/event_baseline_excludes_lanes_flagged_no_incumbent_baseline_but_counts_their_volume
        """
        set_clock(DEFAULT_CLOCK)
        incumbent = create_qualified_carrier()
        event, lanes = create_event_with_locked_lanes(
            lane_overrides=[
                dict(LANE_A_WITH_INCUMBENT, incumbent_carrier_id=incumbent["id"]),
                dict(LANE_B_REEFER),
            ]
        )

        priced, unpriced = lanes
        assert priced["status"] == "VALIDATED"
        assert priced["data_quality_flags"] == []
        assert float(priced["baseline_cost_usd"]) == LANE_A_BASELINE_USD
        assert unpriced["status"] == "VALIDATED", "the missing incumbent is advisory"
        assert unpriced["data_quality_flags"] == ["NO_INCUMBENT_BASELINE"]
        assert float(unpriced["baseline_cost_usd"]) == 0.00

        assert event["status"] == "LANES_LOCKED"
        assert event["total_scope_volume_loads"] == SCOPE_VOLUME_LOADS
        assert float(event["baseline_cost_usd"]) == LANE_A_BASELINE_USD, (
            "the flagged lane is filtered out of the baseline sum entirely"
        )
        assert float(event["baseline_cost_usd"]) != BOTH_LANE_BASELINE_USD
        assert float(event["coverage_pct"]) == 0.00


class TestWaterfallGrantsTheRunnerUpOnlyTheRemainder:
    """Two seats on one lane: the second seat is sized by what the first left."""

    @staticmethod
    def _two_seat_run(scenario_label="TWO_SEATS"):
        ctx = _two_carrier_lane()
        close_round(ctx["bid_round"]["id"])
        ctx["run"] = run_optimization(
            ctx["event"]["id"],
            scenario_label=scenario_label,
            max_carriers_per_lane=2,
        )
        return ctx

    def test_the_runner_up_receives_the_remainder_and_not_its_own_commitment(self):
        """250 of the 400 loads BFLX offered, because 300 were already gone.

        PRD §3.6: "For each candidate it computes a grant as the smallest of three
        quantities: the lane's remaining volume, the bid's `committed_volume_loads`, and
        the share cap."
        PRD §3.6: "The remaining volume is then reduced by the grant and the next
        position becomes current."
        PRD §3.6: "Three routing positions are available in strict order: `PRIMARY`,
        then `BACKUP_1`, then `BACKUP_2`, capped at the smaller of the run's effective
        `max_carriers_per_lane` and the structural maximum of 3 positions."
        PRD §3.5: "Subtract `service_credit_pct` from 1, multiply
        `evaluated_total_cost_usd` by that factor, and round to 2 decimal places."

        Design: Corner/calculations/waterfall_fills_primary_then_backup_and_grants_the_remainder_to_the_runner_up
        """
        ctx = self._two_seat_run()
        incumbent_bid = read_lane_bid(ctx["incumbent_bid"]["id"])
        challenger_bid = read_lane_bid(ctx["challenger_bid"]["id"])
        assert float(incumbent_bid["cost_per_load_usd"]) == INCUMBENT_COST_PER_LOAD
        assert incumbent_bid["awardable_volume_loads"] == PRIMARY_GRANT_LOADS
        assert (
            float(incumbent_bid["evaluated_total_cost_usd"])
            == INCUMBENT_EVALUATED_TOTAL_USD
        )
        assert float(incumbent_bid["cost_rank_score"]) == INCUMBENT_RANK_SCORE
        assert float(challenger_bid["cost_per_load_usd"]) == CHALLENGER_COST_PER_LOAD
        assert (
            float(challenger_bid["evaluated_total_cost_usd"])
            == CHALLENGER_EVALUATED_TOTAL_USD
        )
        assert float(challenger_bid["cost_rank_score"]) == CHALLENGER_RANK_SCORE

        run = ctx["run"]
        assert run["proposed_primary_count"] == 1
        assert run["proposed_backup_count"] == 1
        publish_guide(run["id"])

        by_carrier = {
            allocation["carrier_id"]: allocation
            for allocation in list_allocations(lane_id=ctx["lane"]["id"])
        }
        primary = by_carrier[ctx["incumbent"]["id"]]
        assert primary["routing_position"] == "PRIMARY"
        assert primary["allocated_volume_loads"] == PRIMARY_GRANT_LOADS
        assert float(primary["allocated_pct"]) == PRIMARY_PCT
        assert float(primary["allocated_cost_usd"]) == INCUMBENT_EVALUATED_TOTAL_USD

        backup = by_carrier[ctx["challenger"]["id"]]
        assert backup["routing_position"] == "BACKUP_1"
        assert backup["allocated_volume_loads"] == REMAINDER_GRANT_LOADS, (
            "the runner-up is capped by the lane's remaining volume, not by its offer"
        )
        assert float(backup["allocated_pct"]) == REMAINDER_PCT
        assert float(backup["allocated_cost_usd"]) == REMAINDER_COST_USD

        assert read_lane(ctx["lane"]["id"])["unallocated_volume_loads"] == (
            LANE_A_PLAN_LOADS
        ), "proposed allocations reserve nothing on the lane"

    def test_the_diversity_term_reads_the_granted_remainder(self):
        """45.45, because the diverse carrier holds 250 of the 550 allocated loads.

        PRD §3.6: "`diversity_pct` is `0.00` when nothing was allocated; otherwise it is
        the allocated volume belonging to carriers whose `diversity_classification` is
        not `NONE`, multiplied by `100.00`, divided by the total allocated volume,
        rounded to 2 decimal places."
        PRD §3.6: "Divide `diversity_pct` by `100.00`, round to 6 decimal places, and
        multiply by `diversity_weight`."
        PRD §3.6: "otherwise, for each pick multiply its `allocated_volume_loads` by its
        carrier's `composite_score` divided by `100.00`, sum those products, divide by
        the total `allocated_volume_loads`, and round to 6 decimal places"

        Design: Corner/calculations/waterfall_fills_primary_then_backup_and_grants_the_remainder_to_the_runner_up
        """
        ctx = self._two_seat_run()
        assert ctx["challenger"]["diversity_classification"] == "MWBE"
        assert ctx["incumbent"]["diversity_classification"] == "NONE"

        run = ctx["run"]
        assert float(run["total_cost_usd"]) == TWO_SEAT_TOTAL_COST_USD
        assert float(run["coverage_pct"]) == 100.00
        assert float(run["diversity_pct"]) == REMAINDER_PCT, (
            "the denominator is allocated volume, not the lane's planned volume"
        )
        assert float(run["objective_score"]) == TWO_SEAT_OBJECTIVE


class TestWithdrawnBidsAreNotCandidates:
    """The cheapest bid on the lane does not count once it has been withdrawn."""

    def test_the_withdrawn_cheapest_bid_neither_wins_nor_takes_a_backup_seat(self):
        """The dearer surviving bid takes PRIMARY for its whole commitment.

        PRD §3.6: "For one lane, the candidate set is the lane's bids **from the event's
        most recent `CLOSED` round only** — earlier rounds are superseded by the
        negotiation and are not mixed in — whose `status` is `SUBMITTED` or
        `SHORTLISTED`"
        PRD §3.5: "The bid moves to the terminal `WITHDRAWN` and `withdrawn_at` is set
        to the logical clock."
        PRD §3.6: "`infeasible_lane_ids` lists the `id` of every in-scope lane that
        produced no `PRIMARY` pick at all, ordered by the lane's `created_at` ascending."
        PRD §3.6: "`coverage_pct` is the sum of the picks' `allocated_volume_loads`,
        multiplied by `100.00`, divided by the sum of the in-scope lanes'
        `annual_volume_loads`, rounded to 2 decimal places."

        Design: Corner/calculations/waterfall_eligible_set_ignores_a_withdrawn_bid_even_when_it_was_the_cheapest
        """
        ctx = _two_carrier_lane()
        validate_success(
            api_client.withdraw_lane_bid(
                ctx["incumbent_bid"]["id"],
                make_carrier_rep_headers(ctx["incumbent"]["id"]),
            )
        )
        close_round(ctx["bid_round"]["id"])

        run = run_optimization(
            ctx["event"]["id"],
            scenario_label="AFTER_WITHDRAWAL",
            max_carriers_per_lane=2,
        )
        assert run["status"] == "COMPLETED"
        assert run["proposed_primary_count"] == 1
        assert run["proposed_backup_count"] == 0
        assert float(run["total_cost_usd"]) == SOLE_TOTAL_COST_USD
        assert float(run["coverage_pct"]) == SOLE_COVERAGE_PCT
        assert float(run["diversity_pct"]) == 100.00
        assert run["infeasible_lane_ids"] == [], (
            "a lane that produced a PRIMARY pick is covered, not infeasible"
        )

        publish_guide(run["id"])
        allocations = list_allocations(lane_id=ctx["lane"]["id"])
        assert len(allocations) == 1
        sole = allocations[0]
        assert sole["carrier_id"] == ctx["challenger"]["id"]
        assert sole["routing_position"] == "PRIMARY"
        assert sole["allocated_volume_loads"] == SOLE_GRANT_LOADS
        assert float(sole["allocated_pct"]) == SOLE_GRANT_PCT
        assert float(sole["allocated_cost_usd"]) == SOLE_TOTAL_COST_USD
        assert sole["lane_bid_id"] != ctx["incumbent_bid"]["id"]

        stale = read_lane_bid(ctx["incumbent_bid"]["id"])
        assert stale["status"] == "WITHDRAWN", (
            "the run must not re-status a withdrawn bid as shortlisted or not-awarded"
        )
