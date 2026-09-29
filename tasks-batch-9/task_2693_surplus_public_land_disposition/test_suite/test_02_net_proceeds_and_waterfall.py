"""Freezing the money on a conveyance, and distributing it at the recorder.

Clearing title combines the sale price, the closing costs, the broker fee and
the curative spend through a capped deduction; recording then walks the funds in
three passes whose rounding order decides every row.
"""

from test_helpers import fixtures as fx
from test_helpers import find_row, get_success_data

#: Four designated funds: a reserve that takes no percentage share, then three
#: percentage funds whose shares sum to exactly one.
FUND_LADDER = [
    {
        "priority_rank": 1,
        "allocation_pct": 0,
        "fixed_reserve_cents": 5000000,
        "name": "Land Acquisition Reserve",
        "fund_code": "F-LAND",
    },
    {
        "priority_rank": 2,
        "allocation_pct": 0.3,
        "fixed_reserve_cents": 0,
        "name": "Capital Facilities Fund",
        "fund_code": "F-CAP",
    },
    {
        "priority_rank": 3,
        "allocation_pct": 0.3,
        "fixed_reserve_cents": 0,
        "name": "Affordable Housing Trust",
        "fund_code": "F-HOUSE",
    },
    {
        "priority_rank": 4,
        "allocation_pct": 0.4,
        "fixed_reserve_cents": 0,
        "name": "General Fund",
        "fund_code": "F-GEN",
    },
]


def _heavy_curative_conveyance(api):
    """An awarded sale on a parcel that cost 20,250,000 cents to clear.

    Two liens are cured, at 12,000,000 and 8,250,000, so the incurred curative
    spend far exceeds fifteen percent of the provisional net. The winning bid is
    108,000,000 against closing costs of 1,249,999 and a broker fee of
    1,500,000, leaving a provisional net of 105,250,001.
    """
    ctx = fx.build_valued_parcel(
        api,
        appraised_value_cents=100000000,
        book_value_cents=70000000,
        cured_lien_actual_cents=12000000,
        lien_estimate_cents=12000000,
    )
    fx.add_cured_lien(api, ctx["parcel"]["id"], 8250000, 8250000)
    return fx.build_conveyance(
        api,
        ctx,
        closing_costs_cents=1249999,
        broker_fee_cents=1500000,
        reverter_cure_period_days=30,
        bid_amount_cents=108000000,
        bidder_funding_cents=10000000,
    )


def _light_curative_recording(api):
    """A recorded deed on a parcel that cost only 250,000 cents to clear.

    The single cured lien leaves the recovery cap slack, so the frozen net
    proceeds are 105,000,001 — a figure whose percentage split leaves a one-cent
    residual for the waterfall's third pass to place.
    """
    ctx = fx.build_valued_parcel(
        api,
        appraised_value_cents=100000000,
        book_value_cents=70000000,
        cured_lien_actual_cents=250000,
        lien_estimate_cents=250000,
    )
    return fx.build_recorded_conveyance(api, ctx, fund_specs=FUND_LADDER)


def test_01_recovery_cap_binds_below_the_incurred_curative_spend(api):
    """The agency recovers fifteen percent of the net, not what it actually spent.

    "The recovery cap is the provisional net multiplied by 0.15, rounded half up
    to a whole cent." "`recoverable_curative_cost_cents` is the smaller of the
    incurred curative cost and the recovery cap, so the agency recovers its
    curative spending off the top but never more than 15 percent of the
    provisional net."

    Design: Difficulty/combinatorial_formula/net_proceeds_curative_recovery_cap_binds_nested_min_max
    """
    ctx = _heavy_curative_conveyance(api)

    conveyance = fx.clear_title(api, ctx["conveyance"]["id"])
    assert conveyance["sale_price_cents"] == 108000000, (
        "the consideration is the winning bid amount, got "
        f"{conveyance['sale_price_cents']}"
    )
    assert conveyance["recoverable_curative_cost_cents"] == 15787500, (
        "a provisional net of 105,250,001 caps the recovery at 15,787,500, got "
        f"{conveyance['recoverable_curative_cost_cents']}"
    )
    assert conveyance["recoverable_curative_cost_cents"] != 20250000, (
        "the incurred spend of 20,250,000 must not be recovered in full"
    )


def test_02_net_proceeds_deduct_the_capped_recovery_and_freeze_the_file(api):
    """The net is the provisional net less the capped recovery, and the file closes.

    "`net_proceeds_cents` is then the provisional net less
    `recoverable_curative_cost_cents`. Both values are stored on the conveyance
    and are not recomputed by any later operation; the conveyance moves
    `PENDING_TITLE → READY_TO_RECORD`."

    Design: Difficulty/combinatorial_formula/net_proceeds_curative_recovery_cap_binds_nested_min_max
    """
    ctx = _heavy_curative_conveyance(api)

    conveyance = fx.clear_title(api, ctx["conveyance"]["id"])
    assert conveyance["net_proceeds_cents"] == 89462501, (
        "105,250,001 less the capped 15,787,500 is 89,462,501, got "
        f"{conveyance['net_proceeds_cents']}"
    )
    assert conveyance["net_proceeds_cents"] != 85000001, (
        "deducting the uncapped 20,250,000 would have left 85,000,001, which is "
        "not the answer the cap produces"
    )
    assert conveyance["recording_status"] == "READY_TO_RECORD", (
        f"clearing title readies the deed, got {conveyance['recording_status']!r}"
    )
    assert conveyance["compliance_status"] == "NOT_MONITORED", (
        "the compliance dimension is not armed until recording, got "
        f"{conveyance['compliance_status']!r}"
    )


def test_03_the_curative_spend_moves_the_frozen_minimum_price_and_deposit(api):
    """The same curative spend deducts from the minimum price the offering froze.

    "The raw minimum is then the gross figure less the cure deduction." "The
    required deposit is the offering's own frozen `minimum_price_cents`
    multiplied by 0.05, rounded half up to a whole cent, and then raised to the
    floor of 5,000,000 cents if the product falls below it — so every offering
    priced below 100,000,000 cents demands the same flat 5,000,000-cent deposit."

    Design: Difficulty/combinatorial_formula/net_proceeds_curative_recovery_cap_binds_nested_min_max
    """
    ctx = _heavy_curative_conveyance(api)

    offering = ctx["offering"]
    assert offering["minimum_price_cents"] == 79750000, (
        "100,000,000 less the 20,250,000 cure deduction is 79,750,000, still "
        f"above the 70,000,000 carrying value, got {offering['minimum_price_cents']}"
    )
    assert offering["required_deposit_cents"] == 5000000, (
        "a twentieth of 79,750,000 is 3,987,500, below the floor, so the deposit "
        f"is the flat 5,000,000 cents, got {offering['required_deposit_cents']}"
    )


def test_04_fixed_reserve_is_taken_off_the_top_before_any_percentage_share(api):
    """Pass one pays the ranked reserve and posts a fixed-reserve row for it.

    "Pass one takes the statutory fixed reserves off the top. Starting with a
    remaining balance equal to `net_proceeds_cents`, the service walks the funds
    in `priority_rank` order and for each one takes the smaller of that fund's
    `fixed_reserve_cents` and the remaining balance."

    Design: Difficulty/combinatorial_formula/proceeds_waterfall_round_per_share_then_signed_residual_on_last_fund
    """
    ctx = _light_curative_recording(api)

    assert ctx["conveyance"]["net_proceeds_cents"] == 105000001, (
        "105,250,001 less the 250,000 recoverable curative cost is 105,000,001, "
        f"got {ctx['conveyance']['net_proceeds_cents']}"
    )
    rows = fx.allocations_for_conveyance(api, ctx["conveyance"]["id"])
    assert len(rows) == 4, (
        "the reserve fund takes no percentage share, so four rows are posted "
        f"across four funds, got {len(rows)}"
    )
    reserve_fund = find_row(ctx["funds"], fund_code="F-LAND")
    reserve_row = find_row(rows, fund_id=reserve_fund["id"])
    assert reserve_row is not None, "the ranked reserve fund must receive a row"
    assert reserve_row["amount_cents"] == 5000000, (
        f"the whole 5,000,000 reserve is available, got {reserve_row['amount_cents']}"
    )
    assert reserve_row["allocation_basis"] == "FIXED_RESERVE", (
        f"the reserve row is posted on the reserve basis, got {reserve_row['allocation_basis']!r}"
    )
    assert reserve_row["residual_included_cents"] == 0, (
        "the residual never lands on a fixed-reserve row, got "
        f"{reserve_row['residual_included_cents']}"
    )
    assert reserve_row["status"] == "POSTED", (
        f"every emitted row is posted, got {reserve_row['status']!r}"
    )


def test_05_each_percentage_share_is_rounded_against_the_captured_base(api):
    """Pass two rounds every share independently against the post-reserve base.

    "The surviving remaining balance is captured as the percentage base, and
    every fund whose `allocation_pct` is strictly greater than zero receives a
    row, again in `priority_rank` order: `amount_cents` is that fund's
    `allocation_pct` of the percentage base, rounded half up to a whole cent,
    with `allocation_basis` `PERCENTAGE` and `residual_included_cents` zero, and
    the remaining balance falls by each share as it is posted."
    "Every share is computed against the same captured base, never against a
    base that shrinks as rows are posted."

    Design: Difficulty/combinatorial_formula/proceeds_waterfall_round_per_share_then_signed_residual_on_last_fund
    """
    ctx = _light_curative_recording(api)

    rows = fx.allocations_for_conveyance(api, ctx["conveyance"]["id"])
    capital = find_row(rows, fund_id=find_row(ctx["funds"], fund_code="F-CAP")["id"])
    housing = find_row(rows, fund_id=find_row(ctx["funds"], fund_code="F-HOUSE")["id"])
    for label, row in (("F-CAP", capital), ("F-HOUSE", housing)):
        assert row is not None, f"{label} takes a percentage share and must receive a row"
        assert row["amount_cents"] == 30000000, (
            f"three tenths of the 100,000,001 base rounds to 30,000,000 for "
            f"{label}, got {row['amount_cents']}"
        )
        assert row["allocation_basis"] == "PERCENTAGE", (
            f"{label} is credited on the percentage basis, got {row['allocation_basis']!r}"
        )
        assert row["residual_included_cents"] == 0, (
            f"{label} is not the last percentage row, so it carries no residual, "
            f"got {row['residual_included_cents']}"
        )


def test_06_signed_residual_is_folded_into_the_last_percentage_row_alone(api):
    """Pass three places the one-cent remainder on the last-ranked share.

    "If the remaining balance is not zero after pass two, and at least one fund
    took part in the percentage split, the residual is folded into the last
    percentage row in `priority_rank` order: that row's `amount_cents` is
    increased by the remaining balance and its `residual_included_cents` is set
    to the remaining balance, after which the remaining balance is zero."

    Design: Difficulty/combinatorial_formula/proceeds_waterfall_round_per_share_then_signed_residual_on_last_fund
    """
    ctx = _light_curative_recording(api)

    rows = fx.allocations_for_conveyance(api, ctx["conveyance"]["id"])
    general_fund = find_row(ctx["funds"], fund_code="F-GEN")
    last_row = find_row(rows, fund_id=general_fund["id"])
    assert last_row is not None, "the last-ranked percentage fund must receive a row"
    assert last_row["amount_cents"] == 40000001, (
        "two fifths of 100,000,001 rounds to 40,000,000 and the one-cent "
        f"residual raises it to 40,000,001, got {last_row['amount_cents']}"
    )
    assert last_row["residual_included_cents"] == 1, (
        "the row must record the residual it absorbed, got "
        f"{last_row['residual_included_cents']}"
    )

    total = sum(row["amount_cents"] for row in rows)
    assert total == 105000001, (
        "the posted rows must equal the net proceeds to the cent, got "
        f"{total}"
    )
    assert ctx["conveyance"]["allocated_proceeds_cents"] == 105000001, (
        "the conveyance records the posted total, got "
        f"{ctx['conveyance']['allocated_proceeds_cents']}"
    )
    credited = get_success_data(
        api.get_fund(general_fund["id"], fx.FINANCE_HEADERS)
    )
    assert credited["balance_cents"] == 40000001, (
        "the credited fund's balance rises by the row's final amount, residual "
        f"included, got {credited['balance_cents']}"
    )
    assert credited["lifetime_credits_cents"] == 40000001, (
        "and so does its lifetime credit total, got "
        f"{credited['lifetime_credits_cents']}"
    )
