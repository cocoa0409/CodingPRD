"""Ledger cascades: the depth-4 disbursement chain on closing completion, the
depth-2 release chain on award cancellation, and the conservation of the
funding pool across reserve-then-cancel.

Difficulty:
  transitive_cascade / closing_complete_disbursement_chain_depth4
  transitive_cascade / award_cancel_release_chain_depth2
  compensating_invariant / funding_pool_conserved_on_award_cancel
"""
from test_helpers import validate_success
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_funding_source_ledger_invariant

CASE_MANAGER = fx.CASE_MANAGER
SERVICER = fx.SERVICER


# --- transitive_cascade / closing_complete_disbursement_chain_depth4 --------
def test_closing_complete_disburses_allocation_and_advances_award(api):
    """PRD 3.6: "A successful completion moves the closing to `COMPLETED` and
    drives a four-hop cascade that carries the award from `FUNDED` to
    `SERVICING`:"
    PRD 3.6: "Every allocation still `RESERVED` after reconciliation transitions
    to `DISBURSED`."

    Design: Difficulty/transitive_cascade/closing_complete_disbursement_chain_depth4
    """
    ctx = fx.setup_servicing_account(api)  # completes the closing end-to-end
    allocation = validate_success(api.get_funding_allocation(ctx["allocation"]["id"], CASE_MANAGER), 200)
    award = validate_success(api.get_award(ctx["award"]["id"], CASE_MANAGER), 200)
    assert allocation["status"] == "DISBURSED", f"expected DISBURSED, got {allocation['status']}"
    assert award["status"] == "SERVICING", f"expected SERVICING, got {award['status']}"


def test_closing_complete_moves_source_reserved_to_disbursed(api):
    """PRD 3.6: "For each, the amount moves from that funding source's
    `reserved_cents` to its `disbursed_cents`; and if the source's
    `available_cents` and `reserved_cents` have both reached zero, the source
    flips to `FULLY_COMMITTED`."

    Design: Difficulty/transitive_cascade/closing_complete_disbursement_chain_depth4
    """
    # 5,000,000 drawn from a 10,000,000 source, disbursed in full at closing.
    ctx = fx.setup_servicing_account(api)
    source = validate_success(api.get_funding_source(ctx["funding_source"]["id"], CASE_MANAGER), 200)
    assert source["disbursed_cents"] == 5_000_000
    assert source["reserved_cents"] == 0
    assert source["available_cents"] == 5_000_000
    assert_funding_source_ledger_invariant(source)


# --- transitive_cascade / award_cancel_release_chain_depth2 -----------------
def test_award_cancel_releases_allocation(api):
    """PRD 3.4: "Cancellation drives a cascade: every one of the award's
    still-`RESERVED` funding allocations is released (moved to `RELEASED`), and
    for each such allocation the reserved amount is credited back from the
    funding source's `reserved_cents` to its `available_cents`, preserving the
    ledger invariant of Section 2.10."

    Design: Difficulty/transitive_cascade/award_cancel_release_chain_depth2
    """
    ctx = fx.setup_funded_award(api)  # award FUNDED, one allocation RESERVED
    validate_success(api.cancel_award(ctx["award"]["id"], CASE_MANAGER), 200)
    allocation = validate_success(api.get_funding_allocation(ctx["allocation"]["id"], CASE_MANAGER), 200)
    award = validate_success(api.get_award(ctx["award"]["id"], CASE_MANAGER), 200)
    assert allocation["status"] == "RELEASED", f"expected RELEASED, got {allocation['status']}"
    assert award["status"] == "CANCELLED", f"expected CANCELLED, got {award['status']}"


def test_award_cancel_credits_source_reserved_back_to_available(api):
    """PRD 3.4: "for each such allocation the reserved amount is credited back
    from the funding source's `reserved_cents` to its `available_cents`,
    preserving the ledger invariant of Section 2.10."

    Design: Difficulty/transitive_cascade/award_cancel_release_chain_depth2
    """
    ctx = fx.setup_funded_award(api)  # 5,000,000 reserved from a 10,000,000 source
    validate_success(api.cancel_award(ctx["award"]["id"], CASE_MANAGER), 200)
    source = validate_success(api.get_funding_source(ctx["funding_source"]["id"], CASE_MANAGER), 200)
    assert source["reserved_cents"] == 0
    assert source["available_cents"] == 10_000_000


# --- compensating_invariant / funding_pool_conserved_on_award_cancel --------
def test_pool_available_restored_after_cancel(api):
    """PRD 2.10: "When an allocation is released, the same amount moves back from
    `reserved_cents` to `available_cents`."
    PRD 3.4: "for each such allocation the reserved amount is credited back from
    the funding source's `reserved_cents` to its `available_cents`, preserving
    the ledger invariant of Section 2.10."

    Design: Difficulty/compensating_invariant/funding_pool_conserved_on_award_cancel
    """
    ctx = fx.setup_funded_award(api)
    validate_success(api.cancel_award(ctx["award"]["id"], CASE_MANAGER), 200)
    source = validate_success(api.get_funding_source(ctx["funding_source"]["id"], CASE_MANAGER), 200)
    assert source["available_cents"] == 10_000_000
    assert source["reserved_cents"] == 0


def test_pool_sum_conserved_after_cancel(api):
    """PRD 2.10: "Each `FundingSource` maintains three ledger buckets —
    `available_cents` (uncommitted), `reserved_cents` (committed but not yet paid
    out), and `disbursed_cents` (permanently paid out) — whose sum must always
    equal `total_appropriation_cents`."

    Design: Difficulty/compensating_invariant/funding_pool_conserved_on_award_cancel
    """
    ctx = fx.setup_funded_award(api)
    validate_success(api.cancel_award(ctx["award"]["id"], CASE_MANAGER), 200)
    source = validate_success(api.get_funding_source(ctx["funding_source"]["id"], CASE_MANAGER), 200)
    assert source["disbursed_cents"] == 0
    assert_funding_source_ledger_invariant(source)
