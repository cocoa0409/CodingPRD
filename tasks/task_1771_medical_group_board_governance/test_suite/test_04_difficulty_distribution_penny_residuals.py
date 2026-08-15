"""Difficulty queue: nested rounding order — floor per allocation, then residual pennies."""
from test_helpers import (
    adopted_distribution,
    allocation_for,
    create_policy,
    create_shareholder,
)


class TestDistributionPennyResidualAllocationOrder:
    def test_residual_penny_to_largest_holder_by_created_at(self, api):
        """PRD §2.5: "Some quantities are deliberately floored rather than rounded:
        per-physician allocation and assessment amounts are floored, and the residual
        pennies that result are distributed one cent at a time to the largest holders,
        never by rounding each allocation."
        PRD §3.5: "Under the `PRO_RATA` method, each eligible physician's raw
        allocation is the total amount multiplied by their `shares_held` and divided by
        total eligible shares; each allocation is floored, and the residual pennies go
        one cent at a time to the physicians with the most shares, ties broken by
        `created_at` ascending."
        10000001 over 1000/1000/500 -> raw 4000000.4 / 4000000.4 / 2000000.2; A and B
        tie on shares so A (created first) takes the one residual cent.

        Design: Difficulty/combinatorial_formula/distribution_penny_residual_allocation_order
        """
        create_policy(total_shares_authorized=1000000, board_quorum_count=1)
        a = create_shareholder("Dr A", 1000, "2015-01-01T00:00:00Z")
        b = create_shareholder("Dr B", 1000, "2016-01-01T00:00:00Z")
        c = create_shareholder("Dr C", 500, "2025-01-01T00:00:00Z")
        _motion, distribution = adopted_distribution(a, 10000001, voters=[a])
        assert allocation_for(distribution, a["id"])["allocated_cents"] == 4000001, (
            "A takes the residual penny: shares tie 1000=1000 broken by created_at ASC"
        )
        assert allocation_for(distribution, b["id"])["allocated_cents"] == 4000000
        assert allocation_for(distribution, c["id"])["allocated_cents"] == 2000000

    def test_allocations_sum_to_total_no_cent_lost(self, api):
        """PRD §2.5: "Some quantities are deliberately floored rather than rounded:
        per-physician allocation and assessment amounts are floored, and the residual
        pennies that result are distributed one cent at a time to the largest holders,
        never by rounding each allocation."
        Rounding each allocation instead would drop the residual cent (4000000 +
        4000000 + 2000000 = 10000000 != 10000001); the floored-plus-residual rule keeps
        the sum exactly equal to the total.

        Design: Difficulty/combinatorial_formula/distribution_penny_residual_allocation_order
        """
        create_policy(total_shares_authorized=1000000, board_quorum_count=1)
        a = create_shareholder("Dr A", 1000, "2015-01-01T00:00:00Z")
        create_shareholder("Dr B", 1000, "2016-01-01T00:00:00Z")
        create_shareholder("Dr C", 500, "2025-01-01T00:00:00Z")
        _motion, distribution = adopted_distribution(a, 10000001, voters=[a])
        total_allocated = sum(al["allocated_cents"] for al in distribution["allocations"])
        assert total_allocated == 10000001, (
            f"allocations must sum to the distribution total exactly, got {total_allocated}"
        )
        assert total_allocated == distribution["total_amount_cents"]
