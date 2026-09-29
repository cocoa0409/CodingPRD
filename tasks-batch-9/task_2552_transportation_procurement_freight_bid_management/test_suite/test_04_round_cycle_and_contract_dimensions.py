"""Cyclic negotiation rounds and the contract's independently advancing dimensions.

Two structures that a linear state machine cannot express are exercised here. A
bid event re-enters `ROUND_OPEN` after it has already left it, cycling once per
allowed negotiation round; and a contract advances its signature dimension and
its rate-loading dimension on independent tracks that touch at exactly one point.
"""

from test_helpers import (
    ANALYST,
    api_client,
    assert_same_instant,
    CLOCK_GO_LIVE,
    close_round,
    get_success_data,
    go_live,
    load_rate_record,
    open_round,
    read_contract,
    read_event,
    read_lane_bid,
    read_rate_record,
    set_clock,
    setup_open_round_with_bidder,
    setup_staged_rate_record,
    sign_as_carrier,
    sign_as_shipper,
    submit_bid,
)

# Round 1 quote, then a round 2 quote that clears a 2.00 percent reduction target.
ROUND_1_RATE = 2.1152
ROUND_2_RATE = 2.0500
TARGET_REDUCTION_PCT = 2.00

ROUND_1_CLOSES_AT = "2026-08-20T00:00:00Z"
ROUND_2_CLOSES_AT = "2026-08-28T00:00:00Z"


def _two_round_event():
    """An event that allows two negotiation rounds, with round 1 open and bid."""
    ctx = setup_open_round_with_bidder(rounds_allowed=2)
    ctx["bid_round_1"] = ctx["bid_round"]
    ctx["bid_1"] = submit_bid(
        ctx["bid_round_1"]["id"],
        ctx["lane"]["id"],
        ctx["carrier"]["id"],
        rate_per_mile=ROUND_1_RATE,
    )
    return ctx


def _read_round(round_id):
    return get_success_data(api_client.get_bid_round(round_id, ANALYST))


class TestNegotiationRoundCycle:
    """The event visits `ROUND_OPEN` once per negotiation round, not once overall."""

    def test_event_re_enters_round_open_after_it_has_already_left_it(self):
        """A second round returns the event to a state it had already exited.

        PRD §3.4: "Round 1 may be opened from `INVITING` and requires that
        `accepted_invitation_count` is at least 1"
        PRD §3.4: "Subsequent rounds are opened from `ROUND_CLOSED` under the same
        round-count condition."
        PRD §3.4: "The event's `current_round_no` increases by one, the event moves
        to `ROUND_OPEN`, and its `version` increases by one."
        PRD §3.4: "The event moves from `ROUND_OPEN` to `ROUND_CLOSED` and its
        `version` increases by one."

        Design: Difficulty/non_linear_state_machine/bid_event_negotiation_round_cycle
        """
        ctx = _two_round_event()
        assert ctx["bid_round_1"]["round_no"] == 1
        assert read_event(ctx["event"]["id"])["status"] == "ROUND_OPEN"

        close_round(ctx["bid_round_1"]["id"])
        after_first_close = read_event(ctx["event"]["id"])
        assert after_first_close["status"] == "ROUND_CLOSED"
        assert after_first_close["current_round_no"] == 1

        open_round(
            ctx["event"]["id"],
            incumbent_visibility="FULL",
            closes_at=ROUND_2_CLOSES_AT,
            target_reduction_pct=TARGET_REDUCTION_PCT,
        )
        reopened = read_event(ctx["event"]["id"])
        assert reopened["status"] == "ROUND_OPEN", (
            "the event must re-enter ROUND_OPEN for the second negotiation round"
        )
        assert reopened["current_round_no"] == 2
        assert reopened["version"] > after_first_close["version"]

    def test_each_round_closes_one_way_while_the_event_keeps_cycling(self):
        """Round closure is terminal even though the event returns to ROUND_OPEN.

        PRD §3.4: "The round moves to the terminal `CLOSED` and `closed_at` is set
        to the logical clock."
        PRD §3.4: "Rounds carry only the two statuses `OPEN` and `CLOSED`, and
        closure is one-way."
        PRD §3.4: "The round is created with `round_no` set to the event's
        `current_round_no` plus one, `status` `OPEN`, `opens_at` set to the logical
        clock, `closed_at` null, `submitted_bid_count` `0` and `lowest_rate_per_mile`
        null."

        Design: Difficulty/non_linear_state_machine/bid_event_negotiation_round_cycle
        """
        ctx = _two_round_event()
        close_round(ctx["bid_round_1"]["id"])

        round_1 = _read_round(ctx["bid_round_1"]["id"])
        assert round_1["status"] == "CLOSED"
        assert round_1["closed_at"] is not None
        assert round_1["submitted_bid_count"] == 1
        assert float(round_1["lowest_rate_per_mile"]) == ROUND_1_RATE

        round_2 = open_round(
            ctx["event"]["id"],
            incumbent_visibility="FULL",
            closes_at=ROUND_2_CLOSES_AT,
            target_reduction_pct=TARGET_REDUCTION_PCT,
        )
        assert round_2["round_no"] == 2
        assert round_2["status"] == "OPEN"
        assert round_2["closed_at"] is None
        assert round_2["submitted_bid_count"] == 0
        assert round_2["lowest_rate_per_mile"] is None
        assert float(round_2["target_reduction_pct"]) == TARGET_REDUCTION_PCT

        submit_bid(
            round_2["id"],
            ctx["lane"]["id"],
            ctx["carrier"]["id"],
            rate_per_mile=ROUND_2_RATE,
        )
        close_round(round_2["id"])

        assert _read_round(ctx["bid_round_1"]["id"])["status"] == "CLOSED", (
            "closing the second round must not reopen the first"
        )
        assert float(_read_round(round_2["id"])["lowest_rate_per_mile"]) == ROUND_2_RATE
        final_event = read_event(ctx["event"]["id"])
        assert final_event["status"] == "ROUND_CLOSED"
        assert final_event["current_round_no"] == 2

    def test_second_round_bid_is_evaluated_within_its_own_round_only(self):
        """The re-entered round scores its own bid and leaves round 1 untouched.

        PRD §3.5: "from round 2 onward, when the round carries a
        `target_reduction_pct` above `0.00`, a carrier that also bid on this lane in
        the immediately preceding round must quote at or below its own previous
        `rate_per_mile` reduced by that percentage"
        PRD §3.5: "Multiply `cost_per_load_usd` by `awardable_volume_loads` and round
        to 2 decimal places, giving `evaluated_total_cost_usd`."
        PRD §3.4: "each lane bid on the round whose `status` is `SUBMITTED` has its
        evaluated cost and its cost-rank score recomputed and its `rank_in_lane`
        rewritten"

        Design: Difficulty/non_linear_state_machine/bid_event_negotiation_round_cycle
        """
        ctx = _two_round_event()
        close_round(ctx["bid_round_1"]["id"])
        round_2 = open_round(
            ctx["event"]["id"],
            incumbent_visibility="FULL",
            closes_at=ROUND_2_CLOSES_AT,
            target_reduction_pct=TARGET_REDUCTION_PCT,
        )
        bid_2 = submit_bid(
            round_2["id"],
            ctx["lane"]["id"],
            ctx["carrier"]["id"],
            rate_per_mile=ROUND_2_RATE,
        )
        close_round(round_2["id"])

        # 1147 x 2.0500 = 2351.35, plus 137.55 x 1.15 = 158.18, on 600 loads.
        bid_2 = read_lane_bid(bid_2["id"])
        assert float(bid_2["linehaul_per_load_usd"]) == 2351.35
        assert float(bid_2["accessorial_per_load_usd"]) == 158.18
        assert float(bid_2["cost_per_load_usd"]) == 2509.53
        assert float(bid_2["evaluated_total_cost_usd"]) == 1505718.00
        assert bid_2["rank_in_lane"] == 1
        assert bid_2["status"] == "SUBMITTED"

        # The first round's bid keeps the figures it was scored with.
        bid_1 = read_lane_bid(ctx["bid_1"]["id"])
        assert bid_1["status"] == "SUBMITTED"
        assert float(bid_1["cost_per_load_usd"]) == 2584.31
        assert float(bid_1["evaluated_total_cost_usd"]) == 1550586.00
        assert bid_1["rank_in_lane"] == 1


class TestContractDimensionsAdvanceIndependently:
    """Signature progress and rate-loading progress are separate tracks."""

    def test_rates_stage_and_load_while_both_signatures_are_outstanding(self):
        """The rate dimension runs to LOADED on a contract nobody has signed.

        PRD §3.7: "Each contract is created with `status` `DRAFT`,
        `signature_status` `PENDING_BOTH`, `rate_load_status` `NOT_STAGED`,
        `amendment_count` `0`, `rate_record_count` `0`"
        PRD §3.8: "rates may be staged and loaded while signatures are still
        outstanding, and signatures may complete while no rate has been staged"
        PRD §3.8: "its `rate_load_status` moves from `NOT_STAGED` to `STAGED`"
        PRD §3.8: "On success the record moves from `STAGED` to `LOADED`, `loaded_at`
        is set to the logical clock, and on the contract's first loaded record the
        contract's `rate_load_status` moves from `STAGED` to `LOADED`."

        Design: Difficulty/non_linear_state_machine/contract_signature_and_rate_load_dimensions_advance_independently
        """
        ctx = setup_staged_rate_record()
        contract = ctx["contract"]
        assert contract["rate_load_status"] == "STAGED"
        assert contract["signature_status"] == "PENDING_BOTH", (
            "staging a rate must not advance the signature dimension"
        )
        assert contract["status"] == "DRAFT"
        assert contract["rate_record_count"] == 1
        assert contract["carrier_signed_at"] is None
        assert contract["shipper_signed_at"] is None

        load_rate_record(ctx["rate_record"]["id"])
        record = read_rate_record(ctx["rate_record"]["id"])
        assert record["status"] == "LOADED"
        assert record["loaded_at"] is not None
        assert record["live_at"] is None

        loaded_contract = read_contract(contract["id"])
        assert loaded_contract["rate_load_status"] == "LOADED"
        assert loaded_contract["signature_status"] == "PENDING_BOTH", (
            "loading a rate must not advance the signature dimension"
        )
        assert loaded_contract["status"] == "DRAFT"

    def test_signatures_complete_without_disturbing_the_rate_dimension(self):
        """Execution moves the commercial status while the rate stays LOADED.

        PRD §3.8: "A carrier representative signs on behalf of its own carrier: from
        `PENDING_BOTH` the `signature_status` becomes `PENDING_SHIPPER`, and from
        `PENDING_CARRIER` it becomes `FULLY_SIGNED` and the contract's `status` moves
        from `DRAFT` to `EXECUTED`."
        PRD §3.8: "from `PENDING_BOTH` the `signature_status` becomes
        `PENDING_CARRIER`, and from `PENDING_SHIPPER` it becomes `FULLY_SIGNED` and
        `status` moves from `DRAFT` to `EXECUTED`"
        PRD §3.8: "rates may be staged and loaded while signatures are still
        outstanding, and signatures may complete while no rate has been staged"

        Design: Difficulty/non_linear_state_machine/contract_signature_and_rate_load_dimensions_advance_independently
        """
        ctx = setup_staged_rate_record()
        load_rate_record(ctx["rate_record"]["id"])

        after_carrier = sign_as_carrier(ctx["contract"]["id"], ctx["carrier"]["id"])
        assert after_carrier["signature_status"] == "PENDING_SHIPPER"
        assert after_carrier["status"] == "DRAFT", (
            "one signature does not execute the contract"
        )
        assert after_carrier["rate_load_status"] == "LOADED", (
            "signing must leave the rate-loading dimension where it was"
        )
        assert after_carrier["carrier_signed_at"] is not None
        assert after_carrier["shipper_signed_by_user_id"] is None

        after_shipper = sign_as_shipper(ctx["contract"]["id"])
        assert after_shipper["signature_status"] == "FULLY_SIGNED"
        assert after_shipper["status"] == "EXECUTED"
        assert after_shipper["rate_load_status"] == "LOADED", (
            "full execution must not promote the rate to LIVE by itself"
        )
        assert after_shipper["shipper_signed_at"] is not None
        assert read_rate_record(ctx["rate_record"]["id"])["status"] == "LOADED"
        assert after_shipper["version"] > after_carrier["version"]

    def test_go_live_is_the_single_point_where_the_dimensions_couple(self):
        """Only the cutover reads both dimensions and advances the rate to LIVE.

        PRD §3.8: "The two dimensions couple at exactly one point — a rate record may
        only be taken live when the contract's `signature_status` is `FULLY_SIGNED` —
        and nowhere else."
        PRD §3.8: "The record moves from `LOADED` to `LIVE` and `live_at` is set to
        the logical clock."
        PRD §3.8: "The contract's `rate_load_status` moves from `LOADED` to `LIVE`."
        PRD §3.8: "The award allocation the record implements moves from `EXECUTED` to
        `ACTIVE`, and the carrier's `active_primary_lane_count` is recomputed."

        Design: Difficulty/non_linear_state_machine/contract_signature_and_rate_load_dimensions_advance_independently
        """
        ctx = setup_staged_rate_record()
        load_rate_record(ctx["rate_record"]["id"])
        sign_as_carrier(ctx["contract"]["id"], ctx["carrier"]["id"])
        sign_as_shipper(ctx["contract"]["id"])

        set_clock(CLOCK_GO_LIVE)
        record = go_live(ctx["rate_record"]["id"])
        assert record["status"] == "LIVE"
        assert_same_instant(record["live_at"], CLOCK_GO_LIVE, "live_at")

        contract = read_contract(ctx["contract"]["id"])
        assert contract["rate_load_status"] == "LIVE"
        assert contract["signature_status"] == "FULLY_SIGNED"
        assert contract["status"] == "EXECUTED", (
            "the cutover moves the rate dimension, not the commercial one"
        )
        assert read_event(ctx["event"]["id"])["status"] == "LIVE"
