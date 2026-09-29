"""Per-line rounding in the allocation waterfall.

The reconstruction uplift is rounded half up as each line is computed, and the
lines are only then summed. Rounding once at the end differs by a cent, and
these gross amounts are chosen so that cent is visible.
"""
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    allocation_line,
    assert_allocation_line_order,
    assert_claim_incurred_identity,
    assert_no_allocation_line,
)
from test_helpers.factories import loss_item

ROUNDING_SENSITIVE_PART_PLAN = (
    ("MATERIALS_ON_SITE", 1000000000),
    ("IN_TRANSIT", 200000000),
    ("SOFT_COST", 300000000),
)

ROUNDING_SENSITIVE_ITEMS = [
    loss_item("MATERIALS_ON_SITE", 45678920),
    loss_item("IN_TRANSIT", 12345670),
]


def _adjusted_on_reconstruction_basis():
    account = fx.in_force_account(parts=ROUNDING_SENSITIVE_PART_PLAN)
    claim = fx.adjusted_claim(
        account,
        ROUNDING_SENSITIVE_ITEMS,
        adjustment_basis="RECONSTRUCTION_COST",
        continuing_pm_weeks=0,
    )
    return account, claim


def test_each_line_is_uplifted_and_rounded_on_its_own_before_the_lines_are_summed():
    """Under RECONSTRUCTION_COST each line's covered_basis_cents is its
    gross_loss_cents multiplied by 1.08 and rounded half up at once, so
    45678920 becomes 49333234 and 12345670 becomes 13333324. Summing the
    unrounded products and rounding once is not the rule.

    Design: Difficulty/combinatorial_formula/claim_allocation_round_per_line_then_sum_mode_b
    """
    _, claim = _adjusted_on_reconstruction_basis()

    materials = allocation_line(claim, "MATERIALS_ON_SITE")
    in_transit = allocation_line(claim, "IN_TRANSIT")

    assert materials["covered_basis_cents"] == 49333234, (
        f"round_half_up(45678920 * 1.08) is 49333234, "
        f"got {materials['covered_basis_cents']}")
    assert in_transit["covered_basis_cents"] == 13333324, (
        f"round_half_up(12345670 * 1.08) is 13333324, "
        f"got {in_transit['covered_basis_cents']}")
    assert_allocation_line_order(claim)


def test_the_indemnity_carries_the_per_line_rounding_and_no_management_line():
    """The claim's indemnity_cents is the sum of the per-line allocations after
    the occurrence deductible bites the largest non-delay line once, giving
    52666558; the forbidden sum-then-round order would yield 52666557. With
    continuing_pm_weeks at zero the project-management amount is exactly zero,
    so no SOFT_COST line is appended.

    Design: Difficulty/combinatorial_formula/claim_allocation_round_per_line_then_sum_mode_b
    """
    _, claim = _adjusted_on_reconstruction_basis()

    assert claim["indemnity_cents"] == 52666558, (
        "49333234 less the 10000000 deductible plus 13333324, "
        f"got {claim['indemnity_cents']}")
    assert len(claim["allocation_lines"]) == 2, claim["allocation_lines"]
    assert_no_allocation_line(claim, "SOFT_COST")
    assert claim["uncovered_cents"] == 10000000, claim["uncovered_cents"]
    assert_claim_incurred_identity(claim)
