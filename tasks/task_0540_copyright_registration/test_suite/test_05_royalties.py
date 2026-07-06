"""Royalty statement accrual (GROSS/NET), waterfall distribution, period-overlap
validation, escrow conservation, and the temporal-beats-constraint precedence.

Covers Difficulty queue instances royalty_accrual_gross_vs_net,
royalty_distribution_round_then_allocate, royalty_period_overlap_closed,
royalty_reverse_conserves_escrow, royalty_statement_temporal_beats_constraint,
plus the post-on-terminated corner instance.
"""
from test_helpers import validate_success, validate_error, validate_paginated, ApiErrorId
from test_helpers import factories as fac
from test_helpers import fixtures as fx


# ==========================================================================
# Difficulty — royalty_accrual_gross_vs_net
# ==========================================================================
def test_gross_basis_accrual(api, rightsholder_headers):
    """PRD §3.6: "Under a GROSS basis, the accrued amount is the gross_revenue_cents
    multiplied by the royalty_rate_bps, divided by 10000, and rounded half-up to
    the nearest whole cent; the deduction_cents is ignored."

    Design: Difficulty/dual_variant_calc/royalty_accrual_gross_vs_net
    """
    _work, _lic, rs = fx.setup_license_with_draft_statement(
        license_overrides={"royalty_basis": "GROSS", "royalty_rate_bps": 1500},
        statement_overrides={"gross_revenue_cents": 22220, "deduction_cents": 2220},
    )
    posted = validate_success(api.post_royalty_statement(rs["id"], rightsholder_headers), 200)
    assert posted["accrued_cents"] == 3333, "22220 * 1500 / 10000 = 3333 (deduction ignored)"


def test_net_basis_accrual(api, rightsholder_headers):
    """PRD §3.6: "Under a NET basis, the deduction_cents is first subtracted from the
    gross_revenue_cents, and that net amount is then multiplied by the
    royalty_rate_bps, divided by 10000, and rounded half-up to the nearest whole
    cent."

    Design: Difficulty/dual_variant_calc/royalty_accrual_gross_vs_net
    """
    _work, _lic, rs = fx.setup_license_with_draft_statement(
        license_overrides={"royalty_basis": "NET", "royalty_rate_bps": 1500, "right_type": "DISTRIBUTION"},
        statement_overrides={"gross_revenue_cents": 22220, "deduction_cents": 2220},
    )
    posted = validate_success(api.post_royalty_statement(rs["id"], rightsholder_headers), 200)
    assert posted["accrued_cents"] == 3000, "(22220 - 2220) * 1500 / 10000 = 3000"


# ==========================================================================
# Difficulty — royalty_distribution_round_then_allocate
# ==========================================================================
def _posted_multi_owner_statement(api, rh):
    work, lic = fx.setup_registered_work_with_license(
        work_overrides={"work_type": "MUSICAL", "owner_shares": [
            {"name": "A", "share_bps": 5000},
            {"name": "B", "share_bps": 3000},
            {"name": "C", "share_bps": 2000},
        ]},
        license_overrides={"royalty_basis": "GROSS", "royalty_rate_bps": 1500},
    )
    rs = fx.create_draft_statement(lic["id"], gross_revenue_cents=22220)
    fx.post_statement(rs["id"])
    return rs


def test_distribution_waterfall_amounts(api, rightsholder_headers):
    """PRD §3.6: "For each owner, a base amount is computed as the accrued_cents
    multiplied by that owner's share_bps, divided by 10000, and then floored to a
    whole cent. The remainder ... is then distributed one cent at a time to owners
    taken in order of descending share_bps, breaking ties by the owner's position
    in the owner_shares list (earliest position first, never by any identifier),
    until the remainder is exhausted."

    Design: Difficulty/combinatorial_formula/royalty_distribution_round_then_allocate
    """
    rs = _posted_multi_owner_statement(api, rightsholder_headers)
    distributed = validate_success(api.distribute_royalty_statement(rs["id"], rightsholder_headers), 200)
    # accrued 3333: floors A=1666,B=999,C=666 (sum 3331); remainder 2 -> A,B (highest shares).
    assert distributed["distribution"] == [
        {"name": "A", "amount_cents": 1667},
        {"name": "B", "amount_cents": 1000},
        {"name": "C", "amount_cents": 666},
    ]


def test_distributed_total_equals_accrued(api, rightsholder_headers):
    """PRD §3.6: "distributed_cents is set to the sum, which by construction equals
    accrued_cents."

    Design: Difficulty/combinatorial_formula/royalty_distribution_round_then_allocate
    """
    rs = _posted_multi_owner_statement(api, rightsholder_headers)
    distributed = validate_success(api.distribute_royalty_statement(rs["id"], rightsholder_headers), 200)
    assert distributed["distributed_cents"] == 3333
    assert distributed["distributed_cents"] == distributed["accrued_cents"]


# ==========================================================================
# Difficulty — royalty_period_overlap_closed
# ==========================================================================
def test_shared_endpoint_period_rejected(api, rightsholder_headers):
    """PRD §3.6: "a new period that overlaps an existing statement of the same
    license which is neither REVERSED nor VOIDED, measured over the closed period
    interval, is rejected with ERR_PERIOD_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/royalty_period_overlap_closed
    """
    _work, lic, _posted = fx.setup_license_with_posted_statement(
        statement_overrides={"period_start": "2026-01-01T00:00:00Z", "period_end": "2026-03-31T00:00:00Z"},
    )
    overlapping = fac.create_royalty_statement_payload(
        lic["id"], period_start="2026-03-31T00:00:00Z", period_end="2026-06-30T00:00:00Z",
        gross_revenue_cents=5000,
    )
    validate_error(api.create_royalty_statement(overlapping, rightsholder_headers), ApiErrorId.ERR_PERIOD_OVERLAP)


def test_nonoverlapping_period_allowed(api, rightsholder_headers):
    """PRD §3.6: "Two statements for the same license may not cover overlapping
    periods ... measured over the closed period interval."

    Design: Difficulty/resource_temporal_overlap/royalty_period_overlap_closed
    """
    _work, lic, _posted = fx.setup_license_with_posted_statement(
        statement_overrides={"period_start": "2026-01-01T00:00:00Z", "period_end": "2026-03-31T00:00:00Z"},
    )
    disjoint = fac.create_royalty_statement_payload(
        lic["id"], period_start="2026-04-01T00:00:00Z", period_end="2026-06-30T00:00:00Z",
        gross_revenue_cents=5000,
    )
    data = validate_success(api.create_royalty_statement(disjoint, rightsholder_headers), 201)
    assert data["status"] == "DRAFT"


# ==========================================================================
# Difficulty — royalty_reverse_conserves_escrow
# ==========================================================================
def test_reverse_returns_escrow_to_zero(api, rightsholder_headers):
    """PRD §3.6: "Reversing a statement moves it from POSTED to REVERSED and removes
    its accrued amount from the license's escrow_balance_cents."

    Design: Difficulty/compensating_invariant/royalty_reverse_conserves_escrow
    """
    _work, lic, posted = fx.setup_license_with_posted_statement(
        license_overrides={"royalty_basis": "GROSS", "royalty_rate_bps": 1500},
        statement_overrides={"gross_revenue_cents": 22220},
    )
    reversed_rs = validate_success(api.reverse_royalty_statement(posted["id"], rightsholder_headers), 200)
    assert reversed_rs["status"] == "REVERSED"
    assert fx.get_license(lic["id"])["escrow_balance_cents"] == 0


def test_post_then_reverse_leaves_escrow_unchanged(api, rightsholder_headers):
    """PRD §3.6: "Reversal is a compensating action: a statement that is posted and
    then reversed leaves the escrow balance exactly as it was before posting."

    Design: Difficulty/compensating_invariant/royalty_reverse_conserves_escrow
    """
    _work, lic, rs = fx.setup_license_with_draft_statement(
        license_overrides={"royalty_basis": "GROSS", "royalty_rate_bps": 1500},
        statement_overrides={"gross_revenue_cents": 22220},
    )
    assert fx.get_license(lic["id"])["escrow_balance_cents"] == 0
    fx.post_statement(rs["id"])
    assert fx.get_license(lic["id"])["escrow_balance_cents"] == 3333
    validate_success(api.reverse_royalty_statement(rs["id"], rightsholder_headers), 200)
    assert fx.get_license(lic["id"])["escrow_balance_cents"] == 0


# ==========================================================================
# Difficulty — royalty_statement_temporal_beats_constraint
# ==========================================================================
def test_inverted_and_overlapping_period_returns_date_range(api, rightsholder_headers):
    """PRD §2.6: "the remaining business, temporal, and fiscal constraints are
    evaluated last, in the order in which the business narrative of §3 describes
    them."
    PRD §3.6: "period_start must fall strictly before period_end, otherwise
    ERR_INVALID_DATE_RANGE. Two statements for the same license may not cover
    overlapping periods: a new period that overlaps an existing statement ... is
    rejected with ERR_PERIOD_OVERLAP."

    Design: Difficulty/priority_pair_validation_conflict/royalty_statement_temporal_beats_constraint
    """
    _work, lic, _posted = fx.setup_license_with_posted_statement(
        statement_overrides={"period_start": "2026-01-01T00:00:00Z", "period_end": "2026-03-31T00:00:00Z"},
    )
    # period_end < period_start (inverted) AND the range brushes the posted period.
    bad = fac.create_royalty_statement_payload(
        lic["id"], period_start="2026-02-01T00:00:00Z", period_end="2026-01-15T00:00:00Z",
        gross_revenue_cents=5000,
    )
    validate_error(api.create_royalty_statement(bad, rightsholder_headers), ApiErrorId.ERR_INVALID_DATE_RANGE)


def test_inverted_overlapping_period_creates_no_statement(api, rightsholder_headers):
    """PRD §3.6: "period_start must fall strictly before period_end, otherwise
    ERR_INVALID_DATE_RANGE." (A rejected create persists nothing.)

    Design: Difficulty/priority_pair_validation_conflict/royalty_statement_temporal_beats_constraint
    """
    _work, lic, _posted = fx.setup_license_with_posted_statement(
        statement_overrides={"period_start": "2026-01-01T00:00:00Z", "period_end": "2026-03-31T00:00:00Z"},
    )
    bad = fac.create_royalty_statement_payload(
        lic["id"], period_start="2026-02-01T00:00:00Z", period_end="2026-01-15T00:00:00Z",
        gross_revenue_cents=5000,
    )
    api.create_royalty_statement(bad, rightsholder_headers)
    data, meta = validate_paginated(api.list_royalty_statements(rightsholder_headers, params={"license_id": lic["id"]}))
    assert meta["total_count"] == 1, "only the pre-existing POSTED statement should remain"


# ==========================================================================
# Corner — post on a terminated license
# ==========================================================================
def test_post_on_terminated_license_rejected(api, rightsholder_headers, examiner_headers):
    """PRD §3.6: "Posting is only allowed while the parent license is ACTIVE; a post
    against a license that is not ACTIVE is rejected with ERR_LICENSE_NOT_ACTIVE."
    PRD §3.7: "every royalty statement under that license which is POSTED is moved
    to REVERSED" (a DRAFT statement is left untouched by termination).

    Design: Corner/validations/royalty_post_on_terminated_license_returns_error
    """
    _work, lic, term = fx.setup_license_for_termination(effective_date="2026-06-01T00:00:00Z")
    rs = fx.create_draft_statement(lic["id"])
    fx.get_success_data(api.effectuate_termination(term["id"], examiner_headers))
    assert fx.get_license(lic["id"])["status"] == "TERMINATED"
    validate_error(api.post_royalty_statement(rs["id"], rightsholder_headers), ApiErrorId.ERR_LICENSE_NOT_ACTIVE)
