"""Compensating pairs that must leave a conserved quantity exactly where it started.

Two quantities are protected here: whole loads on a lane, debited by approving an
allocation and credited back by rejecting it; and contracted money, moved by
applying a mini-bid and moved back by reverting it. In both cases the interesting
part is the return trip — an implementation that reverses a delta arithmetically
instead of re-deriving the quantity from the surviving rows lands close to the
right answer but not on it.
"""

from test_helpers import (
    allocation_rejection_payload,
    api_client,
    apply_mini_bid,
    approve_allocation,
    assert_contract_value_round_trip,
    assert_lane_volume_conservation,
    assert_same_instant,
    CATEGORY_MANAGER,
    CONTRACT_ADMIN,
    get_success_data,
    LANE_A_WITH_INCUMBENT,
    list_allocations,
    mini_bid_revert_payload,
    read_allocation,
    read_carrier,
    read_contract,
    read_event,
    read_lane,
    read_lane_bid,
    read_mini_bid,
    read_rate_record,
    setup_applied_mini_bid,
    setup_open_mini_bid,
    setup_published_routing_guide,
)

# Lane A plans 550 loads and the single bid commits 600, so the waterfall hands
# the whole lane to that one carrier.
LANE_PLAN_LOADS = 550

# The contract's rate basis: 2.0000 per mile over 1147 miles on 600 loads.
BASE_VALUE_USD = 1376400.00
DISCOUNT_PCT = 0.015
DISCOUNT_USD = 20646.00
ALLOWANCE_PCT = 0.020
ALLOWANCE_USD = 27115.08
TOTAL_VALUE_USD = 1382869.08

# After the 10.00 percent adjustment to 2.2000 the base crosses 1500000, which
# moves the discount into the top tier.
AMENDED_BASE_USD = 1514040.00
AMENDED_DISCOUNT_PCT = 0.025
AMENDED_DISCOUNT_USD = 37851.00
AMENDED_ALLOWANCE_USD = 29523.78
AMENDED_TOTAL_USD = 1505712.78

ADJUSTED_RATE_PER_MILE = 2.2000
ADJUSTMENT_PCT = 10.00
REPLACEMENT_FROM = "2026-09-05T00:00:00Z"
REPLACEMENT_TO = "2027-09-01T00:00:00Z"
APPLY_INSTANT = "2026-09-05T00:00:00Z"

# The incumbent baseline of lane A: (1147 x 2.4000 + 137.55) x 550.
BASELINE_COST_USD = 1589692.50
SAVINGS_PCT_BEFORE = 13.01
SAVINGS_PCT_AMENDED = 5.28

MINI_BID_WINDOW = {
    "window_open_at": "2026-09-01T00:00:00Z",
    "window_close_at": "2026-09-11T00:00:00Z",
}
REJECTION_REASON = "Carrier withdrew its capacity commitment"
REVERT_REASON = "Market index correction withdrawn"


def _single_lane_guide():
    """One lane, one bid, one PROPOSED PRIMARY allocation for the whole lane."""
    return setup_published_routing_guide(
        lane_overrides=[dict(LANE_A_WITH_INCUMBENT)]
    )


def _reject_allocation(allocation_id, **overrides):
    """Rejects an allocation with a mandatory reason."""
    return get_success_data(
        api_client.reject_award_allocation(
            allocation_id,
            allocation_rejection_payload(**overrides),
            CATEGORY_MANAGER,
        )
    )


class TestLaneVolumeConservationAcrossApproveAndReject:
    """Whole loads: nothing is reserved until approval, and rejection gives it all back."""

    def test_a_proposed_allocation_reserves_no_volume_at_all(self):
        """State 0: the published guide plans the lane without touching its capacity.

        PRD §3.6: "The waterfall itself writes nothing to the lane: it never sets
        `unallocated_volume_loads` and never sets `awarded_coverage_pct`."
        PRD §2.12: "A `PROPOSED` allocation reserves nothing at all: the debit against
        `unallocated_volume_loads` is taken when the allocation is approved and credited
        back exactly when it is rejected or superseded."
        PRD §3.3: "`coverage_pct` is `0.00` when `total_scope_volume_loads` is zero;
        otherwise it is the sum of `allocated_volume_loads` over the event's award
        allocations whose `status` is `APPROVED`, `EXECUTED`, `ACTIVE` or
        `SUSPENDED_ROUTING`"

        Design: Difficulty/compensating_invariant/lane_volume_conservation_across_allocation_approve_and_reject
        """
        ctx = _single_lane_guide()
        allocation = ctx["allocation"]
        assert allocation["status"] == "PROPOSED"
        assert allocation["routing_position"] == "PRIMARY"
        assert allocation["allocated_volume_loads"] == LANE_PLAN_LOADS

        lane = read_lane(ctx["lane"]["id"])
        assert lane["annual_volume_loads"] == LANE_PLAN_LOADS
        assert lane["unallocated_volume_loads"] == LANE_PLAN_LOADS
        assert float(lane["awarded_coverage_pct"]) == 0.00
        assert_lane_volume_conservation(lane, list_allocations(lane_id=lane["id"]))
        assert float(read_event(ctx["event"]["id"])["coverage_pct"]) == 0.00

    def test_approval_debits_the_lane_and_rejection_credits_the_same_loads(self):
        """States 1 and 2: the invariant holds before, between and after the pair.

        PRD §3.7: "The lane's `unallocated_volume_loads` is reduced by the allocation's
        `allocated_volume_loads`, and the lane's `awarded_coverage_pct` is recomputed as
        `annual_volume_loads` minus `unallocated_volume_loads`, multiplied by `100.00`,
        divided by `annual_volume_loads`, and rounded to 2 decimal places."
        PRD §3.7: "If — and only if — the allocation was `APPROVED` rather than
        `PROPOSED`, its `allocated_volume_loads` is credited back to the lane's
        `unallocated_volume_loads`. The credit is the exact figure that was debited, so
        the conservation identity of §2.12 is restored without recomputation drift."
        PRD §3.7: "The event's `coverage_pct` and `diversity_pct` are recomputed over the
        allocation status set given in §3.3."

        Design: Difficulty/compensating_invariant/lane_volume_conservation_across_allocation_approve_and_reject
        """
        ctx = _single_lane_guide()
        lane_id = ctx["lane"]["id"]

        approve_allocation(ctx["allocation"]["id"])
        reserved = read_lane(lane_id)
        assert reserved["unallocated_volume_loads"] == 0
        assert float(reserved["awarded_coverage_pct"]) == 100.00
        assert_lane_volume_conservation(reserved, list_allocations(lane_id=lane_id))
        assert float(read_event(ctx["event"]["id"])["coverage_pct"]) == 100.00

        _reject_allocation(ctx["allocation"]["id"], rejection_reason=REJECTION_REASON)
        released = read_lane(lane_id)
        assert released["unallocated_volume_loads"] == LANE_PLAN_LOADS, (
            "the rejection must credit back precisely the 550 loads the approval "
            "debited - never 549, 551 or a doubled 1100"
        )
        assert float(released["awarded_coverage_pct"]) == 0.00
        assert_lane_volume_conservation(released, list_allocations(lane_id=lane_id))
        assert float(read_event(ctx["event"]["id"])["coverage_pct"]) == 0.00

    def test_the_rejected_row_keeps_its_volume_while_leaving_the_reserved_set(self):
        """The credit comes from the status set changing, not from zeroing the row.

        PRD §3.7: "The allocation moves to the terminal `REJECTED` and records
        `rejection_reason`."
        PRD §3.7: "The lane bid the allocation referenced moves from `SHORTLISTED` back
        to `NOT_AWARDED`, since that carrier is no longer being routed on that lane."
        PRD §3.7: "The allocation on that lane whose `routing_position` is `BACKUP_1` and
        whose `status` is `PROPOSED` or `APPROVED` is promoted to `PRIMARY`"
        PRD §2.12: "`Carrier.committed_volume_loads` sums `allocated_volume_loads` over
        that carrier's allocations whose status is `EXECUTED`, `ACTIVE` or
        `SUSPENDED_ROUTING`."

        Design: Difficulty/compensating_invariant/lane_volume_conservation_across_allocation_approve_and_reject
        """
        ctx = _single_lane_guide()
        carrier_id = ctx["carrier"]["id"]
        assert read_carrier(carrier_id)["committed_volume_loads"] == 0

        approve_allocation(ctx["allocation"]["id"])
        assert read_carrier(carrier_id)["committed_volume_loads"] == 0, (
            "only executed allocations feed the carrier's committed capacity"
        )

        _reject_allocation(ctx["allocation"]["id"], rejection_reason=REJECTION_REASON)
        rejected = read_allocation(ctx["allocation"]["id"])
        assert rejected["status"] == "REJECTED"
        assert rejected["rejection_reason"] == REJECTION_REASON
        assert rejected["allocated_volume_loads"] == LANE_PLAN_LOADS, (
            "the row keeps its planned volume; it simply leaves the reserved set"
        )
        assert read_lane_bid(ctx["bid"]["id"])["status"] == "NOT_AWARDED"

        # No backup existed, so nothing was promoted and the lane ends uncovered.
        allocations = list_allocations(lane_id=ctx["lane"]["id"])
        assert len(allocations) == 1
        assert allocations[0]["promoted_from_position"] is None
        assert read_carrier(carrier_id)["committed_volume_loads"] == 0


class TestContractMoneyConservationAcrossApplyAndRevert:
    """Contracted money: the tiered value must be re-derived, never delta-patched."""

    @staticmethod
    def _open_mini_bid():
        """Live rate at 2.0000 over 600 loads, with a 2.2000 proposal open on it."""
        return setup_open_mini_bid(
            proposed_rate_per_mile=ADJUSTED_RATE_PER_MILE,
            mini_bid_overrides=dict(MINI_BID_WINDOW),
            proposal_clock=APPLY_INSTANT,
            rate_overrides={"committed_volume_loads": 600},
            lane_overrides=[dict(LANE_A_WITH_INCUMBENT)],
        )

    @staticmethod
    def _applied_mini_bid():
        """The same setup carried through the apply."""
        return setup_applied_mini_bid(
            proposed_rate_per_mile=ADJUSTED_RATE_PER_MILE,
            mini_bid_overrides=dict(MINI_BID_WINDOW),
            proposal_clock=APPLY_INSTANT,
            rate_overrides={"committed_volume_loads": 600},
            lane_overrides=[dict(LANE_A_WITH_INCUMBENT)],
        )

    def test_the_apply_re_derives_the_whole_tiered_value_over_the_new_basis(self):
        """States 0 and 1: the rate rise carries the contract into the top tier.

        PRD §3.8: "Only rate records whose `status` is `STAGED`, `LOADED`, `LIVE` or
        `AT_RISK` are in the basis. Records whose `status` is `SUPERSEDED` or
        `ROLLED_BACK` are **excluded**, which is precisely how a mini-bid apply removes
        the old rate's value and a revert removes the replacement's."
        PRD §3.8: "below `500000` it is `0.000`; from `500000` up to but not including
        `1500000` it is `0.015`; at `1500000` and above it is `0.025`"
        PRD §3.8: "The contract's `accessorial_allowance_pct` is selected from the
        **post-discount subtotal**, not from the base"
        PRD §3.9: "The contract's `status` moves from `EXECUTED` to `AMENDED`, its
        `amendment_count` increases by one, its committed value is re-evaluated over the
        new basis"

        Design: Difficulty/compensating_invariant/contract_money_conservation_across_mini_bid_apply_and_revert
        """
        ctx = self._open_mini_bid()
        before = read_contract(ctx["contract"]["id"])
        assert float(before["base_committed_value_usd"]) == BASE_VALUE_USD
        assert float(before["volume_discount_pct"]) == DISCOUNT_PCT
        assert float(before["volume_discount_usd"]) == DISCOUNT_USD
        assert float(before["accessorial_allowance_pct"]) == ALLOWANCE_PCT
        assert float(before["accessorial_allowance_usd"]) == ALLOWANCE_USD
        assert float(before["total_committed_value_usd"]) == TOTAL_VALUE_USD
        assert before["amendment_count"] == 0
        assert before["status"] == "EXECUTED"

        applied = apply_mini_bid(
            ctx["mini_bid"]["id"],
            before["version"],
            effective_from=REPLACEMENT_FROM,
            effective_to=REPLACEMENT_TO,
        )
        assert applied["status"] == "APPLIED"

        amended = read_contract(ctx["contract"]["id"])
        assert float(amended["base_committed_value_usd"]) == AMENDED_BASE_USD
        assert float(amended["volume_discount_pct"]) == AMENDED_DISCOUNT_PCT, (
            "the higher base crosses into the top volume discount tier"
        )
        assert float(amended["volume_discount_usd"]) == AMENDED_DISCOUNT_USD
        assert float(amended["accessorial_allowance_usd"]) == AMENDED_ALLOWANCE_USD
        assert float(amended["total_committed_value_usd"]) == AMENDED_TOTAL_USD
        assert amended["amendment_count"] == 1
        assert amended["status"] == "AMENDED"

    def test_the_apply_supersedes_the_original_and_mints_the_replacement(self):
        """State 1: the basis swap that carries the money, plus the event rollups.

        PRD §3.9: "A replacement rate record is minted directly in `LIVE` — it does not
        pass through `STAGED` or `LOADED`"
        PRD §3.9: "The targeted record moves from `LIVE` or `AT_RISK` to `SUPERSEDED`,
        and its `superseded_by_rate_record_id` is set to the new record's `id`. The
        mini-bid records `applied_rate_record_id` as the new record's `id` and
        `applied_at` from the logical clock."
        PRD §3.9: "The event's `award_cost_usd` and `savings_pct` are recomputed, since
        the portfolio's committed value has changed."

        Design: Difficulty/compensating_invariant/contract_money_conservation_across_mini_bid_apply_and_revert
        """
        ctx = self._applied_mini_bid()
        replacement = ctx["replacement_record"]
        assert replacement["status"] == "LIVE"
        assert float(replacement["rate_per_mile"]) == ADJUSTED_RATE_PER_MILE
        assert replacement["committed_volume_loads"] == 600, (
            "the replacement copies the committed volume of the record it replaces"
        )
        assert_same_instant(replacement["effective_from"], REPLACEMENT_FROM)
        assert_same_instant(replacement["effective_to"], REPLACEMENT_TO)
        assert replacement["routing_position"] == "PRIMARY"

        superseded = ctx["rate_record"]
        assert superseded["status"] == "SUPERSEDED"
        assert superseded["superseded_by_rate_record_id"] == replacement["id"]

        mini_bid = ctx["mini_bid"]
        assert mini_bid["applied_rate_record_id"] == replacement["id"]
        assert_same_instant(mini_bid["applied_at"], APPLY_INSTANT, "applied_at")
        assert float(mini_bid["adjustment_pct"]) == ADJUSTMENT_PCT
        assert float(mini_bid["contract_value_before_usd"]) == TOTAL_VALUE_USD
        assert float(mini_bid["contract_value_after_usd"]) == AMENDED_TOTAL_USD

        event = read_event(ctx["event"]["id"])
        assert float(event["baseline_cost_usd"]) == BASELINE_COST_USD
        assert float(event["award_cost_usd"]) == AMENDED_TOTAL_USD
        assert float(event["savings_pct"]) == SAVINGS_PCT_AMENDED

    def test_the_revert_restores_the_committed_value_to_the_cent(self):
        """State 2: the round trip lands on the snapshot exactly, not near it.

        PRD §3.9: "the contract's `total_committed_value_usd` after a revert equals the
        `contract_value_before_usd` snapshotted at apply time **exactly** — the
        round-trip leaves no residue."
        PRD §2.12: "Consequently, after an apply followed by a revert,
        `total_committed_value_usd` equals the value snapshotted in
        `contract_value_before_usd` exactly, to the cent, and not merely to within a
        rounding step."
        PRD §3.9: "The contract's `amendment_count` decreases by one, its committed value
        is re-evaluated over the restored basis, and its `version` increases by one. When
        `amendment_count` returns to `0`, the contract's `status` moves from `AMENDED`
        back to `EXECUTED`"

        Design: Difficulty/compensating_invariant/contract_money_conservation_across_mini_bid_apply_and_revert
        """
        ctx = self._applied_mini_bid()
        assert float(ctx["contract"]["total_committed_value_usd"]) == AMENDED_TOTAL_USD

        get_success_data(
            api_client.revert_mini_bid(
                ctx["mini_bid"]["id"],
                mini_bid_revert_payload(revert_reason=REVERT_REASON),
                CONTRACT_ADMIN,
            )
        )

        restored = read_contract(ctx["contract"]["id"])
        assert float(restored["total_committed_value_usd"]) == TOTAL_VALUE_USD
        assert restored["amendment_count"] == 0
        assert restored["status"] == "EXECUTED"
        assert_contract_value_round_trip(
            restored, read_mini_bid(ctx["mini_bid"]["id"])
        )

    def test_the_revert_re_derives_every_component_rather_than_patching_a_delta(self):
        """State 2: reversing only the total would leave the discount in the top tier.

        PRD §3.8: "The contract's `volume_discount_pct` is selected from
        `base_committed_value_usd`: below `500000` it is `0.000`; from `500000` up to but
        not including `1500000` it is `0.015`; at `1500000` and above it is `0.025`."
        PRD §3.8: "Multiply the subtotal by `accessorial_allowance_pct` and round to 2
        decimal places to obtain `accessorial_allowance_usd`."
        PRD §2.12: "A contract's `total_committed_value_usd` is derived only from rate
        records that are still part of its rate basis."

        Design: Difficulty/compensating_invariant/contract_money_conservation_across_mini_bid_apply_and_revert
        """
        ctx = self._applied_mini_bid()
        get_success_data(
            api_client.revert_mini_bid(
                ctx["mini_bid"]["id"],
                mini_bid_revert_payload(revert_reason=REVERT_REASON),
                CONTRACT_ADMIN,
            )
        )

        restored = read_contract(ctx["contract"]["id"])
        assert float(restored["base_committed_value_usd"]) == BASE_VALUE_USD
        assert float(restored["volume_discount_pct"]) == DISCOUNT_PCT, (
            "the discount tier must be re-selected from the restored base, not left "
            "at the 0.025 the amendment reached"
        )
        assert float(restored["volume_discount_usd"]) == DISCOUNT_USD
        assert float(restored["accessorial_allowance_pct"]) == ALLOWANCE_PCT
        assert float(restored["accessorial_allowance_usd"]) == ALLOWANCE_USD
        assert float(restored["total_committed_value_usd"]) == TOTAL_VALUE_USD

    def test_the_revert_restores_the_basis_and_keeps_the_mini_bid_as_audit(self):
        """State 2: the record swap that makes the money come back, and the trail of it.

        PRD §3.9: "The replacement rate record moves from `LIVE` to the terminal
        `ROLLED_BACK`. The record it had superseded moves from `SUPERSEDED` back to
        `LIVE`, and its `superseded_by_rate_record_id` is cleared to null."
        PRD §3.9: "The mini-bid records `revert_reason` and sets `reverted_at` from the
        logical clock, then moves from `APPLIED` to the terminal `REVERTED`."
        PRD §3.9: "The event's `award_cost_usd` and `savings_pct` are recomputed."

        Design: Difficulty/compensating_invariant/contract_money_conservation_across_mini_bid_apply_and_revert
        """
        ctx = self._applied_mini_bid()
        get_success_data(
            api_client.revert_mini_bid(
                ctx["mini_bid"]["id"],
                mini_bid_revert_payload(revert_reason=REVERT_REASON),
                CONTRACT_ADMIN,
            )
        )

        replacement = read_rate_record(ctx["replacement_record"]["id"])
        assert replacement["status"] == "ROLLED_BACK"
        original = read_rate_record(ctx["rate_record"]["id"])
        assert original["status"] == "LIVE"
        assert original["superseded_by_rate_record_id"] is None

        mini_bid = read_mini_bid(ctx["mini_bid"]["id"])
        assert mini_bid["status"] == "REVERTED"
        assert mini_bid["revert_reason"] == REVERT_REASON
        assert_same_instant(mini_bid["reverted_at"], APPLY_INSTANT, "reverted_at")
        assert mini_bid["applied_rate_record_id"] == replacement["id"], (
            "the reversed adjustment is kept as an audit trail, not erased"
        )

        event = read_event(ctx["event"]["id"])
        assert float(event["award_cost_usd"]) == TOTAL_VALUE_USD
        assert float(event["savings_pct"]) == SAVINGS_PCT_BEFORE
