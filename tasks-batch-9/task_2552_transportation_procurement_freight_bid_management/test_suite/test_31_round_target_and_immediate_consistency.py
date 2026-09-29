"""One field that binds only under two selectors, and read-your-writes discipline.

`target_reduction_pct` is informational in round 1 and binding from round 2, and
even then only against a carrier that bid the same lane in the previous round —
so a newcomer quoting far above the target is accepted beside a returning bidder
refused one hundredth above its own reduced rate. The rate floor, by contrast,
binds everyone. The rest of the file is the consistency model: a write's own
response already carries every field it recomputed, and a refused write leaves
no link of its cascade half-applied.
"""

from test_helpers import (
    ANALYST,
    CATEGORY_MANAGER,
    CATEGORY_MANAGER_USER_ID,
    CONTRACT_ADMIN,
    DEFAULT_CLOCK,
    api_client,
    approve_allocation,
    assert_same_instant,
    close_round,
    create_event_with_locked_lanes,
    create_qualified_carrier,
    get_success_data,
    invite_and_accept,
    lane_bid_payload,
    make_carrier_rep_headers,
    open_round,
    read_allocation,
    read_carrier,
    read_event,
    read_lane,
    read_lane_bid,
    second_carrier_overrides,
    set_clock,
    setup_published_routing_guide,
    submit_bid,
    validate_error,
    validate_paginated,
    validate_success,
)

# The event allows two negotiation rounds and floors every rate at 1.5000.
TWO_ROUNDS = 2
RATE_FLOOR_PER_MILE = 1.5000

# Both rounds ask returning bidders for the same 5.00% reduction.
TARGET_REDUCTION_PCT = 5.00

# The returning bidder's round 1 rate, and 2.0000 * (1 - 0.05) == 1.9000.
RETURNING_FIRST_RATE = 2.0000
TARGET_RATE = 1.9000
ONE_HUNDREDTH_ABOVE_TARGET = 1.9100

# The newcomer's rate: far above the target, but it has no previous round.
NEWCOMER_RATE = 2.4000

# 2.4000 * (1 - 0.05) == 2.2800, the reduction the same rate owes in round 2.
REDUCED_NEWCOMER_RATE = 2.2800
BELOW_FLOOR_RATE = 1.4900
NEWCOMER_VOLUME_LOADS = 300

# The lane's planned volume, fully covered by the single primary allocation.
LANE_PLAN_LOADS = 550
FULL_COVERAGE_PCT = 100.00
NO_DIVERSITY_PCT = 0.00

# A diversity floor the NONE-classified carrier can never reach.
DIVERSITY_FLOOR_PCT = 50.00


def _attempt_bid(round_id, lane_id, carrier_id, rate_per_mile, **overrides):
    """Submits one lane bid as its owning carrier, without asserting the outcome."""
    return api_client.create_lane_bid(
        round_id,
        lane_bid_payload(
            lane_id, carrier_id, rate_per_mile=rate_per_mile, **overrides
        ),
        make_carrier_rep_headers(carrier_id),
    )


def _read_round(round_id):
    return get_success_data(api_client.get_bid_round(round_id, ANALYST))


def _commit(event_id):
    """Attempts the award commit without asserting the outcome."""
    return api_client.award_bid_event(event_id, CATEGORY_MANAGER)


def _two_carrier_event_with_a_second_round(first_round_rate):
    """Round 1 closed with only the returning bidder's rate, round 2 open.

    Both rounds carry the same reduction target, and both carriers hold accepted
    invitations, so the only difference between them in round 2 is whether they
    bid this lane in round 1.
    """
    set_clock(DEFAULT_CLOCK)
    returning = create_qualified_carrier()
    newcomer = create_qualified_carrier(carrier_overrides=second_carrier_overrides())
    event, lanes = create_event_with_locked_lanes(
        rounds_allowed=TWO_ROUNDS, rate_floor_per_mile=RATE_FLOOR_PER_MILE
    )
    invite_and_accept(event["id"], returning["id"])
    invite_and_accept(event["id"], newcomer["id"])

    round_one = open_round(event["id"], target_reduction_pct=TARGET_REDUCTION_PCT)
    first_bid = submit_bid(
        round_one["id"],
        lanes[0]["id"],
        returning["id"],
        rate_per_mile=first_round_rate,
    )
    close_round(round_one["id"])
    round_two = open_round(event["id"], target_reduction_pct=TARGET_REDUCTION_PCT)
    return {
        "event": event,
        "lane": lanes[0],
        "returning": returning,
        "newcomer": newcomer,
        "round_one": round_one,
        "first_bid": first_bid,
        "round_two": round_two,
    }


def _approved_award_awaiting_commit(**event_overrides):
    """A published guide whose every allocation is approved, event in AWARDING."""
    ctx = setup_published_routing_guide(**event_overrides)
    ctx["allocations"] = [
        approve_allocation(allocation["id"]) for allocation in ctx["allocations"]
    ]
    ctx["allocation"] = ctx["allocations"][0]
    return ctx


class TestTheRoundNumberSelectsTheTargetEnforcement:
    """The same rate, accepted in round 1 and refused in round 2."""

    def test_the_target_is_informational_in_round_one_and_binding_in_round_two(self):
        """2.4000 lands in round 1; the identical quote is refused in round 2.

        PRD §3.4: "`target_reduction_pct` is the reduction the shipper is asking
        returning bidders to deliver against their own previous round. In round 1 it is
        purely informational, because there is no previous round to measure against; from
        round 2 onward it becomes an enforced constraint, described in §3.5."
        PRD §3.5: "and from round 2 onward, when the round carries a
        `target_reduction_pct` above `0.00`, a carrier that also bid on this lane in the
        immediately preceding round must quote at or below its own previous
        `rate_per_mile` reduced by that percentage, otherwise
        `ERR_RATE_ABOVE_ROUND_TARGET` (422)."
        PRD §2.12: "`BidRound.lowest_rate_per_mile` is the minimum `rate_per_mile`
        across the round's bids whose status is `SUBMITTED`, and is null when the
        round holds none."

        Design: Corner/cross_cutting_complexity_layers/the_round_number_selects_whether_the_reduction_target_is_enforced
        """
        ctx = _two_carrier_event_with_a_second_round(NEWCOMER_RATE)
        round_one = _read_round(ctx["round_one"]["id"])
        assert round_one["round_no"] == 1
        assert float(round_one["target_reduction_pct"]) == TARGET_REDUCTION_PCT
        assert ctx["first_bid"]["status"] == "SUBMITTED"
        assert float(ctx["first_bid"]["rate_per_mile"]) == NEWCOMER_RATE, (
            "the target changed nothing about what round 1 would accept"
        )

        round_two_id = ctx["round_two"]["id"]
        assert _read_round(round_two_id)["round_no"] == TWO_ROUNDS
        repeated = _attempt_bid(
            round_two_id, ctx["lane"]["id"], ctx["returning"]["id"], NEWCOMER_RATE
        )
        validate_error(repeated, "ERR_RATE_ABOVE_ROUND_TARGET", 422)

        empty = _read_round(round_two_id)
        assert empty["submitted_bid_count"] == 0
        assert empty["lowest_rate_per_mile"] is None
        assert read_lane_bid(ctx["first_bid"]["id"])["status"] == "SUBMITTED", (
            "the refusal leaves the previous round's bid exactly where it was"
        )

        delivered = validate_success(
            _attempt_bid(
                round_two_id,
                ctx["lane"]["id"],
                ctx["returning"]["id"],
                REDUCED_NEWCOMER_RATE,
            ),
            201,
        )
        assert delivered["status"] == "SUBMITTED"
        assert float(delivered["rate_per_mile"]) == REDUCED_NEWCOMER_RATE

    def test_the_boundary_is_inclusive_and_the_floor_binds_the_newcomer_anyway(self):
        """One hundredth above is refused, exactly at target is accepted.

        PRD §3.5: "Finally the two money gates: `rate_per_mile` must be greater than or
        equal to the event's `rate_floor_per_mile`, otherwise `ERR_RATE_BELOW_FLOOR`
        (422); and from round 2 onward, when the round carries a `target_reduction_pct`
        above `0.00`, a carrier that also bid on this lane in the immediately preceding
        round must quote at or below its own previous `rate_per_mile` reduced by that
        percentage, otherwise `ERR_RATE_ABOVE_ROUND_TARGET` (422)."
        PRD §3.5: "A carrier bidding this lane for the first time in this round has no
        previous rate to be measured against and so cannot violate the target."
        PRD §2.9: "**Per-rate money limits.** A submitted or proposed per-mile rate must
        be at or above the event's rate floor (`ERR_RATE_BELOW_FLOOR`); a returning
        bidder in a round carrying a reduction target must meet that target
        (`ERR_RATE_ABOVE_ROUND_TARGET`); and a mini-bid's adjustment must stay inside the
        adjustment cap (`ERR_ADJUSTMENT_EXCEEDS_CAP`)."

        Design: Corner/cross_cutting_complexity_layers/the_round_number_selects_whether_the_reduction_target_is_enforced
        """
        ctx = _two_carrier_event_with_a_second_round(RETURNING_FIRST_RATE)
        round_two_id = ctx["round_two"]["id"]
        lane_id = ctx["lane"]["id"]

        above = _attempt_bid(
            round_two_id, lane_id, ctx["returning"]["id"], ONE_HUNDREDTH_ABOVE_TARGET
        )
        validate_error(above, "ERR_RATE_ABOVE_ROUND_TARGET", 422)

        # The floor is not selected by anything: it binds the newcomer too.
        below_floor = _attempt_bid(
            round_two_id,
            lane_id,
            ctx["newcomer"]["id"],
            BELOW_FLOOR_RATE,
            committed_volume_loads=NEWCOMER_VOLUME_LOADS,
        )
        validate_error(below_floor, "ERR_RATE_BELOW_FLOOR", 422)
        assert (
            below_floor.json()["data"]["error_id"] != "ERR_RATE_ABOVE_ROUND_TARGET"
        )

        unbound = validate_success(
            _attempt_bid(
                round_two_id,
                lane_id,
                ctx["newcomer"]["id"],
                NEWCOMER_RATE,
                committed_volume_loads=NEWCOMER_VOLUME_LOADS,
            ),
            201,
        )
        assert unbound["status"] == "SUBMITTED"
        assert float(unbound["rate_per_mile"]) == NEWCOMER_RATE, (
            "a carrier with no previous rate on this lane cannot miss the target"
        )

        at_target = validate_success(
            _attempt_bid(round_two_id, lane_id, ctx["returning"]["id"], TARGET_RATE),
            201,
        )
        assert at_target["status"] == "SUBMITTED"
        assert float(at_target["rate_per_mile"]) == TARGET_RATE

        final = _read_round(round_two_id)
        assert final["submitted_bid_count"] == 2
        assert float(final["lowest_rate_per_mile"]) == TARGET_RATE


class TestDerivedFieldsAreCurrentInTheResponseThatChangedThem:
    """The approval's own response already carries the debit and the rollups."""

    def test_the_approve_response_already_shows_everything_it_recomputed(self):
        """No second call is needed to observe the reserved volume or the coverage.

        PRD §3.7: "Approval is where volume is actually reserved, and it is the first of
        the three-link consistency chain:"
        PRD §3.7: "The allocation moves from `PROPOSED` to `APPROVED`,
        `approved_by_user_id` is set to the acting `X-User-ID` — the value the
        segregation-of-duties rule of §2.11 will later compare against — and `approved_at`
        is set to the logical clock."
        PRD §3.7: "The lane's `unallocated_volume_loads` is reduced by the allocation's
        `allocated_volume_loads`, and the lane's `awarded_coverage_pct` is recomputed as
        `annual_volume_loads` minus `unallocated_volume_loads`, multiplied by `100.00`,
        divided by `annual_volume_loads`, and rounded to 2 decimal places."
        PRD §3.7: "The event's `coverage_pct` and `diversity_pct` are recomputed over the
        allocation status set given in §3.3."

        Design: Corner/consistency_model/every_derived_field_is_current_in_the_same_response_that_changed_it
        """
        guide = setup_published_routing_guide()
        allocation = guide["allocation"]
        assert allocation["status"] == "PROPOSED"
        assert allocation["approved_by_user_id"] is None
        assert allocation["approved_at"] is None
        assert allocation["allocated_volume_loads"] == LANE_PLAN_LOADS

        before_lane = read_lane(guide["lane"]["id"])
        assert before_lane["unallocated_volume_loads"] == LANE_PLAN_LOADS
        assert float(before_lane["awarded_coverage_pct"]) == 0.00
        assert float(read_event(guide["event"]["id"])["coverage_pct"]) == 0.00

        approved = validate_success(
            api_client.approve_award_allocation(allocation["id"], CATEGORY_MANAGER)
        )
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == CATEGORY_MANAGER_USER_ID
        assert_same_instant(approved["approved_at"], DEFAULT_CLOCK, "approved_at")

        after_lane = read_lane(guide["lane"]["id"])
        assert after_lane["unallocated_volume_loads"] == 0
        assert float(after_lane["awarded_coverage_pct"]) == FULL_COVERAGE_PCT

        after_event = read_event(guide["event"]["id"])
        assert float(after_event["coverage_pct"]) == FULL_COVERAGE_PCT
        assert float(after_event["diversity_pct"]) == NO_DIVERSITY_PCT, (
            "the only routed carrier is classified NONE, so no volume is diverse"
        )
        assert after_event["status"] == "AWARDING"

    def test_a_second_identical_read_changes_nothing(self):
        """Nothing is still settling after the write returns.

        PRD §2.12: "Several operations in this system mutate rows in more than one
        aggregate, and each such mutation is a real mutation: the affected row's
        `updated_at` is refreshed and its `version` incremented, even when the row was
        touched only because a rollup it owns had to be recomputed."
        PRD §3.3: "`coverage_pct` is `0.00` when `total_scope_volume_loads` is zero;
        otherwise it is the sum of `allocated_volume_loads` over the event's award
        allocations whose `status` is `APPROVED`, `EXECUTED`, `ACTIVE` or
        `SUSPENDED_ROUTING`, multiplied by `100.00`, divided by
        `total_scope_volume_loads`, rounded to 2 decimal places."

        Design: Corner/consistency_model/every_derived_field_is_current_in_the_same_response_that_changed_it
        """
        guide = setup_published_routing_guide()
        approved = validate_success(
            api_client.approve_award_allocation(
                guide["allocation"]["id"], CATEGORY_MANAGER
            )
        )

        first_allocation = read_allocation(approved["id"])
        assert first_allocation == read_allocation(approved["id"])
        assert first_allocation["status"] == approved["status"]
        assert first_allocation["approved_at"] == approved["approved_at"]
        assert first_allocation["version"] == approved["version"]

        first_lane = read_lane(guide["lane"]["id"])
        assert first_lane == read_lane(guide["lane"]["id"])
        first_event = read_event(guide["event"]["id"])
        assert first_event == read_event(guide["event"]["id"])
        assert float(first_event["coverage_pct"]) == FULL_COVERAGE_PCT
        assert first_lane["unallocated_volume_loads"] == 0


class TestARefusedCommitLeavesNoPartialWrite:
    """The five-link commit fails its diversity gate, so none of it lands."""

    def test_the_refused_commit_leaves_the_first_three_links_unwritten(self):
        """The allocation, its bid, its lane and the event are all as they were.

        PRD §3.7: "The event's `diversity_pct` must be greater than or equal to its
        `diversity_min_pct`, otherwise `ERR_DIVERSITY_MINIMUM_NOT_MET` (422)."
        PRD §3.7: "Every allocation of the `PUBLISHED` run whose `status` is `APPROVED`
        moves to `EXECUTED`, and each one's referenced lane bid moves from `SHORTLISTED`
        to `AWARDED_PRIMARY` when the allocation's `routing_position` is `PRIMARY`, or to
        `AWARDED_BACKUP` when it is `BACKUP_1` or `BACKUP_2`."
        PRD §3.7: "Every lane holding an executed allocation moves from `LOCKED` to
        `AWARDED`, and its `awarded_coverage_pct` is recomputed."
        PRD §2.9: "Checks are evaluated in a single fixed ascending order, and **the
        first violated check decides the response** — no later check is evaluated and
        no partial write is retained."

        Design: Corner/consistency_model/a_refused_request_leaves_no_partially_applied_state
        """
        ctx = _approved_award_awaiting_commit(diversity_min_pct=DIVERSITY_FLOOR_PCT)
        event_id = ctx["event"]["id"]
        before = read_event(event_id)
        assert before["status"] == "AWARDING"
        assert float(before["diversity_pct"]) == NO_DIVERSITY_PCT
        assert float(before["diversity_min_pct"]) == DIVERSITY_FLOOR_PCT

        refused = _commit(event_id)
        validate_error(refused, "ERR_DIVERSITY_MINIMUM_NOT_MET", 422)

        allocation = read_allocation(ctx["allocation"]["id"])
        assert allocation["status"] == "APPROVED", "link 2 never ran"
        assert read_lane_bid(allocation["lane_bid_id"])["status"] == "SHORTLISTED"
        assert read_lane(ctx["lane"]["id"])["status"] == "LOCKED", "link 3 never ran"

        after = read_event(event_id)
        assert after["status"] == "AWARDING"
        assert after["awarded_at"] is None
        assert after["award_cost_usd"] is None
        assert after["savings_pct"] is None
        assert after["version"] == before["version"], (
            "a refused commit is not a mutation of the event"
        )

    def test_the_refused_commit_creates_no_contract_and_debits_no_carrier(self):
        """Links 4 and 5 leave no trace either, and the listing agrees.

        PRD §3.7: "One contract is created for each distinct pairing of `bid_event_id`
        and `carrier_id` appearing among those executed allocations — one contract per
        carrier per event, however many lanes that carrier won."
        PRD §3.7: "Each carrier that now holds a contract has its
        `committed_volume_loads` and `active_primary_lane_count` recomputed from its
        executed allocations, per the status sets in §2.12."
        PRD §2.12: "`Carrier.committed_volume_loads` sums `allocated_volume_loads` over
        that carrier's allocations whose status is `EXECUTED`, `ACTIVE` or
        `SUSPENDED_ROUTING`."

        Design: Corner/consistency_model/a_refused_request_leaves_no_partially_applied_state
        """
        ctx = _approved_award_awaiting_commit(diversity_min_pct=DIVERSITY_FLOOR_PCT)
        event_id = ctx["event"]["id"]

        validate_error(_commit(event_id), "ERR_DIVERSITY_MINIMUM_NOT_MET", 422)

        rows, meta = validate_paginated(
            api_client.list_award_allocations(
                CATEGORY_MANAGER, {"bid_event_id": event_id}
            )
        )
        assert meta["total_count"] == len(ctx["allocations"])
        assert [row["status"] for row in rows] == ["APPROVED"] * len(rows)

        _contracts, contract_meta = validate_paginated(
            api_client.list_contracts(CONTRACT_ADMIN, {"bid_event_id": event_id})
        )
        assert contract_meta["total_count"] == 0, "link 4 created no contract"

        carrier = read_carrier(ctx["carrier"]["id"])
        assert carrier["committed_volume_loads"] == 0, "link 5 left no trace"
        assert carrier["active_primary_lane_count"] == 0
