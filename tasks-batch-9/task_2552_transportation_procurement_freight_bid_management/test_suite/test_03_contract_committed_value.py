"""A contract's committed value: two tier tables read against two different bases."""

from test_helpers import (
    assert_contract_value_derivation,
    read_contract,
    stage_rate_record,
    two_lane_awarded_event,
)


def _stage(ctx, index: int, committed_volume_loads: int):
    """Stages the rate record implementing the allocation on lane `index`."""
    return stage_rate_record(
        ctx["contract"]["id"],
        ctx["lanes"][index]["id"],
        ctx["carrier"]["id"],
        ctx["allocations"][index]["id"],
        rate_per_mile=2.0000,
        fuel_surcharge_included=True,
        committed_volume_loads=committed_volume_loads,
    )


class TestCommittedValueTiers:
    """The volume discount keys on the base; the allowance keys on the subtotal."""

    def test_committed_value_is_zero_until_a_rate_record_is_staged(self):
        """A freshly awarded contract has an empty rate basis and no committed value.

        PRD §3.7: "Each contract is created with `status` `DRAFT`, `signature_status`
        `PENDING_BOTH`, `rate_load_status` `NOT_STAGED`, `amendment_count` `0`,
        `rate_record_count` `0`".
        PRD §3.8: "The contract's `base_committed_value_usd` is the sum of the in-basis
        records' `committed_value_usd`, rounded to 2 decimal places."

        Design: Difficulty/combinatorial_formula/contract_committed_value_pinned_tier_evaluation_order
        """
        ctx = two_lane_awarded_event()
        contract = ctx["contract"]

        assert contract is not None, "the award cascade must mint a contract"
        assert contract["rate_record_count"] == 0, (
            f"no rate record has been staged, got {contract['rate_record_count']}"
        )
        assert contract["rate_load_status"] == "NOT_STAGED", (
            f"a contract with no staged rate is NOT_STAGED, "
            f"got {contract['rate_load_status']}"
        )
        assert contract["base_committed_value_usd"] == 0.00, (
            f"an empty basis sums to 0.00, got {contract['base_committed_value_usd']}"
        )
        assert contract["total_committed_value_usd"] == 0.00, (
            f"an empty basis carries no committed value, "
            f"got {contract['total_committed_value_usd']}"
        )

    def test_one_staged_record_lands_in_the_middle_volume_discount_tier(self):
        """A base of 1376400.00 discounts at 0.015 and then allows at 0.020.

        PRD §3.8: "Multiply the lane's `mileage` by that effective rate and round to 2
        decimal places; multiply that already-rounded figure by the record's
        `committed_volume_loads` and round to 2 decimal places. That is the record's
        `committed_value_usd`."
        PRD §3.8: "The contract's `volume_discount_pct` is selected from
        `base_committed_value_usd`: below `500000` it is `0.000`; from `500000` up to
        but not including `1500000` it is `0.015`; at `1500000` and above it is
        `0.025`."
        PRD §3.8: "Add `accessorial_allowance_usd` to the post-discount subtotal and
        round to 2 decimal places. That is `total_committed_value_usd`."

        Design: Difficulty/combinatorial_formula/contract_committed_value_pinned_tier_evaluation_order
        """
        ctx = two_lane_awarded_event()
        record = _stage(ctx, 0, 600)
        contract = read_contract(ctx["contract"]["id"])

        assert record["committed_value_usd"] == 1376400.00, (
            f"1147 miles at 2.0000 is 2294.00 a load over 600 loads, "
            f"got {record['committed_value_usd']}"
        )
        assert contract["base_committed_value_usd"] == 1376400.00, (
            f"the single in-basis record sets the base, "
            f"got {contract['base_committed_value_usd']}"
        )
        assert contract["volume_discount_pct"] == 0.015, (
            f"1376400.00 sits in the 500000-to-1500000 tier, "
            f"got {contract['volume_discount_pct']}"
        )
        assert contract["volume_discount_usd"] == 20646.00, (
            f"1376400.00 x 0.015 is 20646.00, got {contract['volume_discount_usd']}"
        )
        assert contract["accessorial_allowance_usd"] == 27115.08, (
            f"the 1355754.00 subtotal x 0.020 is 27115.08, "
            f"got {contract['accessorial_allowance_usd']}"
        )
        assert contract["total_committed_value_usd"] == 1382869.08, (
            f"1355754.00 + 27115.08 is 1382869.08, "
            f"got {contract['total_committed_value_usd']}"
        )

    def test_allowance_tier_reads_the_post_discount_subtotal_not_the_base(self):
        """A base of 1520400.00 discounts at 0.025; the allowance keys on 1482390.00.

        PRD §3.8: "The contract's `accessorial_allowance_pct` is selected from the
        **post-discount subtotal**, not from the base: below `400000` it is `0.000`;
        from `400000` up to but not including `1200000` it is `0.010`; at `1200000` and
        above it is `0.020`. Reading the base figure instead of the subtotal is a
        distinct and wrong answer for any contract whose discount pushes it across a
        tier boundary."
        PRD §3.8: "Multiply the base by `volume_discount_pct` and round to 2 decimal
        places to obtain `volume_discount_usd`. Subtract that from the base and round
        to 2 decimal places to obtain the post-discount subtotal."
        PRD §2.12: "`Contract.rate_record_count` counts the contract's rate records
        whose status is `STAGED`, `LOADED`, `LIVE` or `AT_RISK`."

        Design: Difficulty/combinatorial_formula/contract_committed_value_pinned_tier_evaluation_order
        """
        ctx = two_lane_awarded_event()
        record_a = _stage(ctx, 0, 600)
        record_b = _stage(ctx, 1, 120)
        contract = read_contract(ctx["contract"]["id"])

        assert record_b["committed_value_usd"] == 144000.00, (
            f"600 miles at 2.0000 is 1200.00 a load over 120 loads, "
            f"got {record_b['committed_value_usd']}"
        )
        assert contract["base_committed_value_usd"] == 1520400.00, (
            f"1376400.00 + 144000.00 is 1520400.00, "
            f"got {contract['base_committed_value_usd']}"
        )
        assert contract["volume_discount_pct"] == 0.025, (
            f"1520400.00 is at or above the 1500000 tier floor, "
            f"got {contract['volume_discount_pct']}"
        )
        assert contract["volume_discount_usd"] == 38010.00, (
            f"1520400.00 x 0.025 is 38010.00, got {contract['volume_discount_usd']}"
        )
        assert contract["accessorial_allowance_pct"] == 0.020, (
            f"the 1482390.00 subtotal is at or above the 1200000 allowance floor, "
            f"got {contract['accessorial_allowance_pct']}"
        )
        assert contract["accessorial_allowance_usd"] == 29647.80, (
            f"1482390.00 x 0.020 is 29647.80, "
            f"got {contract['accessorial_allowance_usd']}"
        )
        assert contract["total_committed_value_usd"] == 1512037.80, (
            f"1482390.00 + 29647.80 is 1512037.80, "
            f"got {contract['total_committed_value_usd']}"
        )
        assert contract["total_committed_value_usd"] != 1512798.00, (
            "1512798.00 is the answer produced by keying the allowance on the base "
            "instead of the post-discount subtotal"
        )
        assert contract["rate_record_count"] == 2, (
            f"both staged records are in the basis, got {contract['rate_record_count']}"
        )
        assert_contract_value_derivation(contract, [record_a, record_b])
