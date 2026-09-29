"""Pooling completion and the donation obligation it assesses."""
from test_helpers import (
    create_eligible_carrier,
    create_submitted_filing,
    load_block,
    load_held_blocks,
    pooling_transition,
    read_block,
    read_carrier,
    read_rate_center,
    set_clock,
    setup_npa_with_rate_center,
)


def _incumbent_holder_of_five_blocks():
    """Carrier A holding five activated blocks, the oldest of them dirty, at 68.89."""
    set_clock()
    carrier = create_eligible_carrier("A")
    npa, rate_center = setup_npa_with_rate_center()
    dirty = load_block(
        npa, rate_center, nxx_code="555", thousands_digit=0, contaminated_count=40,
        holder_carrier_id=carrier["id"], mark_activated=True,
    )
    clean = load_held_blocks(
        npa, rate_center, carrier, 4, nxx_code="555", first_thousands_digit=1,
        mark_activated=True,
    )
    create_submitted_filing(
        carrier, rate_center,
        numbers_assigned=2500, numbers_intermediate=400, numbers_reserved=200,
        numbers_aging=200, numbers_administrative=300,
        blocks_held_at_period_end=5, forecast_quarters=[1800, 1200, 900, 600],
    )
    pooling_transition(rate_center, "BEGIN_POOLING")
    return {
        "carrier": carrier,
        "npa": npa,
        "rate_center": rate_center,
        "dirty": dirty,
        "clean": clean,
    }


class TestDonationObligationIsPinnedPreDonation:
    """The donation rate is read once, before any block leaves the carrier."""

    def test_five_blocks_at_sixty_eight_point_eight_nine_owe_exactly_one_block(self):
        """The twenty-five percent band on a holding of five discards the fraction and
        yields one block, and a rate recomputed after the move would yield none.

        Consider a carrier holding 5 blocks whose filing reports 3100 numbers in use
        against a denominator of 4500, an effective utilization of 68.89. That falls
        in the twenty-five percent band, so the obligation is five blocks times one
        quarter with the fraction discarded, which is 1 block.

        Design: Difficulty/combinatorial_formula/pooling_donation_obligation_pre_donation_tier_pinned
        """
        scenario = _incumbent_holder_of_five_blocks()

        pooling_transition(
            scenario["rate_center"], "COMPLETE_POOLING",
            pooling_effective_at="2026-08-01T00:00:00Z",
        )

        rate_center = read_rate_center(scenario["rate_center"]["id"])
        assert rate_center["pooling_status"] == "POOLED"
        assert rate_center["last_donation_block_count"] == 1
        assert rate_center["donation_shortfall_count"] == 0
        assert rate_center["available_block_count"] == 1
        assert read_carrier(scenario["carrier"]["id"])["blocks_held_count"] == 4

    def test_the_dirtiest_eligible_block_is_the_one_surrendered(self):
        """The donation ranking is the mirror image of the pool draw, so the block
        carrying forty contaminated numbers goes and the pristine four stay.

        Each donated block moves from `RESERVED` or `ASSIGNED` to `POOL_AVAILABLE` with

        Design: Difficulty/combinatorial_formula/pooling_donation_obligation_pre_donation_tier_pinned
        """
        scenario = _incumbent_holder_of_five_blocks()

        pooling_transition(
            scenario["rate_center"], "COMPLETE_POOLING",
            pooling_effective_at="2026-08-01T00:00:00Z",
        )

        donated = read_block(scenario["dirty"]["id"])
        assert donated["allocation_status"] == "POOL_AVAILABLE"
        assert donated["holder_carrier_id"] is None
        assert donated["assigned_at"] is None
        assert donated["activation_due_at"] is None
        assert donated["activated_at"] is None
        assert donated["contaminated_count"] == 40

        for block in scenario["clean"]:
            retained = read_block(block["id"])
            assert retained["allocation_status"] == "ASSIGNED"
            assert retained["holder_carrier_id"] == scenario["carrier"]["id"]
