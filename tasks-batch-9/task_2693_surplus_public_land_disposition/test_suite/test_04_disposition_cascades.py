"""Two operations that reach far beyond the resource named in the request.

Closing bidding on a field that grades out unwinds the offering, the
declaration, the valuation and the parcel. Recording the deed conveys the
parcel, closes the declaration and the offering, distributes the money and
consumes the winner's deposit.
"""

from test_helpers import fixtures as fx
from test_helpers import get_success_data

#: One general fund taking the whole distribution.
SINGLE_FUND = [
    {
        "priority_rank": 1,
        "allocation_pct": 1.0,
        "fixed_reserve_cents": 0,
        "name": "General Fund",
        "fund_code": "F-GEN",
    }
]


def _offering_with_one_debarred_bid(api):
    """A live competitive sale whose only bidder was debarred after tendering.

    The bid was lawfully accepted from a clear bidder, the compliance monitor
    then debarred that bidder, and the clock now stands exactly on the closing
    instant, so the window has run out and the field can be graded.
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
    ctx["bid"] = fx.submit_bid(
        api,
        ctx["offering"]["id"],
        ctx["bidder"]["id"],
        amount_cents=105000000,
        deposit_amount_cents=ctx["offering"]["required_deposit_cents"],
    )
    fx.debar_bidder(api, ctx["bidder"]["id"])
    fx.set_clock(api, ctx["bid_close_at"])
    return ctx


def _recorded_sale(api):
    """A competitive sale carried all the way to the recorder.

    A single fund takes the whole distribution, the winning bid of 108,000,000
    leaves a provisional net of 105,250,001 against one cured lien of 250,000,
    and the deed is recorded on the closing instant.
    """
    ctx = fx.build_valued_parcel(
        api,
        appraised_value_cents=100000000,
        book_value_cents=70000000,
        cured_lien_actual_cents=250000,
        lien_estimate_cents=250000,
    )
    return fx.build_recorded_conveyance(api, ctx, fund_specs=SINGLE_FUND)


def test_01_grading_a_debarred_field_fails_the_offering_and_returns_the_escrow(api):
    """Debarment is fatal at grading time and the deposit goes straight back.

    "Every bid still in `SUBMITTED` is then graded on one criterion only: the bid
    moves `SUBMITTED → QUALIFIED` unless its bidder's `debarment_status` is now
    `DEBARRED`, in which case it moves `SUBMITTED → DISQUALIFIED` and its deposit
    moves `HELD → RELEASED`, with `escrow_held_cents` falling and
    `available_funds_cents` rising by `deposit_amount_cents`."

    Design: Difficulty/transitive_cascade/close_bidding_failure_cascades_offering_declaration_appraisal_parcel
    """
    ctx = _offering_with_one_debarred_bid(api)

    offering = fx.close_bidding(api, ctx["offering"]["id"])
    assert offering["status"] == "FAILED_NO_QUALIFYING_BID", (
        "no bid qualified, so the offering fails, got " f"{offering['status']!r}"
    )
    assert offering["qualified_bid_count"] == 0, (
        f"and counts no qualifying bid, got {offering['qualified_bid_count']}"
    )

    bid = get_success_data(api.get_bid(ctx["bid"]["id"], fx.OFFICER_HEADERS))
    assert bid["qualification_status"] == "DISQUALIFIED", (
        "the debarred bidder's bid is graded out, got "
        f"{bid['qualification_status']!r}"
    )
    assert bid["deposit_status"] == "RELEASED", (
        f"and its deposit is released, got {bid['deposit_status']!r}"
    )

    bidder = get_success_data(api.get_bidder(ctx["bidder"]["id"], fx.FINANCE_HEADERS))
    assert bidder["escrow_held_cents"] == 0, (
        "a failed offering leaves no cash in escrow behind it, got "
        f"{bidder['escrow_held_cents']}"
    )
    assert bidder["available_funds_cents"] == 10000000, (
        "the whole credited amount is spendable again, got "
        f"{bidder['available_funds_cents']}"
    )


def test_02_the_failure_cascades_to_the_declaration_the_valuation_and_the_parcel(api):
    """One close-bidding call unwinds four rows the request never names.

    "The declaration moves `OFFERING_AUTHORIZED → UNSUCCESSFUL` and its
    `reoffer_eligible_at` is set to the logical clock plus 30 days, starting the
    statutory cooling-off period; its `version` rises by 1 on this failure
    cascade, and only on this branch — a close-bidding that grades at least one
    qualifying bid touches no declaration at all." "And because that appraisal is gone, the
    parcel's `valuation_status` becomes `STALE` and `disposition_ready`
    recomputes to false, so the parcel cannot be re-offered until a fresh
    appraisal has been ordered, reported and accepted."

    Design: Difficulty/transitive_cascade/close_bidding_failure_cascades_offering_declaration_appraisal_parcel
    """
    ctx = _offering_with_one_debarred_bid(api)
    fx.close_bidding(api, ctx["offering"]["id"])

    declaration = get_success_data(
        api.get_declaration(ctx["declaration"]["id"], fx.OFFICER_HEADERS)
    )
    assert declaration["status"] == "UNSUCCESSFUL", (
        "the declaration follows the offering down, got "
        f"{declaration['status']!r}"
    )
    assert declaration["reoffer_eligible_at"] == "2027-01-30T00:00:00.000Z", (
        "the cooling-off period runs 30 days from the closing instant of "
        f"2026-12-31T00:00:00Z, got {declaration['reoffer_eligible_at']!r}"
    )
    assert declaration["reoffer_count"] == 0, (
        "no re-offer cycle has been taken yet, got "
        f"{declaration['reoffer_count']}"
    )

    appraisal = get_success_data(
        api.get_appraisal(ctx["appraisal"]["id"], fx.OFFICER_HEADERS)
    )
    assert appraisal["status"] == "SUPERSEDED", (
        "a market that produced no qualifying bid supersedes the valuation, got "
        f"{appraisal['status']!r}"
    )
    assert appraisal["revaluation_required"] is True, (
        f"and demands a revaluation, got {appraisal['revaluation_required']!r}"
    )

    parcel = get_success_data(api.get_parcel(ctx["parcel"]["id"], fx.OFFICER_HEADERS))
    assert parcel["valuation_status"] == "STALE", (
        "with no usable accepted appraisal the valuation goes stale, got "
        f"{parcel['valuation_status']!r}"
    )
    assert parcel["disposition_ready"] is False, (
        f"so the parcel is no longer disposition-ready, got {parcel['disposition_ready']!r}"
    )
    assert parcel["ownership_status"] == "AGENCY_OWNED", (
        "the agency still holds the land, got " f"{parcel['ownership_status']!r}"
    )


def test_03_recording_conveys_the_parcel_and_closes_the_declaration_and_offering(api):
    """The deed lands and three rows besides the conveyance change status.

    "The parcel's `ownership_status` moves `AGENCY_OWNED → CONVEYED`, its
    `disposition_ready` recomputes to false, and its `version` rises by 1. The
    offering moves `AWARDED → CLOSED_CONVEYED`, releasing its bidding window, and
    the declaration moves `OFFERING_AUTHORIZED → CONVEYED` — a terminal status —
    with its `version` raised by 1."

    Design: Difficulty/transitive_cascade/record_conveyance_cascades_parcel_declaration_waterfall_fund_credits
    """
    ctx = _recorded_sale(api)

    assert ctx["conveyance"]["recording_status"] == "RECORDED", (
        f"the deed is recorded, got {ctx['conveyance']['recording_status']!r}"
    )
    assert ctx["conveyance"]["compliance_status"] == "COMPLIANT", (
        "and the deed-restriction monitoring is armed, got "
        f"{ctx['conveyance']['compliance_status']!r}"
    )

    parcel = get_success_data(api.get_parcel(ctx["parcel"]["id"], fx.OFFICER_HEADERS))
    assert parcel["ownership_status"] == "CONVEYED", (
        f"the land has left the agency, got {parcel['ownership_status']!r}"
    )
    assert parcel["disposition_ready"] is False, (
        f"and cannot be disposed of again, got {parcel['disposition_ready']!r}"
    )

    declaration = get_success_data(
        api.get_declaration(ctx["declaration"]["id"], fx.OFFICER_HEADERS)
    )
    assert declaration["status"] == "CONVEYED", (
        f"the declaration reaches its terminal status, got {declaration['status']!r}"
    )

    offering = get_success_data(
        api.get_offering(ctx["offering"]["id"], fx.OFFICER_HEADERS)
    )
    assert offering["status"] == "CLOSED_CONVEYED", (
        f"and the offering closes, got {offering['status']!r}"
    )


def test_04_recording_runs_the_waterfall_and_credits_the_designated_fund(api):
    """The single fund takes the whole net and the ledger records the credit.

    "Each credited fund's `balance_cents` and `lifetime_credits_cents` both rise
    by that row's final `amount_cents`, the residual included. The conveyance's
    `allocated_proceeds_cents` is then set to the posted total, which by the
    invariant equals `net_proceeds_cents`."

    Design: Difficulty/transitive_cascade/record_conveyance_cascades_parcel_declaration_waterfall_fund_credits
    """
    ctx = _recorded_sale(api)

    rows = fx.allocations_for_conveyance(api, ctx["conveyance"]["id"])
    assert len(rows) == 1, (
        f"one fund taking the whole share needs one row, got {len(rows)}"
    )
    row = rows[0]
    assert row["fund_id"] == ctx["funds"][0]["id"], (
        f"credited to the designated fund, got {row['fund_id']!r}"
    )
    assert row["amount_cents"] == 105000001, (
        f"for the whole net proceeds, got {row['amount_cents']}"
    )
    assert row["allocation_basis"] == "PERCENTAGE", (
        f"on the percentage basis, got {row['allocation_basis']!r}"
    )
    assert row["status"] == "POSTED", f"and posted, got {row['status']!r}"

    assert ctx["conveyance"]["allocated_proceeds_cents"] == 105000001, (
        "the conveyance records the posted total, got "
        f"{ctx['conveyance']['allocated_proceeds_cents']}"
    )
    fund = get_success_data(api.get_fund(ctx["funds"][0]["id"], fx.FINANCE_HEADERS))
    assert fund["balance_cents"] == 105000001, (
        f"the fund balance rises by the row, got {fund['balance_cents']}"
    )
    assert fund["lifetime_credits_cents"] == 105000001, (
        "and so does its lifetime credit total, got "
        f"{fund['lifetime_credits_cents']}"
    )


def test_05_the_winning_deposit_is_applied_and_leaves_the_bidder_for_good(api):
    """Escrow is debited at recording with nothing returned to spendable cash.

    "And on a competitive sale the winning bid's deposit is consumed: the
    `WINNING` bid's `deposit_status` moves `HELD → APPLIED` and its bidder's
    `escrow_held_cents` falls by `deposit_amount_cents` while
    `available_funds_cents` is left alone, because that money has left the bidder
    for good."

    Design: Difficulty/transitive_cascade/record_conveyance_cascades_parcel_declaration_waterfall_fund_credits
    """
    ctx = _recorded_sale(api)

    bid = get_success_data(api.get_bid(ctx["bid"]["id"], fx.OFFICER_HEADERS))
    assert bid["qualification_status"] == "WINNING", (
        f"the winning bid keeps its rank, got {bid['qualification_status']!r}"
    )
    assert bid["deposit_status"] == "APPLIED", (
        f"and its deposit is consumed, got {bid['deposit_status']!r}"
    )

    bidder = get_success_data(api.get_bidder(ctx["bidder"]["id"], fx.FINANCE_HEADERS))
    assert bidder["escrow_held_cents"] == 0, (
        f"escrow is emptied, got {bidder['escrow_held_cents']}"
    )
    assert bidder["available_funds_cents"] == 5000000, (
        "10,000,000 credited less the 5,000,000 deposit is 5,000,000, and "
        "applying the deposit returns nothing, got "
        f"{bidder['available_funds_cents']}"
    )
