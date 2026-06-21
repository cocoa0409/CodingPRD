"""Lien amount: principal summed before the admin-fee tier is selected, and the
admin-rate tier boundary at 500,000 cents.

PRD coverage: §3.12 (principal = open citation + open abatement; admin fee keyed on
the fully summed principal at 0.05 below / 0.10 at-or-above 500,000; total =
principal + admin fee), §2.6 (round-half-up once on the admin-fee product).
"""
from test_helpers import validate_success
from test_helpers import assert_lien_total_consistent
from test_helpers import fixtures as F


CLERK = F.CLERK


def _setup_capped_citation_plus_abatement(abatement_cost):
    """Issue a MAJOR notice, drive it 200 days overdue (citation capped at 100000),
    then complete a BOARD_UP abatement of `abatement_cost`, leaving both fines OPEN.
    Returns the context dict (case under key 'case')."""
    ctx = F.setup_issued_notice("MAJOR", clock="2026-01-01T00:00:00Z")
    F.set_clock("2026-08-03T00:00:00Z")  # >200 days overdue -> citation capped at 100000
    F.complete_abatement(ctx["case"]["id"], "BOARD_UP", actual_cost_cents=abatement_cost)
    return ctx


# ==========================================================================
# Difficulty: combinatorial_formula / lien_admin_fee_circular_principal_dependency
# ==========================================================================
def test_lien_principal_summed_before_admin_tier_high_rate(api):
    """PRD §3.12: "The `principal_cents` is the sum of `assessed_cents` over the
    case's `OPEN` citation fines plus the sum of `assessed_cents` over the case's
    `OPEN` abatement-cost fines; settled and waived lines are excluded."
    PRD §3.12: "the `admin_fee_cents` is the principal multiplied by an admin rate
    of `0.05` when the principal is below 500,000 cents, or `0.10` when the
    principal is at or above 500,000 cents, with that product rounded half-up to
    the nearest whole cent. The `total_cents` is the principal plus the
    administrative fee."

    Design: Difficulty/combinatorial_formula/lien_admin_fee_circular_principal_dependency
    """
    ctx = _setup_capped_citation_plus_abatement(400000)
    lien = F.record_lien(ctx["case"]["id"])
    # principal = 100000 (capped citation) + 400000 (abatement) = 500000
    assert lien["principal_cents"] == 500000, (
        f"expected principal 500000, got {lien['principal_cents']}"
    )
    # principal >= 500000 -> 0.10 rate -> 50000
    assert lien["admin_fee_cents"] == 50000, (
        f"expected admin_fee 50000 (0.10 tier), got {lien['admin_fee_cents']}"
    )
    assert lien["total_cents"] == 550000, f"expected total 550000, got {lien['total_cents']}"
    assert_lien_total_consistent(lien)


def test_lien_principal_summed_before_admin_tier_low_rate(api):
    """PRD §3.12: "The `principal_cents` is the sum of `assessed_cents` over the
    case's `OPEN` citation fines plus the sum of `assessed_cents` over the case's
    `OPEN` abatement-cost fines; settled and waived lines are excluded."
    PRD §3.12: "the `admin_fee_cents` is the principal multiplied by an admin rate
    of `0.05` when the principal is below 500,000 cents, or `0.10` when the
    principal is at or above 500,000 cents"

    Design: Difficulty/combinatorial_formula/lien_admin_fee_circular_principal_dependency
    """
    ctx = _setup_capped_citation_plus_abatement(300000)
    lien = F.record_lien(ctx["case"]["id"])
    # principal = 100000 (capped citation) + 300000 (abatement) = 400000 (< 500000)
    assert lien["principal_cents"] == 400000, (
        f"expected principal 400000, got {lien['principal_cents']}"
    )
    # principal < 500000 -> 0.05 rate -> 20000
    assert lien["admin_fee_cents"] == 20000, (
        f"expected admin_fee 20000 (0.05 tier), got {lien['admin_fee_cents']}"
    )
    assert lien["total_cents"] == 420000, f"expected total 420000, got {lien['total_cents']}"
    assert_lien_total_consistent(lien)


# ==========================================================================
# Difficulty: boundary_precision_check / lien_admin_tier_boundary_at_500000
# ==========================================================================
def test_lien_admin_tier_selected_at_exact_boundary(api):
    """PRD §3.12: "the `admin_fee_cents` is the principal multiplied by an admin
    rate of `0.05` when the principal is below 500,000 cents, or `0.10` when the
    principal is at or above 500,000 cents"

    Design: Difficulty/boundary_precision_check/lien_admin_tier_boundary_at_500000
    """
    ctx = _setup_capped_citation_plus_abatement(400000)
    lien = F.record_lien(ctx["case"]["id"])
    # principal exactly 500000 -> at-or-above tier -> 0.10
    assert lien["principal_cents"] == 500000, (
        f"expected principal exactly 500000, got {lien['principal_cents']}"
    )
    assert lien["admin_fee_cents"] == 50000, (
        f"expected 50000 (0.10 because principal >= 500000), got {lien['admin_fee_cents']}"
    )
    assert_lien_total_consistent(lien)


def test_lien_admin_tier_just_below_boundary_uses_low_rate(api):
    """PRD §3.12: "the `admin_fee_cents` is the principal multiplied by an admin
    rate of `0.05` when the principal is below 500,000 cents, or `0.10` when the
    principal is at or above 500,000 cents, with that product rounded half-up to the
    nearest whole cent."

    Design: Difficulty/boundary_precision_check/lien_admin_tier_boundary_at_500000
    """
    # principal = 100000 capped citation + 399999 abatement = 499999 (one below tier)
    ctx = _setup_capped_citation_plus_abatement(399999)
    lien = F.record_lien(ctx["case"]["id"])
    assert lien["principal_cents"] == 499999, (
        f"expected principal 499999, got {lien['principal_cents']}"
    )
    # 499999 < 500000 -> 0.05 rate -> round_half_up(24999.95) = 25000
    assert lien["admin_fee_cents"] == 25000, (
        f"expected 25000 (0.05 tier, half-up), got {lien['admin_fee_cents']}"
    )
    assert_lien_total_consistent(lien)
