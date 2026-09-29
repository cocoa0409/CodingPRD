"""Two ledgers that must come back to where they started, and one that must not.

A bidder's cash position is a pure transfer between spendable funds and escrow, so
submitting and withdrawing a bid must leave the pair of counters exactly as they
were. A reverter enforcement debits every posted allocation row symmetrically, so
every fund balance returns to zero while both lifetime counters keep the history.
"""

from test_helpers import fixtures as fx
from test_helpers import (
    assert_bidder_cash_conserved,
    assert_fund_ledger_identity,
    find_row,
    get_success_data,
)

#: Four designated funds: a statutory reserve off the top, then three percentage
#: funds whose shares sum to exactly one.
FUND_LADDER = [
    {
        "priority_rank": 1,
        "allocation_pct": 0.0,
        "fixed_reserve_cents": 5000000,
        "name": "Statutory Reserve",
        "fund_code": "F-RES",
    },
    {
        "priority_rank": 2,
        "allocation_pct": 0.3,
        "fixed_reserve_cents": 0,
        "name": "Parks Acquisition Fund",
        "fund_code": "F-PARK",
    },
    {
        "priority_rank": 3,
        "allocation_pct": 0.3,
        "fixed_reserve_cents": 0,
        "name": "Capital Facilities Fund",
        "fund_code": "F-CAP",
    },
    {
        "priority_rank": 4,
        "allocation_pct": 0.4,
        "fixed_reserve_cents": 0,
        "name": "General Fund",
        "fund_code": "F-GEN",
    },
]

#: What each fund holds once the deed is recorded, before anything is unwound.
CREDITED_BY_FUND = {
    "F-RES": 5000000,
    "F-PARK": 30000000,
    "F-CAP": 30000000,
    "F-GEN": 40000001,
}


def _published_offering_with_a_funded_bidder(api):
    """A live competitive sale and one clear bidder credited with 10,000,000.

    The cured lien of 250,000 leaves the frozen minimum at 99,750,000 and the
    clock never leaves the default instant, which is inside the bidding window, so
    a withdrawal is permitted at any point in the test.
    """
    ctx = fx.build_valued_parcel(
        api,
        appraised_value_cents=100000000,
        book_value_cents=70000000,
        cured_lien_actual_cents=250000,
        lien_estimate_cents=250000,
    )
    ctx = fx.build_published_offering(api, ctx)
    ctx["bidder"] = fx.make_funded_bidder(api, 10000000)
    return ctx


def _reverted_ready_conveyance(api):
    """A recorded deed distributed across four funds with an uncured breach.

    The sale of 108,000,000 against closing costs of 1,249,999, a broker fee of
    1,500,000 and one cured lien of 250,000 freezes the net at 105,000,001, which
    the waterfall splits across the four designated funds when the deed is
    recorded. The breach was noticed on 2027-01-15, fixing the cure deadline at
    2027-02-14, and the clock now stands well past it.
    """
    ctx = fx.build_valued_parcel(
        api,
        appraised_value_cents=100000000,
        book_value_cents=70000000,
        cured_lien_actual_cents=250000,
        lien_estimate_cents=250000,
    )
    ctx = fx.build_violation_noticed_conveyance(
        api,
        ctx,
        noticed_at="2027-01-15T00:00:00Z",
        fund_specs=FUND_LADDER,
        closing_costs_cents=1249999,
        broker_fee_cents=1500000,
        reverter_cure_period_days=30,
        bid_amount_cents=108000000,
        bidder_funding_cents=10000000,
    )
    fx.set_clock(api, "2027-03-01T00:00:00Z")
    return ctx


def _fund_by_code(api, ctx, fund_code):
    """Read the current ledger of one configured fund."""
    configured = find_row(ctx["funds"], fund_code=fund_code)
    assert configured is not None, f"the {fund_code} fund must have been configured"
    return get_success_data(api.get_fund(configured["id"], fx.FINANCE_HEADERS))


def test_01_funding_credits_the_spendable_side_and_leaves_escrow_empty(api):
    """The opening position is the whole credit on one side and nothing on the other.

    "A new bidder is `CLEAR` of debarment and carries an empty cash ledger:
    `available_funds_cents`, `escrow_held_cents` and `lifetime_deposits_cents` all
    zero. Treasury, acting as `FinanceOfficer`, credits verified cash by supplying
    a positive `amount_cents`, which raises both `available_funds_cents` and
    `lifetime_deposits_cents` by that amount and increments the bidder's `version`
    by 1."

    Design: Difficulty/compensating_invariant/bid_withdrawal_restores_bidder_liquid_plus_escrow_total
    """
    ctx = _published_offering_with_a_funded_bidder(api)

    bidder = get_success_data(api.get_bidder(ctx["bidder"]["id"], fx.FINANCE_HEADERS))
    assert bidder["available_funds_cents"] == 10000000, (
        "the whole credit lands on the spendable side, got "
        f"{bidder['available_funds_cents']}"
    )
    assert bidder["escrow_held_cents"] == 0, (
        f"with nothing in escrow, got {bidder['escrow_held_cents']}"
    )
    assert bidder["lifetime_deposits_cents"] == 10000000, (
        "and the funding counter records the credit, got "
        f"{bidder['lifetime_deposits_cents']}"
    )
    assert_bidder_cash_conserved(bidder)


def test_02_submitting_the_bid_moves_the_deposit_sideways_and_nothing_more(api):
    """The pair of counters redistributes and the total is untouched.

    "Submitting a bid moves the deposit sideways: `available_funds_cents` falls by
    the bid's `deposit_amount_cents` and `escrow_held_cents` rises by the same
    amount, while `lifetime_deposits_cents` is untouched because it counts funding
    credits only."

    Design: Difficulty/compensating_invariant/bid_withdrawal_restores_bidder_liquid_plus_escrow_total
    """
    ctx = _published_offering_with_a_funded_bidder(api)
    deposit = ctx["offering"]["required_deposit_cents"]
    fx.submit_bid(
        api,
        ctx["offering"]["id"],
        ctx["bidder"]["id"],
        amount_cents=108000000,
        deposit_amount_cents=deposit,
    )

    bidder = get_success_data(api.get_bidder(ctx["bidder"]["id"], fx.FINANCE_HEADERS))
    assert bidder["escrow_held_cents"] == deposit, (
        f"the whole deposit of {deposit} sits in escrow, got "
        f"{bidder['escrow_held_cents']}"
    )
    assert bidder["available_funds_cents"] == 10000000 - deposit, (
        f"and the spendable side falls by exactly {deposit}, got "
        f"{bidder['available_funds_cents']}"
    )
    assert bidder["lifetime_deposits_cents"] == 10000000, (
        "the funding counter records no internal movement, got "
        f"{bidder['lifetime_deposits_cents']}"
    )
    assert_bidder_cash_conserved(bidder)


def test_03_withdrawing_the_bid_restores_the_identical_pair_of_values(api):
    """The release is the exact mirror of the transfer, not a fresh credit.

    "On success `qualification_status` moves `SUBMITTED → WITHDRAWN` and
    `deposit_status` moves `HELD → RELEASED`, and the escrow is returned:
    `escrow_held_cents` falls by `deposit_amount_cents` and `available_funds_cents`
    rises by exactly that amount, restoring the ledger to the precise pair of
    values it held before the bid was submitted."

    Design: Difficulty/compensating_invariant/bid_withdrawal_restores_bidder_liquid_plus_escrow_total
    """
    ctx = _published_offering_with_a_funded_bidder(api)
    bid = fx.submit_bid(
        api,
        ctx["offering"]["id"],
        ctx["bidder"]["id"],
        amount_cents=108000000,
        deposit_amount_cents=ctx["offering"]["required_deposit_cents"],
    )

    withdrawn = fx.withdraw_bid(api, bid["id"], ctx["bidder"]["id"])
    assert withdrawn["qualification_status"] == "WITHDRAWN", (
        f"the bid is pulled, got {withdrawn['qualification_status']!r}"
    )
    assert withdrawn["deposit_status"] == "RELEASED", (
        f"and its deposit released, got {withdrawn['deposit_status']!r}"
    )

    bidder = get_success_data(api.get_bidder(ctx["bidder"]["id"], fx.FINANCE_HEADERS))
    assert bidder["available_funds_cents"] == 10000000, (
        "the spendable side is exactly what it was before the bid, got "
        f"{bidder['available_funds_cents']}"
    )
    assert bidder["escrow_held_cents"] == 0, (
        f"escrow is emptied again, got {bidder['escrow_held_cents']}"
    )
    assert bidder["lifetime_deposits_cents"] == 10000000, (
        "and the release was a transfer rather than a new credit, so the funding "
        f"counter has not moved, got {bidder['lifetime_deposits_cents']}"
    )
    assert_bidder_cash_conserved(bidder)

    offering = get_success_data(
        api.get_offering(ctx["offering"]["id"], fx.OFFICER_HEADERS)
    )
    assert offering["status"] == "OPEN", (
        f"the offering is still taking bids, got {offering['status']!r}"
    )
    assert offering["qualified_bid_count"] == 0, (
        "and nothing has been graded, got " f"{offering['qualified_bid_count']}"
    )


def test_04_the_recorded_deed_leaves_every_designated_fund_credited(api):
    """Four funds hold the whole net between them before anything is unwound.

    "Each credited fund's `balance_cents` and `lifetime_credits_cents` both rise by
    that row's final `amount_cents`, the residual included. The conveyance's
    `allocated_proceeds_cents` is then set to the posted total, which by the
    invariant equals `net_proceeds_cents`."

    Design: Difficulty/compensating_invariant/conveyance_revert_reverses_fund_credits_leaving_zero_balance
    """
    ctx = _reverted_ready_conveyance(api)

    rows = fx.allocations_for_conveyance(api, ctx["conveyance"]["id"])
    assert len(rows) == 4, f"one row per designated fund, got {len(rows)}"
    for row in rows:
        assert row["status"] == "POSTED", (
            f"every row is posted before enforcement, got {row['status']!r}"
        )

    for fund_code, credited in CREDITED_BY_FUND.items():
        fund = _fund_by_code(api, ctx, fund_code)
        assert fund["balance_cents"] == credited, (
            f"{fund_code} holds {credited}, got {fund['balance_cents']}"
        )
        assert fund["lifetime_credits_cents"] == credited, (
            f"credited once and only once, got {fund['lifetime_credits_cents']}"
        )
        assert fund["lifetime_debits_cents"] == 0, (
            f"with nothing yet debited, got {fund['lifetime_debits_cents']}"
        )
        assert_fund_ledger_identity(fund)

    assert ctx["conveyance"]["allocated_proceeds_cents"] == 105000001, (
        "the whole net is distributed, got "
        f"{ctx['conveyance']['allocated_proceeds_cents']}"
    )
    assert (
        ctx["conveyance"]["allocated_proceeds_cents"]
        == ctx["conveyance"]["net_proceeds_cents"]
    ), (
        "and the posted total equals the frozen net: "
        f"{ctx['conveyance']['allocated_proceeds_cents']} against "
        f"{ctx['conveyance']['net_proceeds_cents']}"
    )


def test_05_enforcing_the_reverter_debits_every_row_back_to_a_zero_balance(api):
    """Both sides of the ledger are recorded rather than the credit being erased.

    "Every allocation row on this conveyance whose `status` is `POSTED` moves to
    `REVERSED` with `reversed_at` stamped from the clock; rows already `REVERSED`
    are left alone, and rows belonging to other conveyances or to an
    appraisal-challenge forfeiture are untouched. For each row reversed, the
    credited fund's `balance_cents` falls by that row's `amount_cents` and its
    `lifetime_debits_cents` rises by the same amount, while `lifetime_credits_cents`
    is left exactly as it was — the credit happened, and the ledger records both
    sides rather than erasing the first."

    Design: Difficulty/compensating_invariant/conveyance_revert_reverses_fund_credits_leaving_zero_balance
    """
    ctx = _reverted_ready_conveyance(api)

    reverted = fx.revert_conveyance(api, ctx["conveyance"]["id"])
    assert reverted["compliance_status"] == "REVERTED", (
        f"the reverter is enforced, got {reverted['compliance_status']!r}"
    )
    assert reverted["recording_status"] == "RESCINDED", (
        f"and the deed is rescinded on the other dimension, got {reverted['recording_status']!r}"
    )
    assert reverted["reverted_at"] == "2027-03-01T00:00:00.000Z", (
        f"stamped from the clock, got {reverted['reverted_at']!r}"
    )

    rows = fx.allocations_for_conveyance(api, ctx["conveyance"]["id"])
    assert len(rows) == 4, (
        f"the four rows survive as history rather than being deleted, got {len(rows)}"
    )
    for row in rows:
        assert row["status"] == "REVERSED", (
            f"each is marked reversed, got {row['status']!r}"
        )
        assert row["reversed_at"] == "2027-03-01T00:00:00.000Z", (
            f"at the enforcement instant, got {row['reversed_at']!r}"
        )

    total_debited = 0
    for fund_code, credited in CREDITED_BY_FUND.items():
        fund = _fund_by_code(api, ctx, fund_code)
        assert fund["balance_cents"] == 0, (
            f"{fund_code} is emptied by the reversal, got {fund['balance_cents']}"
        )
        assert fund["lifetime_credits_cents"] == credited, (
            "the original credit is not erased, got "
            f"{fund['lifetime_credits_cents']}"
        )
        assert fund["lifetime_debits_cents"] == credited, (
            "and an equal debit is recorded against it, got "
            f"{fund['lifetime_debits_cents']}"
        )
        assert_fund_ledger_identity(fund)
        total_debited += fund["lifetime_debits_cents"]

    assert total_debited == 105000001, (
        "the debits across the four funds account for the whole distribution, got "
        f"{total_debited}"
    )


def test_06_the_reversal_zeroes_the_allocated_total_and_keeps_the_applied_deposit(api):
    """The distribution is undone; the purchase money that already left is not.

    "Finally the conveyance's `allocated_proceeds_cents` recomputes to zero, since
    no posted row remains. The frozen `sale_price_cents`,
    `recoverable_curative_cost_cents` and `net_proceeds_cents` are not disturbed:
    they remain the historical record of the reverted transaction." "Applying a
    deposit at recording is the one movement that is not compensating:
    `escrow_held_cents` falls by the deposit and `available_funds_cents` is not
    credited, because the cash has left the bidder for good and been applied to the
    purchase price."

    Design: Difficulty/compensating_invariant/conveyance_revert_reverses_fund_credits_leaving_zero_balance
    """
    ctx = _reverted_ready_conveyance(api)
    reverted = fx.revert_conveyance(api, ctx["conveyance"]["id"])

    assert reverted["allocated_proceeds_cents"] == 0, (
        "no posted row remains, so nothing is allocated, got "
        f"{reverted['allocated_proceeds_cents']}"
    )
    assert reverted["net_proceeds_cents"] == 105000001, (
        "the frozen net survives as the record of what was reverted, got "
        f"{reverted['net_proceeds_cents']}"
    )
    assert reverted["recoverable_curative_cost_cents"] == 250000, (
        "as does the curative recovery, got "
        f"{reverted['recoverable_curative_cost_cents']}"
    )
    assert reverted["sale_price_cents"] == 108000000, (
        f"and the sale price, got {reverted['sale_price_cents']}"
    )

    parcel = get_success_data(api.get_parcel(ctx["parcel"]["id"], fx.OFFICER_HEADERS))
    assert parcel["ownership_status"] == "REVERTED_TO_AGENCY", (
        f"the land comes back to the agency, got {parcel['ownership_status']!r}"
    )
    assert parcel["valuation_status"] == "STALE", (
        f"carrying a value that can no longer be relied on, got {parcel['valuation_status']!r}"
    )
    assert parcel["disposition_ready"] is False, (
        f"so it is not disposition-ready, got {parcel['disposition_ready']!r}"
    )

    bid = get_success_data(api.get_bid(ctx["bid"]["id"], fx.OFFICER_HEADERS))
    assert bid["deposit_status"] == "APPLIED", (
        "the winner's deposit stays applied, got " f"{bid['deposit_status']!r}"
    )
    bidder = get_success_data(api.get_bidder(ctx["bidder"]["id"], fx.FINANCE_HEADERS))
    assert bidder["available_funds_cents"] == 5000000, (
        "10,000,000 credited less the 5,000,000 deposit is 5,000,000, and "
        "enforcement returns none of it, got "
        f"{bidder['available_funds_cents']}"
    )
    assert bidder["escrow_held_cents"] == 0, (
        f"escrow stays empty, got {bidder['escrow_held_cents']}"
    )
    assert bidder["lifetime_deposits_cents"] == 10000000, (
        "and the funding history is unchanged, so the pair of live counters now "
        "falls short of it by exactly the applied deposit, got "
        f"{bidder['lifetime_deposits_cents']}"
    )
