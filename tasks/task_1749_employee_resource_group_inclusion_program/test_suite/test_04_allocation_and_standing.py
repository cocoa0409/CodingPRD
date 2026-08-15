"""Allocation waterfall and standing scores: largest-remainder rounding,
input-set filtering, and the certified-vs-provisional dual."""
import pytest

from test_helpers import (
    add_members,
    create_active_group,
    create_group_draft,
    create_open_program,
    create_sponsor,
    lock_allocation,
    validate_success,
)
from test_helpers.fixtures import DEI_HEADERS


class TestAllocationWaterfall:
    def test_waterfall_allocates_exact_largest_remainder_shares(self, api):
        """PRD §3.4: "Each eligible group's weight is its `active_member_count` multiplied by its category weight in tenths — 10 for `AFFINITY`, 12 for `PROFESSIONAL`, 15 for `COMMUNITY_OUTREACH`."
        PRD §3.4: "Each group's raw share is `pool_total_cents` multiplied by its weight and divided by the sum of weights over all eligible groups."
        PRD §3.4: "Each group's `allocated_cents` is its raw share rounded down to a whole cent."
        PRD §3.4: "The remainder — `pool_total_cents` minus the sum of the floored allocations — is distributed one cent at a time to groups in order of descending fractional part of their raw share, breaking ties by earlier `created_at` and then by `name` ascending."

        Design: Difficulty/combinatorial_formula/allocation_waterfall_largest_remainder
        """
        program = create_open_program(1000000)
        sponsor = create_sponsor("emp_sp3", max_groups=3, max_mentees=2)
        # Weights: 10x10=100, 10x12=120, 11x15=165 (sum 385).
        g1 = create_active_group(
            program["id"], sponsor["id"], "Alpha Alliance", "AFFINITY", "emp_l1"
        )
        g2 = create_active_group(
            program["id"], sponsor["id"], "Beta Builders", "PROFESSIONAL", "emp_l2"
        )
        g3 = create_active_group(
            program["id"], sponsor["id"], "Gamma Outreach", "COMMUNITY_OUTREACH",
            "emp_l3", member_ids=[f"emp_c{i:02d}" for i in range(1, 12)],
        )

        lock_allocation(program["id"])

        a1 = validate_success(api.get_group(g1["id"], DEI_HEADERS), 200)["allocated_cents"]
        a2 = validate_success(api.get_group(g2["id"], DEI_HEADERS), 200)["allocated_cents"]
        a3 = validate_success(api.get_group(g3["id"], DEI_HEADERS), 200)["allocated_cents"]
        assert a1 == 259740, f"floor of 259740.2597..., smallest fraction gets no cent; got {a1}"
        assert a2 == 311688, f"floor of 311688.3116..., middle fraction gets no cent; got {a2}"
        assert a3 == 428572, f"floor 428571 + 1 remainder cent (largest fraction); got {a3}"

    def test_waterfall_remainder_fully_distributes_pool(self, api):
        """PRD §3.4: "The lock also freezes each eligible group's `certified_standing_score` to the standing score computed from the aggregates as of the lock (see §3.8), and sets the program's `unallocated_pool_cents` to `pool_total_cents` minus the sum of allocated amounts."

        Design: Difficulty/combinatorial_formula/allocation_waterfall_largest_remainder
        """
        program = create_open_program(1000000)
        sponsor = create_sponsor("emp_sp3", max_groups=3, max_mentees=2)
        g1 = create_active_group(
            program["id"], sponsor["id"], "Alpha Alliance", "AFFINITY", "emp_l1"
        )
        g2 = create_active_group(
            program["id"], sponsor["id"], "Beta Builders", "PROFESSIONAL", "emp_l2"
        )
        g3 = create_active_group(
            program["id"], sponsor["id"], "Gamma Outreach", "COMMUNITY_OUTREACH",
            "emp_l3", member_ids=[f"emp_c{i:02d}" for i in range(1, 12)],
        )

        lock_allocation(program["id"])

        a1 = validate_success(api.get_group(g1["id"], DEI_HEADERS), 200)["allocated_cents"]
        a2 = validate_success(api.get_group(g2["id"], DEI_HEADERS), 200)["allocated_cents"]
        a3 = validate_success(api.get_group(g3["id"], DEI_HEADERS), 200)["allocated_cents"]
        program_data = validate_success(api.get_program(program["id"], DEI_HEADERS), 200)
        assert a1 + a2 + a3 == 1000000, "the whole pool is distributed"
        assert program_data["unallocated_pool_cents"] == 0

    def test_allocation_skips_non_active_groups(self, api):
        """PRD §3.4: "The lock runs the allocation waterfall over every group of the program whose status is `ACTIVE` at lock time:"

        Design: Corner/calculations/allocation_skips_non_active_groups
        """
        program = create_open_program(400000)
        sponsor = create_sponsor("emp_sp24", max_groups=3, max_mentees=2)
        group_a = create_active_group(
            program["id"], sponsor["id"], "Alloc A", "AFFINITY", "emp_l33"
        )
        # Group B never leaves CHARTER_DRAFT, so it is outside the waterfall input set.
        group_b = create_group_draft(program["id"], "Alloc B", "PROFESSIONAL", "emp_l34")

        lock_allocation(program["id"])

        data_a = validate_success(api.get_group(group_a["id"], DEI_HEADERS), 200)
        data_b = validate_success(api.get_group(group_b["id"], DEI_HEADERS), 200)
        assert data_a["allocated_cents"] == 400000, "sole eligible group gets the whole pool"
        assert data_b["allocated_cents"] == 0, "CHARTER_DRAFT group is excluded"


class TestStandingScoreDual:
    def test_certified_frozen_at_lock_while_provisional_moves(self, api):
        """PRD §3.8: "Every group read recomputes this live as `provisional_standing_score` from the current aggregates; the allocation lock freezes the same computation into `certified_standing_score`, which later activity cannot move."
        PRD §3.8: "The growth half is capped: `member_growth_pct` is the percentage by which `active_member_count` exceeds the `founding_member_count` snapshot relative to that snapshot, and the capped contribution is the lesser of 100 and that percentage. The standing score is the sum of half the engagement mean and half the capped growth percentage, rounded half-up to 2 decimal places."

        Design: Difficulty/dual_variant_calc/group_standing_provisional_vs_certified
        """
        program = create_open_program(100000)
        sponsor = create_sponsor("emp_sp2", max_groups=3, max_mentees=2)
        group = create_active_group(
            program["id"], sponsor["id"], "Beta Network", "PROFESSIONAL", "emp_l2"
        )
        # Lock with 10 founding members and no completed events: score 0.00.
        lock_allocation(program["id"])
        # Ten more members join after the lock.
        add_members(group["id"], [f"emp_g{i:02d}" for i in range(1, 11)])

        data = validate_success(api.get_group(group["id"], DEI_HEADERS), 200)
        assert data["certified_standing_score"] == pytest.approx(0.00), (
            "frozen at lock: growth 0, no COMPLETED events"
        )
        assert data["provisional_standing_score"] == pytest.approx(50.00), (
            "0.5*0 + 0.5*min(100, 100*(20-10)/10)"
        )

    def test_sole_eligible_group_receives_whole_pool(self, api):
        """PRD §3.4: "When no eligible groups exist, the entire pool remains unallocated."
        PRD §3.4: "Each group's raw share is `pool_total_cents` multiplied by its weight and divided by the sum of weights over all eligible groups."

        Design: Difficulty/dual_variant_calc/group_standing_provisional_vs_certified
        """
        program = create_open_program(100000)
        sponsor = create_sponsor("emp_sp2", max_groups=3, max_mentees=2)
        group = create_active_group(
            program["id"], sponsor["id"], "Beta Network", "PROFESSIONAL", "emp_l2"
        )
        lock_allocation(program["id"])
        add_members(group["id"], [f"emp_g{i:02d}" for i in range(1, 11)])

        data = validate_success(api.get_group(group["id"], DEI_HEADERS), 200)
        assert data["active_member_count"] == 20
        assert data["allocated_cents"] == 100000, (
            "single eligible group receives the whole pool"
        )
