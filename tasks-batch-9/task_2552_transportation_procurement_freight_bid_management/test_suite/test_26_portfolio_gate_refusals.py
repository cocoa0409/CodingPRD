"""Portfolio-wide 422s, each provoked at the gate that actually owns it.

Coverage and feasibility are portfolio judgements about a scenario, so they are
answered when the routing guide is published. Diversity is a judgement about the
committed award, so it is answered only at the award itself. Each refusal has to
leave the run and the event exactly where they were: a portfolio refusal is a
no-op, not a partial award.
"""

from test_helpers import (
    ANALYST,
    CATEGORY_MANAGER,
    api_client,
    approve_allocation,
    close_round,
    create_event_with_locked_lanes,
    create_qualified_carrier,
    get_success_data,
    invite_and_accept,
    list_allocations,
    list_contracts,
    open_round,
    read_allocation,
    read_event,
    run_optimization,
    setup_closed_round_with_bid,
    setup_published_routing_guide,
    validate_error,
    validate_success,
)

# The lane plans 550 loads; the only bid commits 300 of them.
LANE_PLAN_LOADS = 550
UNDER_COMMITTED_LOADS = 300
COVERAGE_ACHIEVED_PCT = 54.55

# The unreachable and the reachable coverage floor for the same scenario.
UNREACHABLE_COVERAGE_FLOOR_PCT = 100.00
REACHABLE_COVERAGE_FLOOR_PCT = 50.00

# The diversity floor the event demands, and the two classifications tested.
DIVERSITY_FLOOR_PCT = 50.00
NON_DIVERSE_CLASSIFICATION = "NONE"
DIVERSE_CLASSIFICATION = "MWBE"


def _publish(run_id):
    """Attempts to publish a routing guide without asserting the outcome."""
    return api_client.publish_routing_guide(run_id, ANALYST)


def _commit(event_id):
    """Attempts the award commit without asserting the outcome."""
    return api_client.award_bid_event(event_id, CATEGORY_MANAGER)


def _read_run(run_id):
    return get_success_data(api_client.get_optimization_run(run_id, ANALYST))


def _under_covered_run(coverage_floor_pct):
    """A COMPLETED run covering 300 of the lane's 550 loads."""
    ctx = setup_closed_round_with_bid(
        bid_overrides={"committed_volume_loads": UNDER_COMMITTED_LOADS}
    )
    assert ctx["lane"]["annual_volume_loads"] == LANE_PLAN_LOADS
    ctx["run"] = run_optimization(
        ctx["event"]["id"], min_capacity_coverage_pct=coverage_floor_pct
    )
    return ctx


def _infeasible_run():
    """A FAILED run: the round closed without a single submitted bid."""
    carrier = create_qualified_carrier()
    event, lanes = create_event_with_locked_lanes()
    invite_and_accept(event["id"], carrier["id"])
    bid_round = open_round(event["id"])
    closed = close_round(bid_round["id"])
    assert closed["submitted_bid_count"] == 0
    run = run_optimization(event["id"])
    return {"event": event, "lanes": lanes, "carrier": carrier, "run": run}


def _award_pending_event(diversity_classification):
    """An AWARDING event with one APPROVED allocation and a 50.00 diversity floor."""
    ctx = setup_published_routing_guide(
        carrier_overrides={"diversity_classification": diversity_classification},
        diversity_min_pct=DIVERSITY_FLOOR_PCT,
    )
    ctx["allocation"] = approve_allocation(ctx["allocation"]["id"])
    ctx["event"] = read_event(ctx["event"]["id"])
    return ctx


class TestCoverageIsJudgedAtPublication:
    """The floor is the run's own parameter, and the refusal writes nothing."""

    def test_a_scenario_below_its_own_coverage_floor_cannot_be_published(self):
        """54.55 against a floor of 100.00 is a 422, not a partial guide.

        PRD §3.6: "The run's `coverage_pct` must be greater than or equal to its own
        `min_capacity_coverage_pct`, otherwise `ERR_COVERAGE_BELOW_MINIMUM` (422) — a
        scenario that leaves too much volume uncovered is not a routing guide."
        PRD §2.9: "a run's `coverage_pct` must reach its minimum capacity coverage before
        its guide may be published (`ERR_COVERAGE_BELOW_MINIMUM`)"
        PRD §3.6: "The run moves from `COMPLETED` to `PUBLISHED`, `published_at` is set
        to the logical clock, the event moves from `OPTIMIZING` to `AWARDING`, and the
        event's `version` increases by one."

        Design: Corner/errors/portfolio_level_refusals_fire_at_publish_and_at_award
        """
        ctx = _under_covered_run(UNREACHABLE_COVERAGE_FLOOR_PCT)
        run = ctx["run"]
        assert run["status"] == "COMPLETED"
        assert float(run["coverage_pct"]) == COVERAGE_ACHIEVED_PCT
        assert float(run["min_capacity_coverage_pct"]) == UNREACHABLE_COVERAGE_FLOOR_PCT

        refused = _publish(run["id"])
        validate_error(refused, "ERR_COVERAGE_BELOW_MINIMUM", 422)

        unchanged = _read_run(run["id"])
        assert unchanged["status"] == "COMPLETED", "the refused run is still publishable"
        assert unchanged["published_at"] is None
        assert list_allocations(lane_id=ctx["lane"]["id"]) == [], (
            "no allocation row may survive a portfolio refusal"
        )
        event = read_event(ctx["event"]["id"])
        assert event["status"] == "OPTIMIZING"
        assert float(event["coverage_pct"]) == 0.00

    def test_the_same_scenario_publishes_once_the_floor_is_reachable(self):
        """Only the run's own parameter changed, so the gate was the parameter.

        PRD §3.6: "may optionally override three constraints for this scenario only —
        `max_carriers_per_lane` between 1 and 3, `diversity_min_pct`, and
        `min_capacity_coverage_pct`, which defaults to `90.00`"
        PRD §3.6: "Publication materialises the picks. An `AwardAllocation` row is
        created for each pick with `status` `PROPOSED`, carrying its `routing_position`,
        `allocated_volume_loads`, `allocated_pct` and `allocated_cost_usd`"

        Design: Corner/errors/portfolio_level_refusals_fire_at_publish_and_at_award
        """
        ctx = _under_covered_run(UNREACHABLE_COVERAGE_FLOOR_PCT)
        validate_error(_publish(ctx["run"]["id"]), "ERR_COVERAGE_BELOW_MINIMUM", 422)

        relaxed = run_optimization(
            ctx["event"]["id"],
            scenario_label="RELAXED",
            min_capacity_coverage_pct=REACHABLE_COVERAGE_FLOOR_PCT,
        )
        assert float(relaxed["coverage_pct"]) == COVERAGE_ACHIEVED_PCT
        assert _read_run(ctx["run"]["id"])["status"] == "SUPERSEDED"

        published = validate_success(_publish(relaxed["id"]))
        assert published["status"] == "PUBLISHED"

        allocations = list_allocations(lane_id=ctx["lane"]["id"])
        assert len(allocations) == 1
        assert allocations[0]["status"] == "PROPOSED"
        assert allocations[0]["allocated_volume_loads"] == UNDER_COMMITTED_LOADS
        assert read_event(ctx["event"]["id"])["status"] == "AWARDING"


class TestAFailedRunIsNeverPublishable:
    """`FAILED` is terminal, so retrying the publication changes nothing."""

    def test_a_run_with_no_feasible_primary_is_refused_and_stays_failed(self):
        """The diagnosis is recorded; the guide never comes into existence.

        PRD §3.6: "When `infeasible_lane_ids` covers every in-scope lane, the run is
        created with `status` `FAILED`, `coverage_pct` `0.00`, `total_cost_usd` `0.00`
        and `objective_score` `0.00`. A failed run records the diagnosis without
        pretending a routing guide exists."
        PRD §3.6: "And a run whose `status` is `FAILED` can never be published, the
        attempt being rejected with `ERR_NO_FEASIBLE_ALLOCATION` (422)."
        PRD §3.6: "A run's `status` is `COMPLETED` on creation, or `FAILED` when no lane
        yielded a feasible primary; from `COMPLETED` it may move to `PUBLISHED`, and from
        either `COMPLETED` or `PUBLISHED` it may be moved to the terminal `SUPERSEDED` by
        a later run. `FAILED` is also terminal."

        Design: Corner/errors/portfolio_level_refusals_fire_at_publish_and_at_award
        """
        ctx = _infeasible_run()
        run = ctx["run"]
        assert run["status"] == "FAILED"
        assert float(run["coverage_pct"]) == 0.00
        assert float(run["total_cost_usd"]) == 0.00
        assert float(run["objective_score"]) == 0.00
        assert ctx["lanes"][0]["id"] in run["infeasible_lane_ids"]

        validate_error(_publish(run["id"]), "ERR_NO_FEASIBLE_ALLOCATION", 422)
        validate_error(_publish(run["id"]), "ERR_NO_FEASIBLE_ALLOCATION", 422)

        assert _read_run(run["id"])["status"] == "FAILED"
        assert _read_run(run["id"])["published_at"] is None
        assert list_allocations(lane_id=ctx["lanes"][0]["id"]) == []
        assert read_event(ctx["event"]["id"])["status"] == "OPTIMIZING"


class TestDiversityIsJudgedOnlyAtTheAward:
    """The guide published happily; it is the commit that measures the portfolio."""

    def test_an_all_non_diverse_award_is_refused_at_the_commit(self):
        """The five-link cascade never starts: no contract row is minted.

        PRD §3.7: "The event's `diversity_pct` must be greater than or equal to its
        `diversity_min_pct`, otherwise `ERR_DIVERSITY_MINIMUM_NOT_MET` (422)."
        PRD §3.3: "`diversity_pct` is `0.00` when that allocated sum is zero; otherwise
        it is the portion of that same allocated sum belonging to carriers whose
        `diversity_classification` is anything other than `NONE`, multiplied by `100.00`,
        divided by the total allocated sum, and rounded to 2 decimal places."
        PRD §3.7: "One contract is created for each distinct pairing of `bid_event_id`
        and `carrier_id` appearing among those executed allocations — one contract per
        carrier per event, however many lanes that carrier won."

        Design: Corner/errors/portfolio_level_refusals_fire_at_publish_and_at_award
        """
        ctx = _award_pending_event(NON_DIVERSE_CLASSIFICATION)
        event = ctx["event"]
        assert event["status"] == "AWARDING"
        assert float(event["diversity_pct"]) == 0.00
        assert float(event["coverage_pct"]) == 100.00
        assert ctx["carrier"]["diversity_classification"] == NON_DIVERSE_CLASSIFICATION

        validate_error(_commit(event["id"]), "ERR_DIVERSITY_MINIMUM_NOT_MET", 422)

        after = read_event(event["id"])
        assert after["status"] == "AWARDING", "the refused commit does not award the event"
        assert after["awarded_at"] is None
        assert read_allocation(ctx["allocation"]["id"])["status"] == "APPROVED"
        assert list_contracts(bid_event_id=event["id"]) == []

    def test_the_identical_award_commits_when_the_holder_is_diverse(self):
        """Same volume, same floor: only the carrier's classification moved.

        PRD §3.3: "Both percentages are volume-weighted, not headcount-weighted: one
        diverse carrier holding half the volume yields `50.00`, not a fraction based on
        how many carriers were used."
        PRD §3.7: "The event moves from `AWARDING` to `AWARDED`, `awarded_at` is set to
        the logical clock, and its `award_cost_usd` and `savings_pct` are recomputed per
        §3.3."

        Design: Corner/errors/portfolio_level_refusals_fire_at_publish_and_at_award
        """
        ctx = _award_pending_event(DIVERSE_CLASSIFICATION)
        event = ctx["event"]
        assert ctx["carrier"]["diversity_classification"] == DIVERSE_CLASSIFICATION
        assert float(event["diversity_pct"]) == 100.00
        assert float(event["diversity_min_pct"]) == DIVERSITY_FLOOR_PCT

        awarded = validate_success(_commit(event["id"]))
        assert awarded["status"] == "AWARDED"
        assert awarded["awarded_at"] is not None
        assert read_allocation(ctx["allocation"]["id"])["status"] == "EXECUTED"
        assert len(list_contracts(bid_event_id=event["id"])) == 1
