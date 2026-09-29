"""Three write endpoints whose whole job is to rewrite rows they do not name.

Creating a second optimisation run rewrites the entire scenario history of an
event and hands volume back to the lanes that had reserved it. Staging a rate
record is the only four-way link in the system, and it re-derives the contract's
money. Taking a rate live is gated on the logical clock falling inside the
record's own half-open interval, and the refusal must leave the four-link
cutover completely unwritten.
"""

from test_helpers import (
    ANALYST,
    CLOCK_GO_LIVE,
    CONTRACT_ADMIN,
    CONTRACT_EFFECTIVE_FROM,
    DEFAULT_CLOCK,
    NON_EXISTENT_UUID,
    api_client,
    approve_allocation,
    assert_same_instant,
    close_round,
    create_event_with_locked_lanes,
    create_qualified_carrier,
    fully_sign_contract,
    get_success_data,
    invite_and_accept,
    list_allocations,
    load_rate_record,
    open_round,
    optimization_run_payload,
    publish_guide,
    rate_record_payload,
    read_allocation,
    read_contract,
    read_event,
    read_lane,
    read_rate_record,
    run_optimization,
    second_carrier_overrides,
    set_clock,
    setup_awarded_event,
    setup_staged_rate_record,
    submit_bid,
    validate_error,
    validate_paginated,
    validate_success,
)

# Two bids on one 550-load lane: 300 loads at 2.1152 and 250 at 2.2000. Bids are
# ordered by `cost_rank_score`, a service-adjusted *annual* cost, so the 250-load
# bid wins PRIMARY at 2681.58 x 250 = 670395.00 even though its per-mile rate is
# dearer than the 300-load bid's 2584.31 x 300 = 775293.00. The two-seat waterfall
# then hands the 300 loads that remain of the plan to BACKUP_1.
BULK_BID = {"rate_per_mile": 2.1152, "committed_volume_loads": 300}
LEAN_BID = {"rate_per_mile": 2.2000, "committed_volume_loads": 250}
PRIMARY_GRANT_LOADS = 250
BACKUP_GRANT_LOADS = 300
LANE_PLAN_LOADS = 550
PRIMARY_ALLOCATED_PCT = 45.45
COVERAGE_AFTER_APPROVAL_PCT = 45.45
VOLUME_AFTER_APPROVAL_LOADS = 300
TWO_SEAT_LIMIT = 2

# The staged rate: 1147 miles x 2.0000 all-in x 550 loads, then the contract's
# 1.5% volume discount and the 2.0% accessorial allowance on the subtotal.
RECORD_COMMITTED_VALUE_USD = 1261700.00
CONTRACT_BASE_VALUE_USD = 1261700.00
VOLUME_DISCOUNT_PCT = 0.015
VOLUME_DISCOUNT_USD = 18925.50
ACCESSORIAL_ALLOWANCE_PCT = 0.020
ACCESSORIAL_ALLOWANCE_USD = 24855.49
CONTRACT_TOTAL_VALUE_USD = 1267629.99

# A record whose interval closes early, so the exclusive upper bound is reachable
# while the carrier's certificate is still valid.
EARLY_WINDOW_CLOSE = "2026-10-01T00:00:00Z"
INSIDE_EARLY_WINDOW = "2026-09-15T00:00:00Z"


def _list_allocation_page(**params):
    """Reads the allocation collection and returns its (rows, meta) pair."""
    return validate_paginated(api_client.list_award_allocations(ANALYST, params or None))


def _read_run(run_id):
    return get_success_data(api_client.get_optimization_run(run_id, ANALYST))


def _create_run(event_id, version, **overrides):
    """Attempts a scenario run under an explicit version guard."""
    return api_client.create_optimization_run(
        optimization_run_payload(event_id, version, **overrides), ANALYST
    )


def _stage(contract_id, lane_id, carrier_id, allocation_id, **overrides):
    """Attempts to stage a rate record without asserting the outcome."""
    return api_client.create_rate_record(
        contract_id,
        rate_record_payload(lane_id, carrier_id, allocation_id, **overrides),
        CONTRACT_ADMIN,
    )


def _go_live(rate_record_id):
    """Attempts the cutover without asserting the outcome."""
    return api_client.go_live_rate_record(rate_record_id, CONTRACT_ADMIN)


def _two_seat_guide_with_one_approval():
    """A published two-seat routing guide whose PRIMARY allocation is approved."""
    set_clock(DEFAULT_CLOCK)
    bulk_carrier = create_qualified_carrier()
    lean_carrier = create_qualified_carrier(
        carrier_overrides=second_carrier_overrides()
    )
    event, lanes = create_event_with_locked_lanes()
    invite_and_accept(event["id"], bulk_carrier["id"])
    invite_and_accept(event["id"], lean_carrier["id"])
    bid_round = open_round(event["id"])
    submit_bid(bid_round["id"], lanes[0]["id"], bulk_carrier["id"], **BULK_BID)
    submit_bid(bid_round["id"], lanes[0]["id"], lean_carrier["id"], **LEAN_BID)
    close_round(bid_round["id"])
    run = run_optimization(event["id"], max_carriers_per_lane=TWO_SEAT_LIMIT)
    publish_guide(run["id"])
    allocations = list_allocations(lane_id=lanes[0]["id"])
    by_position = {allocation["routing_position"]: allocation for allocation in allocations}
    approve_allocation(by_position["PRIMARY"]["id"])
    return {
        "event": read_event(event["id"]),
        "lane": lanes[0],
        "first_run": run,
        "primary": by_position["PRIMARY"],
        "backup": by_position["BACKUP_1"],
    }


def _loaded_record(**rate_overrides):
    """An awarded, fully signed contract holding one LOADED rate record."""
    ctx = setup_staged_rate_record(rate_overrides=rate_overrides or None)
    ctx["contract"] = fully_sign_contract(ctx["contract"]["id"], ctx["carrier"]["id"])
    ctx["rate_record"] = load_rate_record(ctx["rate_record"]["id"])
    return ctx


class TestASecondRunRewritesTheScenarioHistory:
    """One call supersedes every earlier run and every allocation beneath it."""

    def test_the_new_run_supersedes_the_earlier_run_and_all_of_its_allocations(self):
        """Both rows go: the approved one and the never-approved one alike.

        PRD §3.6: "Creating a run first **supersedes the scenario history**, in three
        linked steps. Every earlier run of the same event whose `status` is `COMPLETED`
        or `PUBLISHED` moves to `SUPERSEDED`."
        PRD §3.6: "Every award allocation belonging to those superseded runs whose
        `status` is `PROPOSED` or `APPROVED` moves to `SUPERSEDED`."
        PRD §3.6: "The new run is then created, the allocation waterfall and the
        objective score are evaluated, the event moves to `OPTIMIZING`, and the event's
        `version` increases by one."
        PRD §3.6: "A run may be created while the event's `status` is `ROUND_CLOSED`,
        `OPTIMIZING` or `AWARDING`"

        Design: Corner/endpoints/a_second_optimization_run_supersedes_the_first_and_credits_every_volume_back
        """
        ctx = _two_seat_guide_with_one_approval()
        before = read_event(ctx["event"]["id"])
        assert before["status"] == "AWARDING"
        assert _read_run(ctx["first_run"]["id"])["status"] == "PUBLISHED"

        second = validate_success(
            _create_run(
                before["id"],
                before["version"],
                scenario_label="REOPTIMIZE_AFTER_REJECTS",
                max_carriers_per_lane=TWO_SEAT_LIMIT,
            ),
            201,
        )
        assert second["status"] == "COMPLETED"

        after = read_event(ctx["event"]["id"])
        assert after["status"] == "OPTIMIZING"
        assert after["version"] == before["version"] + 1
        assert _read_run(ctx["first_run"]["id"])["status"] == "SUPERSEDED"

        rows, meta = _list_allocation_page(optimization_run_id=ctx["first_run"]["id"])
        assert meta["total_count"] == 2
        assert {row["status"] for row in rows} == {"SUPERSEDED"}
        assert read_allocation(ctx["primary"]["id"])["status"] == "SUPERSEDED"
        assert read_allocation(ctx["backup"]["id"])["status"] == "SUPERSEDED"

    def test_only_the_approved_allocation_credits_its_volume_back_to_the_lane(self):
        """The ledger lands exactly on 550: the proposed backup credited nothing.

        PRD §3.6: "And for each of those that was `APPROVED` — and only those, since a
        `PROPOSED` allocation was never holding volume — its `allocated_volume_loads` is
        credited back to its lane's `unallocated_volume_loads`, restoring the
        conservation identity of §2.12 exactly."
        PRD §3.7: "The lane's `unallocated_volume_loads` is reduced by the allocation's
        `allocated_volume_loads`, and the lane's `awarded_coverage_pct` is recomputed as
        `annual_volume_loads` minus `unallocated_volume_loads`, multiplied by `100.00`,
        divided by `annual_volume_loads`, and rounded to 2 decimal places."
        PRD §3.6: "The waterfall itself writes nothing to the lane: it never sets
        `unallocated_volume_loads` and never sets `awarded_coverage_pct`."
        PRD §3.6: "Publication materialises the picks. An `AwardAllocation` row is
        created for each pick with `status` `PROPOSED`"

        Design: Corner/endpoints/a_second_optimization_run_supersedes_the_first_and_credits_every_volume_back
        """
        ctx = _two_seat_guide_with_one_approval()
        assert ctx["primary"]["allocated_volume_loads"] == PRIMARY_GRANT_LOADS
        assert ctx["backup"]["allocated_volume_loads"] == BACKUP_GRANT_LOADS
        reserved = read_lane(ctx["lane"]["id"])
        assert reserved["unallocated_volume_loads"] == VOLUME_AFTER_APPROVAL_LOADS
        assert float(reserved["awarded_coverage_pct"]) == PRIMARY_ALLOCATED_PCT
        assert float(ctx["event"]["coverage_pct"]) == COVERAGE_AFTER_APPROVAL_PCT

        event = read_event(ctx["event"]["id"])
        second = validate_success(
            _create_run(
                event["id"],
                event["version"],
                scenario_label="REOPTIMIZE_AFTER_REJECTS",
                max_carriers_per_lane=TWO_SEAT_LIMIT,
            ),
            201,
        )

        credited = read_lane(ctx["lane"]["id"])
        assert credited["unallocated_volume_loads"] == LANE_PLAN_LOADS, (
            "only the approved 250 loads return; the proposed 300 never left"
        )
        assert float(credited["awarded_coverage_pct"]) == 0.00

        rolled_up = read_event(ctx["event"]["id"])
        assert float(rolled_up["coverage_pct"]) == 0.00
        assert float(rolled_up["diversity_pct"]) == 0.00

        _rows, meta = _list_allocation_page(optimization_run_id=second["id"])
        assert meta["total_count"] == 0, (
            "a fresh run holds picks, not allocations, until its guide is published"
        )


class TestStagingARateRecordLinksFourEntities:
    """The record names a lane, a carrier and an allocation while living under a contract."""

    def test_a_dangling_allocation_reference_leaves_the_contract_untouched(self):
        """The body foreign key is resolved before anything is written.

        PRD §2.9: "**Body foreign keys.** Every foreign key supplied in the request
        **body** must resolve to an existing row, checked in the order the fields are
        declared for that endpoint, each raising that entity's own 404 from the list in
        rung 3. This applies to lane creation, invitation creation, lane-bid submission,
        optimization-run creation, rate-record staging, mini-bid creation and scorecard
        drafting."
        PRD §2.9: "an optimization run `ERR_OPTIMIZATION_RUN_NOT_FOUND`, an award
        allocation `ERR_AWARD_ALLOCATION_NOT_FOUND`, a contract `ERR_CONTRACT_NOT_FOUND`,
        a rate record `ERR_RATE_RECORD_NOT_FOUND`"
        PRD §3.8: "The contract's `rate_record_count` is recomputed, its
        `rate_load_status` moves from `NOT_STAGED` to `STAGED`, its committed value is
        re-evaluated, and its `version` increases by one."

        Design: Corner/endpoints/staging_a_rate_record_links_contract_lane_carrier_and_allocation
        """
        ctx = setup_awarded_event()
        before = read_contract(ctx["contract"]["id"])
        assert before["rate_record_count"] == 0
        assert before["rate_load_status"] == "NOT_STAGED"

        validate_error(
            _stage(
                before["id"],
                ctx["lane"]["id"],
                ctx["carrier"]["id"],
                NON_EXISTENT_UUID,
            ),
            "ERR_AWARD_ALLOCATION_NOT_FOUND",
            404,
        )

        untouched = read_contract(before["id"])
        assert untouched["rate_record_count"] == 0
        assert untouched["rate_load_status"] == "NOT_STAGED"
        assert float(untouched["total_committed_value_usd"]) == 0.00
        assert untouched["version"] == before["version"], (
            "a refused stage consumes no contract version"
        )
        _rows, meta = validate_paginated(
            api_client.list_rate_records(CONTRACT_ADMIN, {"contract_id": before["id"]})
        )
        assert meta["total_count"] == 0

    def test_the_accepted_stage_echoes_every_link_and_re_derives_the_money(self):
        """One write, four references and the whole contract money ladder.

        PRD §3.8: "The payload names the `lane_id`, the `carrier_id`, the
        `award_allocation_id` the rate implements, and a `routing_position` that must
        match that allocation's own `routing_position`"
        PRD §3.8: "The record is created with `status` `STAGED`; `acceptance_pct`
        `100.00` and `rejection_pct` `0.00`, the neutral starting position of a lane that
        has never been tendered; `tender_count` `0`; `superseded_by_rate_record_id` null;
        and `loaded_at` and `live_at` null."
        PRD §3.8: "Multiply the lane's `mileage` by that effective rate and round to 2
        decimal places; multiply that already-rounded figure by the record's
        `committed_volume_loads` and round to 2 decimal places. That is the record's
        `committed_value_usd`."
        PRD §3.8: "The contract's `volume_discount_pct` is selected from
        `base_committed_value_usd`: below `500000` it is `0.000`; from `500000` up to but
        not including `1500000` it is `0.015`; at `1500000` and above it is `0.025`."
        PRD §3.8: "The contract's `accessorial_allowance_pct` is selected from the
        **post-discount subtotal**, not from the base: below `400000` it is `0.000`; from
        `400000` up to but not including `1200000` it is `0.010`; at `1200000` and above
        it is `0.020`."

        Design: Corner/endpoints/staging_a_rate_record_links_contract_lane_carrier_and_allocation
        """
        ctx = setup_awarded_event()
        before = read_contract(ctx["contract"]["id"])

        staged = validate_success(
            _stage(
                before["id"],
                ctx["lane"]["id"],
                ctx["carrier"]["id"],
                ctx["allocation"]["id"],
            ),
            201,
        )
        assert staged["status"] == "STAGED"
        assert staged["contract_id"] == before["id"]
        assert staged["lane_id"] == ctx["lane"]["id"]
        assert staged["carrier_id"] == ctx["carrier"]["id"]
        assert staged["award_allocation_id"] == ctx["allocation"]["id"]
        assert staged["routing_position"] == ctx["allocation"]["routing_position"]
        assert float(staged["committed_value_usd"]) == RECORD_COMMITTED_VALUE_USD
        assert staged["tender_count"] == 0
        assert float(staged["acceptance_pct"]) == 100.00
        assert float(staged["rejection_pct"]) == 0.00
        assert staged["superseded_by_rate_record_id"] is None
        assert staged["loaded_at"] is None
        assert staged["live_at"] is None

        after = read_contract(before["id"])
        assert after["rate_record_count"] == 1
        assert after["rate_load_status"] == "STAGED"
        assert float(after["base_committed_value_usd"]) == CONTRACT_BASE_VALUE_USD
        assert float(after["volume_discount_pct"]) == VOLUME_DISCOUNT_PCT
        assert float(after["volume_discount_usd"]) == VOLUME_DISCOUNT_USD
        assert float(after["accessorial_allowance_pct"]) == ACCESSORIAL_ALLOWANCE_PCT
        assert float(after["accessorial_allowance_usd"]) == ACCESSORIAL_ALLOWANCE_USD
        assert float(after["total_committed_value_usd"]) == CONTRACT_TOTAL_VALUE_USD
        assert after["version"] == before["version"] + 1

        by_allocation, allocation_meta = validate_paginated(
            api_client.list_rate_records(
                CONTRACT_ADMIN, {"award_allocation_id": ctx["allocation"]["id"]}
            )
        )
        assert allocation_meta["total_count"] == 1
        assert by_allocation[0]["id"] == staged["id"]
        by_contract, contract_meta = validate_paginated(
            api_client.list_rate_records(CONTRACT_ADMIN, {"contract_id": before["id"]})
        )
        assert contract_meta["total_count"] == 1
        assert by_contract[0]["id"] == staged["id"]


class TestGoLiveIsGatedOnTheHalfOpenEffectiveInterval:
    """The clock decides, not the request order, and the bounds are asymmetric."""

    def test_the_cutover_is_refused_before_effective_from_and_admitted_exactly_at_it(self):
        """One refusal at 2026-08-01, one success at exactly 2026-09-01.

        PRD §3.8: "The current logical clock instant must fall inside the record's own
        half-open effective interval, at or after `effective_from` and strictly before
        `effective_to`, otherwise `ERR_RATE_NOT_IN_EFFECTIVE_WINDOW` (409); a rate cannot
        go live before it begins or after it has expired."
        PRD §3.8: "The record moves from `LOADED` to `LIVE` and `live_at` is set to the
        logical clock."
        PRD §3.8: "The award allocation the record implements moves from `EXECUTED` to
        `ACTIVE`, and the carrier's `active_primary_lane_count` is recomputed."
        PRD §3.8: "On the **first** rate record of the whole event to go live, the event
        moves from `AWARDED` to the terminal `LIVE` and its `coverage_pct` is recomputed
        over the allocations now `ACTIVE`."

        Design: Corner/endpoints/go_live_is_refused_before_the_effective_window_opens
        """
        ctx = _loaded_record()
        assert ctx["rate_record"]["status"] == "LOADED"
        assert_same_instant(
            ctx["rate_record"]["effective_from"], CONTRACT_EFFECTIVE_FROM
        )

        validate_error(
            _go_live(ctx["rate_record"]["id"]),
            "ERR_RATE_NOT_IN_EFFECTIVE_WINDOW",
            409,
        )

        refused = read_rate_record(ctx["rate_record"]["id"])
        assert refused["status"] == "LOADED"
        assert refused["live_at"] is None
        assert read_allocation(ctx["allocation"]["id"])["status"] == "EXECUTED"
        assert read_contract(ctx["contract"]["id"])["rate_load_status"] == "LOADED"
        assert read_event(ctx["event"]["id"])["status"] == "AWARDED"

        set_clock(CLOCK_GO_LIVE)
        live = validate_success(_go_live(ctx["rate_record"]["id"]))
        assert live["status"] == "LIVE"
        assert_same_instant(live["live_at"], CLOCK_GO_LIVE, "live_at")
        assert read_allocation(ctx["allocation"]["id"])["status"] == "ACTIVE"
        assert read_contract(ctx["contract"]["id"])["rate_load_status"] == "LIVE"
        assert read_event(ctx["event"]["id"])["status"] == "LIVE"

    def test_the_upper_bound_of_the_interval_is_exclusive(self):
        """At `effective_to` the same record is refused; one instant inside it is not.

        PRD §3.8: "Intervals are **half-open**, running from `effective_from` inclusive
        to `effective_to` exclusive, so two records where one's `effective_to` is exactly
        the other's `effective_from` are adjacent and do **not** overlap"
        PRD §3.8: "a rate cannot go live before it begins or after it has expired"
        PRD §2.5: "Every instant the system writes or compares is read from a
        server-side **logical clock**, never from the host wall clock."

        Design: Corner/endpoints/go_live_is_refused_before_the_effective_window_opens
        """
        ctx = _loaded_record(effective_to=EARLY_WINDOW_CLOSE)
        assert_same_instant(ctx["rate_record"]["effective_to"], EARLY_WINDOW_CLOSE)

        set_clock(EARLY_WINDOW_CLOSE)
        validate_error(
            _go_live(ctx["rate_record"]["id"]),
            "ERR_RATE_NOT_IN_EFFECTIVE_WINDOW",
            409,
        )
        assert read_rate_record(ctx["rate_record"]["id"])["status"] == "LOADED"

        set_clock(INSIDE_EARLY_WINDOW)
        live = validate_success(_go_live(ctx["rate_record"]["id"]))
        assert live["status"] == "LIVE"
        assert_same_instant(live["live_at"], INSIDE_EARLY_WINDOW, "live_at")
