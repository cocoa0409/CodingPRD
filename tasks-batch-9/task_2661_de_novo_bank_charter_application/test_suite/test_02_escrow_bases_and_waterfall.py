"""
The two escrow bases, the release waterfall and the conservation of escrowed cents.

The canonical offering prices shares at 1000 cents, targets 4,300,000,000 cents
gross and may not be locked below 4,100,000,000. Harbor Trust LP subscribes for
2,000,000 shares and Puget Founders Fund for 2,150,000, so the two rows are worth
2,000,000,000 and 2,150,000,000 cents respectively.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import ESCROW_AGENT_HEADERS, fixtures as fx
from test_helpers.assertions import (
    assert_escrow_conservation,
    assert_fields_equal,
    assert_integer_cents,
    assert_waterfall_reconciles,
)
from test_helpers.factories import funding_payload
from test_helpers.types import (
    AUTHORITY_CHARTERING,
    AUTHORITY_DEPOSIT_INSURER,
    CLEARANCE_CLEARED,
    DECISION_CONDITIONALLY_APPROVED,
    FUNDING_EVENT_REFUND,
    FUNDING_FUNDED,
    FUNDING_REFUNDED,
    RAISE_ESCROW_LOCKED,
    RAISE_OPEN,
)


def _funded_but_half_cleared(api):
    """Both canonical subscriptions funded, with only Harbor Trust LP screened clear."""
    world = fx.filing_ready_group(api)
    fx.open_raise_with_two_subscriptions(api, world)
    fx.fund(api, world["s1"])
    fx.fund(api, world["s2"])
    fx.screen(api, world["s1"], CLEARANCE_CLEARED)
    return world


# ---------------------------------------------------------------------------
# Difficulty / dual_variant_calc
# ---------------------------------------------------------------------------
def test_escrow_lock_measures_the_cleared_basis_and_never_the_pledged_basis(api):
    """
    With both subscriptions funded but only one screened clear, the subscription basis
    stands at the full 4,150,000,000 cents — comfortably over the 4,100,000,000 minimum
    — while the cleared basis is only the 2,000,000,000 that actually counts. The lock
    is refused on the cleared figure even though the raise looks fully subscribed.

    PRD: "Three gates apply in this order: the raise must be `OPEN` (`ERR_RAISE_NOT_LOCKABLE`); at least one subscription of the raise must have `counts_toward_escrow` true, so an empty cleared set cannot be locked even in the degenerate case where `minimum_gross_cents` happens to be zero (`ERR_NO_CLEARED_SUBSCRIPTIONS`); and `cleared_escrow_cents` must be at least `minimum_gross_cents`, measured on the cleared basis only — `pledged_gross_cents` is never accepted here (`ERR_ESCROW_BELOW_MINIMUM`)."

    Design: Difficulty/dual_variant_calc/escrow_subscription_basis_vs_cleared_basis_divergence
    """
    world = _funded_but_half_cleared(api)

    before = fx.read_raise(api, world["raise_id"])
    assert_integer_cents(before, "pledged_gross_cents", "cleared_escrow_cents")
    assert_fields_equal(
        before,
        status=RAISE_OPEN,
        subscribed_shares=4_150_000,
        pledged_gross_cents=4_150_000_000,
        funded_gross_cents=4_150_000_000,
        cleared_escrow_cents=2_000_000_000,
    )
    assert before["pledged_gross_cents"] >= before["minimum_gross_cents"], (
        "the subscription basis must genuinely clear the minimum, so only the "
        "cleared basis can be the reason for the refusal"
    )

    validate_error(
        api.lock_escrow(world["raise_id"], ESCROW_AGENT_HEADERS), "ERR_ESCROW_BELOW_MINIMUM"
    )
    after = fx.read_raise(api, world["raise_id"])
    assert_fields_equal(after, status=RAISE_OPEN, version=before["version"])


def test_clearing_the_second_subscription_collapses_the_two_bases_and_permits_the_lock(api):
    """
    Screening the second row clear pulls its 2,150,000,000 cents into the cleared basis,
    which now equals the subscription basis at 4,150,000,000, and the lock the divergence
    had blocked goes through.

    PRD: "The **cleared basis** is `cleared_escrow_cents`, the sum of `amount_cents` over exactly those rows whose `counts_toward_escrow` is true."

    Design: Difficulty/dual_variant_calc/escrow_subscription_basis_vs_cleared_basis_divergence
    """
    world = _funded_but_half_cleared(api)
    fx.screen(api, world["s2"], CLEARANCE_CLEARED)

    raise_row = fx.read_raise(api, world["raise_id"])
    assert_fields_equal(
        raise_row,
        pledged_gross_cents=4_150_000_000,
        cleared_escrow_cents=4_150_000_000,
    )

    locked = get_success_data(api.lock_escrow(world["raise_id"], ESCROW_AGENT_HEADERS))
    assert_fields_equal(
        locked, status=RAISE_ESCROW_LOCKED, cleared_escrow_cents=4_150_000_000
    )
    assert_escrow_conservation(
        locked,
        [
            fx.read_subscription(api, world["s1"]),
            fx.read_subscription(api, world["s2"]),
        ],
    )


# ---------------------------------------------------------------------------
# Difficulty / combinatorial_formula
# ---------------------------------------------------------------------------
def test_reimbursement_cap_is_five_percent_of_gross_cleared_escrow(api):
    """
    Against 4,150,000,000 cents of cleared escrow the five percent cap is 207,500,000,
    so a 260,000,000 cent organizational expense claim is trimmed to the cap. Basing the
    cap on the capital actually released instead would give 197,619,048, which is the
    self-referential reading the contract rules out.

    PRD: "The cap base is gross cleared escrow and *not* escrow net of the reimbursement; the alternative reading, under which the reimbursement may not exceed five percent of the capital actually released, is a self-referential fixed point and yields a different answer whenever the claim is above the cap."

    Design: Difficulty/combinatorial_formula/escrow_reimbursement_cap_keyed_on_gross_not_net
    """
    world = fx.filing_ready_group(api)
    fx.open_raise(api, world, organizational_expense_claim_cents=260_000_000)
    s1 = fx.add_subscription(api, world["raise_id"], "Harbor Trust LP", 2_000_000)
    s2 = fx.add_subscription(api, world["raise_id"], "Puget Founders Fund", 2_150_000)
    for subscription_id in (s1, s2):
        fx.fund(api, subscription_id)
        fx.screen(api, subscription_id, CLEARANCE_CLEARED)

    raise_row = fx.read_raise(api, world["raise_id"])
    assert_fields_equal(
        raise_row,
        cleared_escrow_cents=4_150_000_000,
        projected_reimbursement_cents=207_500_000,
        projected_net_release_cents=3_942_500_000,
    )
    assert raise_row["projected_reimbursement_cents"] != 197_619_048, (
        "the reimbursement must not be solved against the net release"
    )
    assert raise_row["projected_net_release_cents"] != 3_952_380_952, (
        "the net release must not be solved against itself"
    )


def test_capped_waterfall_still_reconciles_gross_to_reimbursement_plus_net(api):
    """
    Trimming the claim to the cap does not lose a cent: the two buckets add back up to
    the gross cleared figure exactly. Nothing has been released yet, so the frozen
    released figure is still zero while the projections carry the current arithmetic.

    PRD: "Bucket two is everything left over: `projected_net_release_cents` is the gross figure minus `projected_reimbursement_cents`, an exact subtraction, so gross always reconciles to reimbursement plus net."

    Design: Difficulty/combinatorial_formula/escrow_reimbursement_cap_keyed_on_gross_not_net
    """
    world = fx.filing_ready_group(api)
    fx.open_raise(api, world, organizational_expense_claim_cents=260_000_000)
    for name, shares in (("Harbor Trust LP", 2_000_000), ("Puget Founders Fund", 2_150_000)):
        subscription_id = fx.add_subscription(api, world["raise_id"], name, shares)
        fx.fund(api, subscription_id)
        fx.screen(api, subscription_id, CLEARANCE_CLEARED)

    raise_row = fx.read_raise(api, world["raise_id"])
    assert_waterfall_reconciles(raise_row)
    assert (
        raise_row["projected_reimbursement_cents"] + raise_row["projected_net_release_cents"]
        == 4_150_000_000
    )
    assert_fields_equal(raise_row, released_net_cents=0)


# ---------------------------------------------------------------------------
# Difficulty / priority_pair_validation_conflict
# ---------------------------------------------------------------------------
def _conditionally_approved_without_locking(api):
    """Both filings conditionally approved while the raise is deliberately left open."""
    world = fx.filing_ready_group(api)
    fx.open_raise(api, world, organizational_expense_claim_cents=260_000_000)
    for name, shares in (("Harbor Trust LP", 2_000_000), ("Puget Founders Fund", 2_150_000)):
        subscription_id = fx.add_subscription(api, world["raise_id"], name, shares)
        fx.fund(api, subscription_id)
        fx.screen(api, subscription_id, CLEARANCE_CLEARED)
    fx.both_filings_filed(api, world)
    fx.decide_filing(
        api, world["f_ca"], DECISION_CONDITIONALLY_APPROVED, AUTHORITY_CHARTERING
    )
    fx.decide_filing(
        api, world["f_di"], DECISION_CONDITIONALLY_APPROVED, AUTHORITY_DEPOSIT_INSURER
    )
    return world


def test_release_on_an_unlocked_raise_reports_the_state_error_not_the_money_error(api):
    """
    A release aimed at a raise that never locked is refused for its status, even though
    the money would also have been short: the net release of 3,942,500,000 cents falls
    below the pinned plan's 4,000,000,000 opening requirement. The state gate sits far
    above the fiscal one, so the fiscal error never surfaces.

    PRD: "That last check sits at the very bottom of the ladder, so a release attempted on a raise that is still `OPEN` *and* whose net release would also be short reports `ERR_ESCROW_NOT_LOCKED` — the state error, not the money error."

    Design: Difficulty/priority_pair_validation_conflict/escrow_state_error_outranks_net_release_fiscal_error
    """
    world = _conditionally_approved_without_locking(api)

    error = validate_error(
        api.release_escrow(world["raise_id"], ESCROW_AGENT_HEADERS),
        "ERR_ESCROW_NOT_LOCKED",
        expected_status=409,
    )
    assert error["error_id"] != "ERR_NET_RELEASE_BELOW_PLAN_CAPITAL", (
        "the fiscal shortfall must not be reported ahead of the state refusal"
    )


def test_the_net_release_shortfall_behind_the_state_refusal_is_genuinely_present(api):
    """
    The shortfall the state error masked is real: with the claim capped at 207,500,000 the
    projected net release is 3,942,500,000 cents against a pinned plan demanding
    4,000,000,000, and the raise is still sitting open with nothing frozen.

    PRD: "And the money must actually be enough to open the bank: `projected_net_release_cents` must be at least the `opening_tier1_capital_cents` of the business plan pinned on the group's chartering-authority filing, failing which the release is refused with `ERR_NET_RELEASE_BELOW_PLAN_CAPITAL`."

    Design: Difficulty/priority_pair_validation_conflict/escrow_state_error_outranks_net_release_fiscal_error
    """
    world = _conditionally_approved_without_locking(api)

    raise_row = fx.read_raise(api, world["raise_id"])
    assert_fields_equal(
        raise_row,
        status=RAISE_OPEN,
        cleared_escrow_cents=4_150_000_000,
        projected_reimbursement_cents=207_500_000,
        projected_net_release_cents=3_942_500_000,
        released_net_cents=0,
    )

    plan = fx.read_plan(api, world["plan_id"])
    assert raise_row["projected_net_release_cents"] < plan["opening_tier1_capital_cents"], (
        "the net release must be genuinely short of the pinned plan's opening capital"
    )


# ---------------------------------------------------------------------------
# Difficulty / compensating_invariant
# ---------------------------------------------------------------------------
def test_funding_and_clearing_both_subscriptions_fills_escrow_to_the_cleared_basis(
    api, escrow_ready_group
):
    """
    Both rows funded and screened clear put the whole 4,150,000,000 cents inside escrow,
    where the 150,000,000 cent expense claim sits well under the 207,500,000 cap and so
    passes through untrimmed, leaving exactly 4,000,000,000 as the projected net release.

    PRD: "For every capital raise, at every point in time, `cleared_escrow_cents` equals the sum of `amount_cents` over exactly those subscriptions of the raise whose `counts_toward_escrow` is true, and `pledged_gross_cents` plus `refunded_gross_cents` equals the sum of `amount_cents` over every subscription of the raise."

    Design: Difficulty/compensating_invariant/fund_then_refund_restores_cleared_escrow_cents_exactly
    """
    world = escrow_ready_group

    raise_row = fx.read_raise(api, world["raise_id"])
    assert_fields_equal(
        raise_row,
        status=RAISE_OPEN,
        cleared_escrow_cents=4_150_000_000,
        funded_gross_cents=4_150_000_000,
        refunded_gross_cents=0,
        projected_reimbursement_cents=150_000_000,
        projected_net_release_cents=4_000_000_000,
    )
    subscriptions = [
        fx.read_subscription(api, world["s1"]),
        fx.read_subscription(api, world["s2"]),
    ]
    for row in subscriptions:
        assert_fields_equal(
            row, funding_state=FUNDING_FUNDED, clearance_state=CLEARANCE_CLEARED,
            counts_toward_escrow=True,
        )
    assert_escrow_conservation(raise_row, subscriptions)


def test_refunding_the_second_subscription_restores_escrow_to_its_prior_value_exactly(
    api, escrow_ready_group
):
    """
    Refunding the 2,150,000,000 cent row takes exactly that much back out of escrow and
    no more, leaving the 2,000,000,000 the first row put in. The refunded row keeps its
    cleared screening result — a refund touches only the money dimension — but stops
    counting, so it drops out of both the cleared and the subscription bases.

    PRD: "A funding event followed by a refund of the same subscription must restore `cleared_escrow_cents` to its exact pre-funding value, with no partial-cent residue and no double subtraction in the case where the subscription was also rejected in screening."

    Design: Difficulty/compensating_invariant/fund_then_refund_restores_cleared_escrow_cents_exactly
    """
    world = escrow_ready_group
    get_success_data(
        api.record_funding_event(
            world["s2"], funding_payload(FUNDING_EVENT_REFUND), ESCROW_AGENT_HEADERS
        )
    )

    refunded = fx.read_subscription(api, world["s2"])
    assert_fields_equal(
        refunded,
        funding_state=FUNDING_REFUNDED,
        clearance_state=CLEARANCE_CLEARED,
        counts_toward_escrow=False,
        amount_cents=2_150_000_000,
    )

    raise_row = fx.read_raise(api, world["raise_id"])
    assert_fields_equal(
        raise_row,
        status=RAISE_OPEN,
        subscribed_shares=2_000_000,
        pledged_gross_cents=2_000_000_000,
        funded_gross_cents=2_000_000_000,
        cleared_escrow_cents=2_000_000_000,
        refunded_gross_cents=2_150_000_000,
        projected_reimbursement_cents=100_000_000,
        projected_net_release_cents=1_900_000_000,
    )
    assert (
        raise_row["pledged_gross_cents"] + raise_row["refunded_gross_cents"] == 4_150_000_000
    ), "pledged plus refunded must still account for every subscription of the raise"
    assert_escrow_conservation(
        raise_row, [fx.read_subscription(api, world["s1"]), refunded]
    )
    assert_waterfall_reconciles(raise_row)
