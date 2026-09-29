"""
A screening rejection unwinding escrow, the capital condition and the chartering filing.
"""

from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_condition_counts_conserved,
    assert_escrow_conservation,
    assert_fields_equal,
)
from test_helpers.types import (
    AUTHORITY_CHARTERING,
    BLOCKED_REASON_ESCROW_SHORTFALL,
    CATEGORY_CAPITAL,
    CLEARANCE_REJECTED,
    CONDITION_OPEN,
    FILING_ADDITIONAL_INFO_REQUESTED,
    FILING_CONDITIONALLY_APPROVED,
    FUNDING_REFUNDED,
    RAISE_OPEN,
    STAGE_CONDITIONALLY_APPROVED,
)


def _locked_escrow_with_a_satisfied_capital_condition(api):
    """
    Escrow locked at 4,150,000,000 cents against a 4,100,000,000 minimum, so losing the
    2,150,000,000 cent Puget Founders Fund row puts the raise under water, with a blocking
    capital condition already satisfied on the chartering application.
    """
    world = fx.conditionally_approved_group(api)
    world["c_cap"] = fx.add_condition(
        api, world["f_ca"], "CAP-01", CATEGORY_CAPITAL, True, authority=AUTHORITY_CHARTERING
    )
    fx.satisfy_condition(api, world["c_cap"], "ESCROW-AGENT-CERT-2026-08-20-CAPITAL")
    return world


# ---------------------------------------------------------------------------
# Difficulty / transitive_cascade
# ---------------------------------------------------------------------------
def test_a_screening_rejection_refunds_the_row_and_stops_it_counting(api):
    """
    Rejecting an investor is the unwinding event. The clearance dimension goes terminal, and
    because the row was funded its money goes back in the same operation, so the row drops
    out of escrow entirely.

    PRD: "If the row was `FUNDED`, its `funding_state` moves to `REFUNDED` in the same operation — a rejected investor's money goes back."

    Design: Difficulty/transitive_cascade/screening_rejection_cascades_four_levels_to_capital_condition_reopen
    """
    world = _locked_escrow_with_a_satisfied_capital_condition(api)
    fx.screen(api, world["s2"], CLEARANCE_REJECTED)

    assert_fields_equal(
        fx.read_subscription(api, world["s2"]),
        clearance_state=CLEARANCE_REJECTED,
        funding_state=FUNDING_REFUNDED,
        counts_toward_escrow=False,
    )
    assert_fields_equal(
        fx.read_subscription(api, world["s1"]), counts_toward_escrow=True
    )


def test_the_shortfall_reverts_the_raise_out_of_escrow_locked(api):
    """
    Cleared escrow falls to the 2,000,000,000 cents the surviving row holds, which is under
    the minimum, so the raise reverts out of its lock and the group records the escrow
    shortfall as what is now blocking opening. The refunded amount moves cleanly across:
    pledged plus refunded still accounts for every subscription.

    PRD: "If the recomputed `cleared_escrow_cents` is below the raise's `minimum_gross_cents` while the raise is `ESCROW_LOCKED`, the raise reverts from `ESCROW_LOCKED` to `OPEN` and the group's `opening_blocked_reason` becomes `ESCROW_SHORTFALL`."

    Design: Difficulty/transitive_cascade/screening_rejection_cascades_four_levels_to_capital_condition_reopen
    """
    world = _locked_escrow_with_a_satisfied_capital_condition(api)
    fx.screen(api, world["s2"], CLEARANCE_REJECTED)

    raise_row = fx.read_raise(api, world["raise_id"])
    assert_fields_equal(
        raise_row,
        status=RAISE_OPEN,
        cleared_escrow_cents=2_000_000_000,
        funded_gross_cents=2_000_000_000,
        refunded_gross_cents=2_150_000_000,
        pledged_gross_cents=2_000_000_000,
    )
    assert_escrow_conservation(
        raise_row,
        [fx.read_subscription(api, world["s1"]), fx.read_subscription(api, world["s2"])],
    )
    assert_fields_equal(
        fx.read_group(api, world["group_id"]),
        opening_blocked_reason=BLOCKED_REASON_ESCROW_SHORTFALL,
    )


def test_leaving_escrow_locked_reopens_the_settled_capital_condition(api):
    """
    The raise leaving its lock unsettles the capital condition that the lock had proven, so
    the condition returns to open with its audit counter incremented — the third link in a
    chain that began with one investor being turned away.

    PRD: "Because the raise left `ESCROW_LOCKED`, every approval condition on either of the group's filings whose `category` is `CAPITAL` and whose `status` is `SATISFIED` is returned to `OPEN` and has its `adjudication_count` incremented by one."

    Design: Difficulty/transitive_cascade/screening_rejection_cascades_four_levels_to_capital_condition_reopen
    """
    world = _locked_escrow_with_a_satisfied_capital_condition(api)
    fx.screen(api, world["s2"], CLEARANCE_REJECTED)

    assert_fields_equal(
        fx.read_condition(api, world["c_cap"]),
        status=CONDITION_OPEN,
        adjudication_count=2,
    )


def test_the_reopened_condition_pulls_the_filing_into_information_requested(api):
    """
    With the condition back in the blocking set the filing's posture is recomputed and the
    filing falls out of conditional approval onto its first information round. The group was
    never in pre-opening, so it holds its stage while carrying the escrow-shortfall block.

    PRD: "And if that re-derivation raises a filing's `open_blocking_condition_count` from zero to a positive number while that filing is `CONDITIONALLY_APPROVED`, the filing itself cascades from `CONDITIONALLY_APPROVED` to `ADDITIONAL_INFO_REQUESTED` with `info_request_round` incremented by one — which in turn pulls the group back out of `PRE_OPENING`."

    Design: Difficulty/transitive_cascade/screening_rejection_cascades_four_levels_to_capital_condition_reopen
    """
    world = _locked_escrow_with_a_satisfied_capital_condition(api)
    before = fx.read_filing(api, world["f_ca"])
    assert_fields_equal(before, status=FILING_CONDITIONALLY_APPROVED, info_request_round=0)

    fx.screen(api, world["s2"], CLEARANCE_REJECTED)

    filing = fx.read_filing(api, world["f_ca"])
    assert_fields_equal(
        filing,
        status=FILING_ADDITIONAL_INFO_REQUESTED,
        info_request_round=1,
        open_blocking_condition_count=1,
        settled_condition_count=0,
        pre_opening_clearance=False,
    )
    assert_condition_counts_conserved(filing, 1)
    assert_fields_equal(
        fx.read_group(api, world["group_id"]), stage=STAGE_CONDITIONALLY_APPROVED
    )
