"""The two optimistic-concurrency guards, and what a version counter counts.

Only two writes in this system carry a version field, and each guards a
different kind of destruction: an optimisation run wipes an earlier scenario's
allocations, and a mini-bid apply layers a second amendment onto a contract's
committed value. Both are equality checks, both refuse without consuming a
version, and both sit one rung above the state checks they precede. The last
class pins down the counter itself: a child write moves the parent, a read never
does, and a refused write consumes nothing.
"""

from test_helpers import (
    ANALYST,
    CATEGORY_MANAGER,
    CONTRACT_ADMIN,
    CLOCK_GO_LIVE,
    CLOCK_MINI_BID_APPLY,
    CONTRACT_EFFECTIVE_TO,
    DEFAULT_CLOCK,
    add_lane,
    api_client,
    assert_same_instant,
    create_bid_event,
    create_carrier,
    fully_sign_contract,
    get_success_data,
    go_live,
    lane_payload,
    load_rate_record,
    mini_bid_apply_payload,
    optimization_run_payload,
    propose_mini_bid_rate,
    read_contract,
    read_event,
    read_mini_bid,
    read_rate_record,
    request_mini_bid,
    set_clock,
    setup_closed_round_with_bid,
    stage_rate_record,
    two_lane_awarded_event,
    validate_error,
    validate_paginated,
    validate_success,
)

# Scenario labels, so the runs are distinguishable in the listing.
FIRST_SCENARIO = "BASE"
REPLAYED_SCENARIO = "REPLAY_WITH_OLD_VERSION"
AHEAD_SCENARIO = "AHEAD_OF_THE_SERVER"
SECOND_SCENARIO = "SECOND_SCENARIO"

# The mini-bid proposal: 2.1000 against a stored 2.0000 is +5.00%, inside the
# 12.00 adjustment cap and above the event's 1.5000 floor.
PROPOSED_RATE_PER_MILE = 2.1000

# The replacement interval, opening a month into the contract window.
AMENDMENT_EFFECTIVE_FROM = "2026-10-01T00:00:00Z"

VERSIONED_LANE_CODE = "L-VER"


def _create_run(event_id, expected_version, scenario_label):
    """Attempts an optimisation run under the version guard, without asserting."""
    return api_client.create_optimization_run(
        optimization_run_payload(
            event_id, expected_version, scenario_label=scenario_label
        ),
        ANALYST,
    )


def _read_run(run_id):
    return get_success_data(api_client.get_optimization_run(run_id, ANALYST))


def _list_runs(event_id):
    return api_client.list_event_optimization_runs(event_id, ANALYST)


def _apply(mini_bid_id, expected_contract_version):
    """Attempts a mini-bid apply under the version guard, without asserting."""
    return api_client.apply_mini_bid(
        mini_bid_id,
        mini_bid_apply_payload(
            expected_contract_version,
            effective_from=AMENDMENT_EFFECTIVE_FROM,
            effective_to=CONTRACT_EFFECTIVE_TO,
        ),
        CONTRACT_ADMIN,
    )


def _closed_round_event():
    """A two-lane event whose only round is closed, ready to be optimised."""
    ctx = setup_closed_round_with_bid()
    ctx["event"] = read_event(ctx["event"]["id"])
    return ctx


def _one_contract_with_two_open_mini_bids():
    """One executed contract, two LIVE rates on two lanes, one mini-bid per lane.

    Both windows are open at `CLOCK_MINI_BID_APPLY`, and both mini-bids carry an
    accepted proposal, so either lane's amendment could be applied first.
    """
    ctx = two_lane_awarded_event()
    carrier_id = ctx["carrier"]["id"]
    contract_id = ctx["contract"]["id"]
    fully_sign_contract(contract_id, carrier_id)

    by_lane = {
        allocation["lane_id"]: allocation for allocation in ctx["allocations"]
    }
    staged = []
    for lane in ctx["lanes"]:
        allocation = by_lane[lane["id"]]
        staged.append(
            stage_rate_record(
                contract_id,
                lane["id"],
                carrier_id,
                allocation["id"],
                committed_volume_loads=allocation["allocated_volume_loads"],
            )
        )
    for record in staged:
        load_rate_record(record["id"])

    set_clock(CLOCK_GO_LIVE)
    ctx["rate_records"] = [go_live(record["id"]) for record in staged]

    requested = [
        request_mini_bid(ctx["event"]["id"], lane["id"], record["id"])
        for lane, record in zip(ctx["lanes"], ctx["rate_records"])
    ]
    set_clock(CLOCK_MINI_BID_APPLY)
    ctx["mini_bids"] = [
        propose_mini_bid_rate(
            mini_bid["id"],
            carrier_id,
            proposed_rate_per_mile=PROPOSED_RATE_PER_MILE,
        )
        for mini_bid in requested
    ]
    ctx["contract"] = read_contract(contract_id)
    return ctx


class TestTheEventVersionGuardsTheScenarioSupersede:
    """A replayed run would discard a scenario the client never read."""

    def test_the_replayed_run_is_refused_and_bumps_nothing(self):
        """The first run consumed the version, so the identical retry is stale.

        PRD §2.8: "Creating a run legitimately supersedes every earlier
        `COMPLETED` or `PUBLISHED` run of that event and releases the lane volume that
        the earlier run's approved allocations were holding, so a creation carrying an
        out-of-date view of the event would discard scenario state the client never saw."
        PRD §2.8: "If `expected_bid_event_version` does not equal the bid event's
        current `version`, the request is rejected with `ERR_STALE_BID_EVENT_VERSION`
        (HTTP 412) and nothing is created."
        PRD §3.6: "The new run is then created, the allocation waterfall and the
        objective score are evaluated, the event moves to `OPTIMIZING`, and the event's
        `version` increases by one."

        Design: Corner/cross_cutting_complexity_layers/stale_bid_event_version_blocks_a_second_optimization_run
        """
        ctx = _closed_round_event()
        event_id = ctx["event"]["id"]
        assert ctx["event"]["status"] == "ROUND_CLOSED"
        read_version = ctx["event"]["version"]

        first = validate_success(
            _create_run(event_id, read_version, FIRST_SCENARIO), 201
        )
        assert first["status"] == "COMPLETED"

        optimizing = read_event(event_id)
        assert optimizing["version"] == read_version + 1
        assert optimizing["status"] == "OPTIMIZING"

        replay = _create_run(event_id, read_version, REPLAYED_SCENARIO)
        validate_error(replay, "ERR_STALE_BID_EVENT_VERSION", 412)

        assert _read_run(first["id"])["status"] == "COMPLETED", (
            "a refused run may not supersede the scenario it could not read"
        )
        unmoved = read_event(event_id)
        assert unmoved["version"] == optimizing["version"], (
            "a rejected version guard consumes no version"
        )
        assert unmoved["status"] == "OPTIMIZING"

        rows, meta = validate_paginated(_list_runs(event_id))
        assert meta["total_count"] == 1
        assert [row["scenario_label"] for row in rows] == [FIRST_SCENARIO]

    def test_the_guard_is_an_equality_check_and_not_a_lower_bound(self):
        """A version ahead of the server is refused with the same identifier.

        PRD §2.9: "**Version guard.** The supplied `expected_bid_event_version` or
        `expected_contract_version` equals the parent's current `version`, otherwise
        `ERR_STALE_BID_EVENT_VERSION` or `ERR_STALE_CONTRACT_VERSION` (412) as described
        in §2.8."
        PRD §3.6: "Every earlier run of the same event whose `status` is `COMPLETED` or
        `PUBLISHED` moves to `SUPERSEDED`."
        PRD §3.6: "A run's `status` is `COMPLETED` on creation, or `FAILED` when no lane
        yielded a feasible primary; from `COMPLETED` it may move to `PUBLISHED`, and from
        either `COMPLETED` or `PUBLISHED` it may be moved to the terminal `SUPERSEDED` by
        a later run."

        Design: Corner/cross_cutting_complexity_layers/stale_bid_event_version_blocks_a_second_optimization_run
        """
        ctx = _closed_round_event()
        event_id = ctx["event"]["id"]
        first = validate_success(
            _create_run(event_id, ctx["event"]["version"], FIRST_SCENARIO), 201
        )
        current_version = read_event(event_id)["version"]

        ahead = _create_run(event_id, current_version + 1, AHEAD_SCENARIO)
        validate_error(ahead, "ERR_STALE_BID_EVENT_VERSION", 412)
        assert _read_run(first["id"])["status"] == "COMPLETED"
        assert read_event(event_id)["version"] == current_version

        second = validate_success(
            _create_run(event_id, current_version, SECOND_SCENARIO), 201
        )
        assert second["status"] == "COMPLETED"
        assert _read_run(first["id"])["status"] == "SUPERSEDED", (
            "only the run carrying the version the client read supersedes its predecessor"
        )

        after = read_event(event_id)
        assert after["version"] == current_version + 1
        assert after["status"] == "OPTIMIZING"


class TestTheContractVersionGuardsTheAmendment:
    """Two lanes of one contract, so the second apply must re-read the money."""

    def test_the_second_apply_on_the_stale_version_is_refused_and_moves_nothing(self):
        """The first amendment advanced the contract past what the client read.

        PRD §2.8: "Applying a mini-bid amends the contract's committed value; if another
        mini-bid on a different lane of the same contract has already been applied, the
        contract's `version` has advanced past what the client read, and layering a
        second amendment onto a committed value the client never saw is exactly the
        outcome to prevent."
        PRD §2.8: "A mismatch is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412)."
        PRD §3.9: "The contract's `status` moves from `EXECUTED` to `AMENDED`, its
        `amendment_count` increases by one, its committed value is re-evaluated over the
        new basis — which now excludes the superseded record and includes the replacement
        — and its `version` increases by one."
        PRD §3.9: "The contract's `total_committed_value_usd` is snapshotted into
        `contract_value_before_usd` immediately before the links run, and into
        `contract_value_after_usd` immediately after they complete:"

        Design: Corner/cross_cutting_complexity_layers/stale_contract_version_blocks_a_second_mini_bid_apply
        """
        ctx = _one_contract_with_two_open_mini_bids()
        contract_id = ctx["contract"]["id"]
        read_version = ctx["contract"]["version"]
        value_before = float(ctx["contract"]["total_committed_value_usd"])
        assert ctx["contract"]["status"] == "EXECUTED"
        assert ctx["contract"]["amendment_count"] == 0

        first = validate_success(_apply(ctx["mini_bids"][0]["id"], read_version))
        assert first["status"] == "APPLIED"
        assert_same_instant(first["applied_at"], CLOCK_MINI_BID_APPLY, "applied_at")
        assert float(first["contract_value_before_usd"]) == value_before

        amended = read_contract(contract_id)
        assert amended["status"] == "AMENDED"
        assert amended["amendment_count"] == 1
        assert amended["version"] > read_version
        value_after_first = float(amended["total_committed_value_usd"])
        assert value_after_first > value_before, (
            "the replacement rate is 5.00% above the stored rate, so the basis grows"
        )
        assert float(first["contract_value_after_usd"]) == value_after_first

        stale = _apply(ctx["mini_bids"][1]["id"], read_version)
        validate_error(stale, "ERR_STALE_CONTRACT_VERSION", 412)

        untouched = read_mini_bid(ctx["mini_bids"][1]["id"])
        assert untouched["status"] == "OPEN"
        assert untouched["applied_rate_record_id"] is None
        assert untouched["contract_value_before_usd"] is None
        assert read_rate_record(ctx["rate_records"][1]["id"])["status"] == "LIVE"

        frozen = read_contract(contract_id)
        assert float(frozen["total_committed_value_usd"]) == value_after_first
        assert frozen["amendment_count"] == 1
        assert frozen["version"] == amended["version"], (
            "a refused amendment consumes no contract version"
        )

    def test_the_fresh_version_lands_and_the_guard_outranks_the_state_check(self):
        """Re-reading the contract is the whole fix; then rung 8 beats rung 9.

        PRD §3.9: "A replacement rate record is minted directly in `LIVE` — it does not
        pass through `STAGED` or `LOADED` — carrying `rate_per_mile` set to the
        mini-bid's `proposed_rate_per_mile`, the `effective_from` and `effective_to`
        supplied in the payload, and `lane_id`, `carrier_id`, `routing_position`,
        `award_allocation_id`, `contract_id`, `fuel_surcharge_included` and
        `committed_volume_loads` copied from the record it replaces."
        PRD §3.9: "A contract administrator applies a mini-bid whose `status` is `OPEN`;
        against any other status the attempt is rejected with `ERR_MINI_BID_NOT_OPEN`
        (409)."
        PRD §2.9: "Checks are evaluated in a single fixed ascending order, and **the
        first violated check decides the response** — no later check is evaluated and
        no partial write is retained."

        Design: Corner/cross_cutting_complexity_layers/stale_contract_version_blocks_a_second_mini_bid_apply
        """
        ctx = _one_contract_with_two_open_mini_bids()
        contract_id = ctx["contract"]["id"]
        stale_version = ctx["contract"]["version"]

        first = validate_success(_apply(ctx["mini_bids"][0]["id"], stale_version))
        after_first = read_contract(contract_id)
        value_after_first = float(after_first["total_committed_value_usd"])

        second = validate_success(
            _apply(ctx["mini_bids"][1]["id"], after_first["version"])
        )
        assert second["status"] == "APPLIED"

        both = read_contract(contract_id)
        assert both["amendment_count"] == 2
        assert both["status"] == "AMENDED"
        assert float(both["total_committed_value_usd"]) > value_after_first, (
            "the committed value reflects both amendments, not only the first"
        )
        assert both["version"] > after_first["version"]

        for original, applied in zip(ctx["rate_records"], (first, second)):
            superseded = read_rate_record(original["id"])
            replacement = read_rate_record(applied["applied_rate_record_id"])
            assert superseded["status"] == "SUPERSEDED"
            assert superseded["superseded_by_rate_record_id"] == replacement["id"]
            assert replacement["status"] == "LIVE"
            assert float(replacement["rate_per_mile"]) == PROPOSED_RATE_PER_MILE
            assert replacement["lane_id"] == original["lane_id"]
            assert (
                replacement["committed_volume_loads"]
                == original["committed_volume_loads"]
            )

        # The already-applied mini-bid violates both the version guard at priority 8
        # and the state check at priority 9; the earlier rung decides the answer.
        both_violations = _apply(ctx["mini_bids"][0]["id"], stale_version)
        validate_error(both_violations, "ERR_STALE_CONTRACT_VERSION", 412)
        assert (
            both_violations.json()["data"]["error_id"] != "ERR_MINI_BID_NOT_OPEN"
        )


class TestTheVersionCounterCountsWritesOnly:
    """The counter both guards depend on must move exactly once per write.

    A child write moves its OCC parent because the parent owns a rollup over the
    child; a read moves nothing; a refused write moves nothing; and an unrelated
    row's write moves nothing here.
    """

    def test_a_child_write_moves_the_event_while_reads_and_refusals_do_not(self):
        """One lane create, two reads, one refusal and one unrelated write.

        PRD §2.6: "a counter that increments by one on every mutation of the row, and
        which the concurrency guards of §2.8 compare against."
        PRD §2.6: "an ISO 8601 UTC timestamp in the same format, refreshed on every
        mutation of the row — including mutations the row did not ask for, such as a
        rollup recomputed by a cascade in another aggregate."
        PRD §2.12: "Several operations in this system mutate rows in more than one
        aggregate, and each such mutation is a real mutation: the affected row's
        `updated_at` is refreshed and its `version` incremented, even when the row was
        touched only because a rollup it owns had to be recomputed."
        PRD §3.3: "Its `data_quality_flags` are computed immediately, and the event's
        `lane_count` is increased by one."
        PRD §2.9: "**Uniqueness.** `scac_code` is unique across all carriers
        (`ERR_DUPLICATE_SCAC`); `lane_code` is unique within its bid event
        (`ERR_DUPLICATE_LANE_CODE`); at most one non-`REVOKED` invitation may exist per
        pairing of event and carrier (`ERR_DUPLICATE_INVITATION`); at most one
        non-`WITHDRAWN` lane bid may exist per combination of round, lane and carrier
        (`ERR_DUPLICATE_LANE_BID`); and `load_reference` is unique within its rate record
        (`ERR_DUPLICATE_LOAD_REFERENCE`)."

        Design: Corner/cross_cutting_complexity_layers/version_advances_on_writes_only_and_never_on_reads
        """
        set_clock(DEFAULT_CLOCK)
        event = create_bid_event()
        empty = read_event(event["id"])
        assert empty["lane_count"] == 0
        baseline_version = empty["version"]

        lane = add_lane(event["id"], lane_code=VERSIONED_LANE_CODE)
        assert lane["status"] == "DRAFT"
        after_child = read_event(event["id"])
        assert after_child["version"] == baseline_version + 1, (
            "a child write bumps the OCC parent that owns the rollup"
        )
        assert after_child["lane_count"] == 1

        # Reads are not mutations, for any role and however often they are repeated.
        peek = get_success_data(api_client.get_bid_event(event["id"], CATEGORY_MANAGER))
        assert peek["version"] == after_child["version"]
        assert peek["updated_at"] == after_child["updated_at"]
        again = read_event(event["id"])
        assert again["version"] == after_child["version"]
        assert again["updated_at"] == after_child["updated_at"]

        refused = api_client.create_lane(
            event["id"], lane_payload(lane_code=VERSIONED_LANE_CODE), ANALYST
        )
        validate_error(refused, "ERR_DUPLICATE_LANE_CODE", 409)
        after_refusal = read_event(event["id"])
        assert after_refusal["version"] == after_child["version"], (
            "a failed write consumes no version"
        )
        assert after_refusal["lane_count"] == 1

        # An unrelated aggregate's write owns no rollup on this event.
        create_carrier()
        assert read_event(event["id"])["version"] == after_child["version"]
