"""
The two independent state dimensions a subscription carries on one row.
"""

from test_helpers import fixtures as fx
from test_helpers.assertions import assert_fields_equal, assert_version_bumped_by
from test_helpers.types import (
    CLEARANCE_CLEARED,
    CLEARANCE_UNSCREENED,
    FUNDING_FUNDED,
    FUNDING_PLEDGED,
)


def _open_raise_with_one_pledge(api):
    """A single 2,000,000 share pledge, neither funded nor screened."""
    world = fx.bare_open_raise(api)
    world["s1"] = fx.add_subscription(
        api, world["raise_id"], "Harbor Trust LP", 2_000_000
    )
    return world


# ---------------------------------------------------------------------------
# Difficulty / non_linear_state_machine
# ---------------------------------------------------------------------------
def test_screening_a_pledge_clear_leaves_the_money_dimension_untouched(api):
    """
    Screening runs ahead of the cash. The row's clearance dimension advances to cleared
    while its funding dimension stays on the original pledge, so the conjunction the escrow
    counter depends on is still false and escrow is still empty — even though the pledge is
    fully inside the subscription basis at 2,000,000,000 cents.

    PRD: "The two dimensions advance in either order and impose no ordering on each other; `counts_toward_escrow` is true for exactly those rows where `funding_state` is `FUNDED` **and** `clearance_state` is `CLEARED`."

    Design: Difficulty/non_linear_state_machine/subscription_funding_and_clearance_dimensions_advance_independently
    """
    world = _open_raise_with_one_pledge(api)
    before = fx.read_subscription(api, world["s1"])
    assert_fields_equal(
        before,
        funding_state=FUNDING_PLEDGED,
        clearance_state=CLEARANCE_UNSCREENED,
        counts_toward_escrow=False,
    )

    screened = fx.screen(api, world["s1"], CLEARANCE_CLEARED)
    assert_fields_equal(
        screened,
        funding_state=FUNDING_PLEDGED,
        clearance_state=CLEARANCE_CLEARED,
        counts_toward_escrow=False,
    )
    assert_version_bumped_by(before, screened)

    assert_fields_equal(
        fx.read_raise(api, world["raise_id"]),
        cleared_escrow_cents=0,
        funded_gross_cents=0,
        pledged_gross_cents=2_000_000_000,
        subscribed_shares=2_000_000,
    )


def test_funding_an_already_cleared_pledge_completes_the_conjunction(api):
    """
    The money arriving second closes the pair, and only then does the row begin to count.
    The whole 2,000,000,000 cents lands in the cleared basis and in the funded total in the
    same operation, with the subscription basis unchanged because it always held the pledge.

    PRD: "`FUND` moves `funding_state` from `PLEDGED` to `FUNDED` and requires the parent raise to be `OPEN` (`ERR_RAISE_NOT_OPEN`); a subscription that is not `PLEDGED` is refused with `ERR_FUNDING_TRANSITION_NOT_ALLOWED`."

    Design: Difficulty/non_linear_state_machine/subscription_funding_and_clearance_dimensions_advance_independently
    """
    world = _open_raise_with_one_pledge(api)
    fx.screen(api, world["s1"], CLEARANCE_CLEARED)

    funded = fx.fund(api, world["s1"])
    assert_fields_equal(
        funded,
        funding_state=FUNDING_FUNDED,
        clearance_state=CLEARANCE_CLEARED,
        counts_toward_escrow=True,
    )

    assert_fields_equal(
        fx.read_raise(api, world["raise_id"]),
        cleared_escrow_cents=2_000_000_000,
        funded_gross_cents=2_000_000_000,
        pledged_gross_cents=2_000_000_000,
    )


def test_the_two_dimensions_reach_the_same_place_in_the_opposite_order(api):
    """
    Running the money first and the screening second arrives at exactly the same row and the
    same escrow position, which is what it means for the two dimensions to impose no
    ordering on each other.

    PRD: "`clearance_state` tracks investor screening and runs `UNSCREENED` → `SCREENING` → `CLEARED`, with `REJECTED` reachable from any of `UNSCREENED`, `SCREENING` or `CLEARED`."

    Design: Difficulty/non_linear_state_machine/subscription_funding_and_clearance_dimensions_advance_independently
    """
    world = _open_raise_with_one_pledge(api)

    funded = fx.fund(api, world["s1"])
    assert_fields_equal(
        funded,
        funding_state=FUNDING_FUNDED,
        clearance_state=CLEARANCE_UNSCREENED,
        counts_toward_escrow=False,
    )
    assert_fields_equal(
        fx.read_raise(api, world["raise_id"]),
        cleared_escrow_cents=0,
        funded_gross_cents=2_000_000_000,
    )

    screened = fx.screen(api, world["s1"], CLEARANCE_CLEARED)
    assert_fields_equal(
        screened,
        funding_state=FUNDING_FUNDED,
        clearance_state=CLEARANCE_CLEARED,
        counts_toward_escrow=True,
    )
    assert_fields_equal(
        fx.read_raise(api, world["raise_id"]),
        cleared_escrow_cents=2_000_000_000,
        funded_gross_cents=2_000_000_000,
    )
