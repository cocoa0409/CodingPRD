"""Difficulty queue: dual-variant distribution allocation (PRO_RATA vs SENIORITY_TIERED)."""
from test_helpers import (
    adopted_distribution,
    allocation_for,
    create_policy,
    create_shareholder,
)

TOTAL = 10000001
NIBB = 800000000


def _setup_three_shareholders():
    """A 1000 shares (senior, created first), B 1000 (senior), C 500 (junior)."""
    create_policy(total_shares_authorized=1000000, board_quorum_count=1)
    a = create_shareholder("Dr A", 1000, "2015-01-01T00:00:00Z")
    b = create_shareholder("Dr B", 1000, "2016-01-01T00:00:00Z")
    c = create_shareholder("Dr C", 500, "2025-01-01T00:00:00Z")
    return a, b, c


class TestDistributionProRataVsSeniorityTieredDiverge:
    def test_pro_rata_allocations(self, api):
        """PRD §3.5: "Under the `PRO_RATA` method, each eligible physician's raw
        allocation is the total amount multiplied by their `shares_held` and divided by
        total eligible shares; each allocation is floored, and the residual pennies go
        one cent at a time to the physicians with the most shares, ties broken by
        `created_at` ascending."
        10000001 over 1000/1000/500: floors 4000000/4000000/2000000, one residual penny
        to A (shares tie 1000=1000, A created first).

        Design: Difficulty/dual_variant_calc/distribution_pro_rata_vs_seniority_tiered_diverge
        """
        a, b, c = _setup_three_shareholders()
        _motion, distribution = adopted_distribution(a, TOTAL, method="PRO_RATA", voters=[a])
        assert distribution["total_amount_cents"] == TOTAL
        assert allocation_for(distribution, a["id"])["allocated_cents"] == 4000001
        assert allocation_for(distribution, b["id"])["allocated_cents"] == 4000000
        assert allocation_for(distribution, c["id"])["allocated_cents"] == 2000000
        assert sum(al["allocated_cents"] for al in distribution["allocations"]) == TOTAL

    def test_seniority_tiered_allocations_diverge(self, api):
        """PRD §3.5: "Under the `SENIORITY_TIERED` method there are two stages, in
        pinned order. First the carve: `seniority_carve_pct` of the total, rounded
        half-up, is split equally among the seniors — eligible physicians whose
        `tenure_years` is at least `seniority_tier_years` — each floored, with carve
        residual pennies going one each in `created_at` ascending order. If no
        physician qualifies as senior, the carve stage is skipped and the entire total
        is allocated pro-rata. Second, the remainder after the carve is allocated
        pro-rata across all eligible physicians under the same floor-and-residual rule
        as `PRO_RATA`. The same inputs therefore produce different per-physician
        amounts under the two methods."
        carve = round(10000001 * 0.20) = 2000000 split equally A/B (1000000 each);
        remainder 8000001 pro-rata: A 3200000 + residual 1, B 3200000, C 1600000.

        Design: Difficulty/dual_variant_calc/distribution_pro_rata_vs_seniority_tiered_diverge
        """
        a, b, c = _setup_three_shareholders()
        _m1, pro_rata = adopted_distribution(a, TOTAL, method="PRO_RATA", voters=[a])
        _m2, tiered = adopted_distribution(a, TOTAL, method="SENIORITY_TIERED", voters=[b])
        assert allocation_for(tiered, a["id"])["allocated_cents"] == 4200001
        assert allocation_for(tiered, b["id"])["allocated_cents"] == 4200000
        assert allocation_for(tiered, c["id"])["allocated_cents"] == 1600000
        assert sum(al["allocated_cents"] for al in tiered["allocations"]) == TOTAL
        assert (
            allocation_for(pro_rata, a["id"])["allocated_cents"]
            != allocation_for(tiered, a["id"])["allocated_cents"]
        ), "identical inputs must yield different per-physician amounts under the two methods"
