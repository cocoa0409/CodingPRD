"""Seller-side pricing: commission variants, the floor and cap, feed and the offset."""

from test_helpers import (
    add_buyer,
    advance_sale_day,
    assert_money,
    assert_settlement_balances,
    assign_pen,
    check_in_consignment,
    close_sale_day,
    create_consignment,
    create_lot,
    enter_ring,
    hammer_lot,
    invoice_for_registration,
    mark_lot_ready,
    read_buyer_invoice,
    read_lot,
    set_clock,
    settlement_for_consignment,
    setup_yard,
    weigh_lot,
)


def _two_consignments_on_different_commission_bases():
    """Two 10-head consignments sold for the same money on different bases."""
    scn = setup_yard()
    common = dict(
        pencil_shrink_pct=0.03,
        yardage_basis="PER_HEAD_DAY",
        ration_type="NONE",
        days_on_feed=0,
        advances_amount=0,
        hold_until_funds=False,
    )
    scn.consignment_tiered = create_consignment(
        scn.sale_day["id"],
        scn.consignor["id"],
        head_received=10,
        commission_basis="TIERED_VALUE",
        **common,
    )
    check_in_consignment(scn.consignment_tiered["id"])
    scn.lot_tiered = create_lot(scn.consignment_tiered["id"], head_count=10)
    assign_pen(scn.lot_tiered["id"], scn.pen["id"])
    weigh_lot(scn.lot_tiered["id"], scn.scale["id"], gross_weight_lb=7200, tare_weight_lb=200)
    mark_lot_ready(scn.lot_tiered["id"])

    scn.consignment_flat = create_consignment(
        scn.sale_day["id"],
        scn.consignor["id"],
        head_received=10,
        commission_basis="FLAT_PER_HEAD",
        **common,
    )
    check_in_consignment(scn.consignment_flat["id"])
    scn.lot_flat = create_lot(scn.consignment_flat["id"], head_count=10)
    assign_pen(scn.lot_flat["id"], scn.pen["id"])
    weigh_lot(scn.lot_flat["id"], scn.scale["id"], gross_weight_lb=7200, tare_weight_lb=200)
    mark_lot_ready(scn.lot_flat["id"])

    add_buyer(scn, bond_type="BONDED", credit_limit=50000)
    advance_sale_day(scn.sale_day["id"], "RINGING")

    for lot_key in ("lot_tiered", "lot_flat"):
        enter_ring(scn[lot_key]["id"])
        scn.lot = scn[lot_key]
        hammer_lot(scn, unit_price=182.50)

    advance_sale_day(scn.sale_day["id"], "BIDDING_CLOSED")
    set_clock("2026-06-02T10:00:00Z")
    close_sale_day(scn.sale_day["id"])

    scn.settlement_tiered = settlement_for_consignment(scn.consignment_tiered["id"])
    scn.settlement_flat = settlement_for_consignment(scn.consignment_flat["id"])
    return scn


def test_identical_gross_prices_a_different_commission_under_each_basis(api):
    """PRD §3.10: "On a flat-per-head basis it is simply 18.00 dollars for every sold
    head — the total `head_count` of the consignment's `SOLD` lots — rounded half up to
    two decimal places; the gross plays no part, and neither the per-head floor nor the
    per-lot cap applies."
    PRD §3.10: "On a tiered-value basis a rate is selected from the gross and then
    applied to the **whole** gross, not marginally: 5% when the gross is at most 1000.00,
    4% when it is above 1000.00 and at most 5000.00, and 3% above 5000.00."
    PRD §3.10: "The settlement's `gross_amount` is the total `extended_amount` of its
    consignment's lots whose `sale_status` is `SOLD`; lots at `NO_SALE`, `WITHDRAWN` or
    still in process contribute nothing."

    Design: Difficulty/dual_variant_calc/seller_commission_tiered_value_versus_flat_per_head_on_settlement
    """
    scn = _two_consignments_on_different_commission_bases()

    assert_money(scn.settlement_tiered["gross_amount"], 12391.75, "tiered settlement gross:")
    assert_money(scn.settlement_flat["gross_amount"], 12391.75, "flat settlement gross:")
    assert_money(scn.settlement_tiered["commission_amount"], 371.75, "3% of the whole gross:")
    assert_money(scn.settlement_flat["commission_amount"], 180.00, "18.00 for every sold head:")
    assert (
        scn.settlement_tiered["commission_amount"] != scn.settlement_flat["commission_amount"]
    ), "the same money must price differently under the two bases"


def test_the_remaining_deductions_are_identical_and_only_the_net_diverges(api):
    """PRD §3.10: "**Net proceeds** close the arithmetic: `net_amount` is
    `gross_amount`, less `commission_amount`, less `yardage_amount`, less `feed_amount`,
    less `statutory_amount`, less `brand_fee_amount`, less `indemnity_fee_amount`, less
    `advances_amount`, less `offset_applied`, plus `adjustment_total`, rounded half up to
    two decimal places."
    PRD §3.10: "**The brand inspection fee** is 1.20 dollars multiplied by the same
    sold-head figure, rounded half up to two decimal places."
    PRD §3.10: "Take 0.15% of the settlement's `gross_amount` — that is, the gross
    multiplied by 0.0015 — rounded half up to two decimal places; then take the greater
    of that and 0.50, and then the lesser of the result and 25.00."
    PRD §2.10: "A settlement's `balance_ok` is true when its `gross_amount` equals
    `net_amount` plus `commission_amount` plus `yardage_amount` plus `feed_amount` plus
    `statutory_amount` plus `brand_fee_amount` plus `indemnity_fee_amount` plus
    `advances_amount` plus `offset_applied` minus `adjustment_total`."

    Design: Difficulty/dual_variant_calc/seller_commission_tiered_value_versus_flat_per_head_on_settlement
    """
    scn = _two_consignments_on_different_commission_bases()
    tiered = scn.settlement_tiered

    assert_money(tiered["yardage_amount"], 35.00, "1.75 x 10 head x 2 days:")
    assert_money(tiered["statutory_amount"], 10.00, "0.50 + 0.50 for every sold head:")
    assert_money(tiered["brand_fee_amount"], 12.00, "1.20 x 10 sold head:")
    assert_money(tiered["indemnity_fee_amount"], 18.59, "0.0015 of the gross:")
    assert_money(tiered["net_amount"], 11944.41, "tiered net proceeds:")
    assert_money(scn.settlement_flat["net_amount"], 12136.16, "flat-per-head net proceeds:")
    assert tiered["balance_ok"] is True
    assert_settlement_balances(tiered)


def _floor_and_cap_settlements():
    """A 500.00 gross over 10 head and a 24000.00 gross over 40 head."""
    scn = setup_yard()
    common = dict(
        pencil_shrink_pct=0.03,
        commission_basis="TIERED_VALUE",
        yardage_basis="PER_HEAD_DAY",
        ration_type="NONE",
        days_on_feed=0,
    )
    scn.consignment_small = create_consignment(
        scn.sale_day["id"], scn.consignor["id"], head_received=10, **common
    )
    check_in_consignment(scn.consignment_small["id"])
    scn.lot_small = create_lot(
        scn.consignment_small["id"],
        head_count=10,
        livestock_class="CALF",
        bid_basis="PER_HEAD",
        opening_bid=40.00,
        reserve_price=45.00,
    )
    assign_pen(scn.lot_small["id"], scn.pen["id"])
    weigh_lot(scn.lot_small["id"], scn.scale["id"], gross_weight_lb=5200, tare_weight_lb=200)
    mark_lot_ready(scn.lot_small["id"])

    scn.consignment_big = create_consignment(
        scn.sale_day["id"], scn.consignor["id"], head_received=40, **common
    )
    check_in_consignment(scn.consignment_big["id"])
    scn.lot_big = create_lot(
        scn.consignment_big["id"],
        head_count=40,
        bid_basis="PER_HEAD",
        opening_bid=500.00,
        reserve_price=550.00,
    )
    assign_pen(scn.lot_big["id"], scn.pen["id"])
    weigh_lot(
        scn.lot_big["id"],
        scn.scale["id"],
        head_on_draft=40,
        gross_weight_lb=26200,
        tare_weight_lb=200,
    )
    mark_lot_ready(scn.lot_big["id"])

    add_buyer(scn, bond_type="BONDED", credit_limit=50000)
    advance_sale_day(scn.sale_day["id"], "RINGING")

    enter_ring(scn.lot_small["id"])
    scn.lot = scn.lot_small
    hammer_lot(scn, unit_price=50.00)
    enter_ring(scn.lot_big["id"])
    scn.lot = scn.lot_big
    hammer_lot(scn, unit_price=600.00)

    advance_sale_day(scn.sale_day["id"], "BIDDING_CLOSED")
    set_clock("2026-06-01T20:00:00Z")
    close_sale_day(scn.sale_day["id"])
    scn.settlement_small = settlement_for_consignment(scn.consignment_small["id"])
    scn.settlement_big = settlement_for_consignment(scn.consignment_big["id"])
    return scn


def test_a_thin_gross_settles_on_the_per_head_commission_floor(api):
    """PRD §3.10: "That tiered figure, rounded half up to two decimal places, is then
    floored at a per-head minimum of 4.00 dollars per sold head (itself rounded half up
    to two decimal places) and capped at 450.00 for the settlement — the greater of the
    tiered figure and the floor, then the lesser of that and the cap."
    PRD §3.8: "On a `PER_HEAD` lot the extension is the unit price multiplied by
    `head_count`, rounded half up to two decimal places, and the weigh-in result does not
    affect the money at all."
    PRD §3.10: "then take the greater of that and 0.50, and then the lesser of the
    result and 25.00."

    Design: Difficulty/combinatorial_formula/commission_floor_and_cap_nesting_mode_a
    """
    scn = _floor_and_cap_settlements()

    assert_money(
        read_lot(scn.lot_small["id"])["extended_amount"],
        500.00,
        "50.00 per head on 10 head, the settle weight playing no part:",
    )
    assert_money(
        scn.settlement_small["commission_amount"],
        40.00,
        "the 25.00 tiered figure is lifted to the 4.00-per-head floor:",
    )
    assert_money(scn.settlement_small["indemnity_fee_amount"], 0.75, "0.0015 of 500.00:")
    assert_money(scn.settlement_small["yardage_amount"], 17.50, "1.75 x 10 head x one day:")
    assert_money(scn.settlement_small["net_amount"], 419.75, "net proceeds on the thin lot:")


def test_a_fat_gross_settles_on_the_commission_cap(api):
    """PRD §3.10: "That tiered figure, rounded half up to two decimal places, is then
    floored at a per-head minimum of 4.00 dollars per sold head (itself rounded half up
    to two decimal places) and capped at 450.00 for the settlement — the greater of the
    tiered figure and the floor, then the lesser of that and the cap."
    PRD §3.10: "The floor therefore binds on any gross below about 333 dollars and the
    cap on any gross above about 16,667 dollars."

    Design: Difficulty/combinatorial_formula/commission_floor_and_cap_nesting_mode_a
    """
    scn = _floor_and_cap_settlements()

    assert_money(
        read_lot(scn.lot_big["id"])["extended_amount"],
        24000.00,
        "600.00 per head on 40 head:",
    )
    assert_money(
        scn.settlement_big["commission_amount"],
        450.00,
        "the 720.00 tiered figure is pulled down to the cap:",
    )
    assert_money(scn.settlement_big["indemnity_fee_amount"], 25.00, "the indemnity cap binds:")
    assert_money(scn.settlement_big["yardage_amount"], 70.00, "1.75 x 40 head x one day:")
    assert_money(scn.settlement_big["net_amount"], 23367.00, "net proceeds on the fat lot:")


def _feed_settlement():
    """A GROWER consignment fed three days, sorted into lots of 7 and 3 head."""
    scn = setup_yard(with_pen=False, with_scale=False)
    scn.consignment = create_consignment(
        scn.sale_day["id"],
        scn.consignor["id"],
        head_received=10,
        pencil_shrink_pct=0.03,
        ration_type="GROWER",
        days_on_feed=3,
        yardage_basis="PER_HEAD_DAY",
        commission_basis="TIERED_VALUE",
    )
    check_in_consignment(scn.consignment["id"])
    scn.lot_seven = create_lot(scn.consignment["id"], head_count=7)
    scn.lot_three = create_lot(scn.consignment["id"], head_count=3)
    advance_sale_day(scn.sale_day["id"], "RINGING")
    advance_sale_day(scn.sale_day["id"], "BIDDING_CLOSED")
    set_clock("2026-06-01T20:00:00Z")
    close_sale_day(scn.sale_day["id"])
    scn.settlement = settlement_for_consignment(scn.consignment["id"])
    return scn


def test_feed_rounds_every_lot_line_before_the_lines_are_summed(api):
    """PRD §3.10: "The daily rate per head is 0.955 dollars on a `STARTER` ration,
    1.405 on `GROWER`, 0.605 on `HAY`, and nothing at all when `ration_type` is `NONE`."
    PRD §3.10: "Walk the consignment's lots whose `sale_status` is not `WITHDRAWN` in
    ascending `created_at` order; for each, multiply the rate by the consignment's
    `days_on_feed` and by that lot's `head_count`, and round **that line** half up to two
    decimal places."
    PRD §3.10: "`feed_amount` is the sum of those already-rounded line figures. Summing
    first and rounding once is wrong and lands on a different cent."

    Design: Difficulty/combinatorial_formula/feed_charge_round_per_line_then_sum_mode_b
    """
    scn = _feed_settlement()

    assert_money(
        scn.settlement["feed_amount"],
        42.16,
        "29.51 on the seven-head line plus 12.65 on the three-head line:",
    )
    assert scn.settlement["feed_amount"] != 42.15, (
        "summing first and rounding once lands on the wrong cent"
    )


def test_an_unsold_consignment_still_owes_yardage_and_feed(api):
    """PRD §3.10: "The settlement's `gross_amount` is the total `extended_amount` of
    its consignment's lots whose `sale_status` is `SOLD`; lots at `NO_SALE`, `WITHDRAWN`
    or still in process contribute nothing."
    PRD §3.10: "Only `SOLD` head count — no-sale head, withdrawn head, death loss and
    condemned head are all excluded."
    PRD §3.10: "When `gross_amount` is zero the indemnity fee is 0.00 and neither bound
    applies."
    PRD §3.10: "**Yardage** is levied on billable head, which is the consignment's
    `head_in_lots` plus its `head_withdrawn` plus its `head_dead` plus its
    `head_condemned` — every head that actually stood on the yard, sold or not."

    Design: Difficulty/combinatorial_formula/feed_charge_round_per_line_then_sum_mode_b
    """
    scn = _feed_settlement()

    assert_money(scn.settlement["gross_amount"], 0.00, "nothing was sold:")
    assert_money(scn.settlement["commission_amount"], 0.00, "no gross and no sold head:")
    assert_money(scn.settlement["yardage_amount"], 17.50, "1.75 x 10 billable head x one day:")
    assert_money(scn.settlement["statutory_amount"], 0.00, "the checkoff counts sold head only:")
    assert_money(scn.settlement["indemnity_fee_amount"], 0.00, "a zero gross levies nothing:")
    assert_money(scn.settlement["net_amount"], -59.66, "the consignor owes the barn:")

    assert read_lot(scn.lot_seven["id"])["sale_status"] == "NO_SALE"
    assert read_lot(scn.lot_three["id"])["sale_status"] == "NO_SALE"


def test_a_consignor_buy_back_clears_the_reserve_and_still_owes_commission(api):
    """PRD §3.8: "Its `unit_price` must be at least the lot's `reserve_price`, unless
    the request elects buy-back **and** the winning registration's party is the same
    party as the consignment's consignor; falling short of reserve without a qualifying
    buy-back is refused with `ERR_RESERVE_NOT_MET`."
    PRD §3.10: "Step five: the candidate invoices are the buyer invoices of this same
    sale day whose registration's `party_id` equals this settlement's
    `consignor_party_id` and whose `status` is `ISSUED` or `PARTIALLY_PAID`, taken in
    ascending `created_at` order."
    PRD §3.10: "Step six: the provisional net is poured down that list, taking from
    each invoice the lesser of what remains to pour and that invoice's `balance_due`.
    `offset_applied` is the total poured, rounded half up to two decimal places."

    Design: Corner/validations/corner_consignor_buyback_below_reserve_succeeds_and_still_owes_commission
    """
    scn = setup_yard()
    scn.consignment = create_consignment(
        scn.sale_day["id"], scn.consignor["id"], head_received=10, pencil_shrink_pct=0.03
    )
    check_in_consignment(scn.consignment["id"])
    scn.lot = create_lot(scn.consignment["id"], head_count=10, reserve_price=200.00)
    assign_pen(scn.lot["id"], scn.pen["id"])
    weigh_lot(scn.lot["id"], scn.scale["id"], gross_weight_lb=7200, tare_weight_lb=200)
    mark_lot_ready(scn.lot["id"])

    add_buyer(scn, buyer_party=scn.consignor, bond_type="BONDED", credit_limit=50000)
    advance_sale_day(scn.sale_day["id"], "RINGING")
    enter_ring(scn.lot["id"])
    hammer_lot(scn, unit_price=182.50, buy_back=True)

    lot = read_lot(scn.lot["id"])
    assert lot["buy_back"] is True
    assert lot["sale_status"] == "SOLD"
    assert_money(lot["extended_amount"], 12391.75, "the bought-back lot still extends:")

    advance_sale_day(scn.sale_day["id"], "BIDDING_CLOSED")
    set_clock("2026-06-02T10:00:00Z")
    close_sale_day(scn.sale_day["id"])

    invoice = read_buyer_invoice(invoice_for_registration(scn.registration["id"])["id"])
    assert_money(invoice["total_due"], 12422.73, "the consignor's own buyer invoice:")

    settlement = settlement_for_consignment(scn.consignment["id"])
    assert_money(settlement["gross_amount"], 12391.75, "settlement gross:")
    assert_money(settlement["commission_amount"], 371.75, "a buy-back is not commission-free:")
    assert_money(settlement["yardage_amount"], 35.00, "1.75 x 10 head x 2 days:")
    assert_money(settlement["statutory_amount"], 10.00, "1.00 for every sold head:")
    assert_money(settlement["brand_fee_amount"], 12.00, "1.20 x 10 sold head:")
    assert_money(
        settlement["offset_applied"],
        11944.41,
        "the whole provisional net is poured into the consignor's own invoice:",
    )
    assert_money(settlement["net_amount"], 0.00, "nothing is left to hand over:")
    assert settlement["balance_ok"] is True
    assert_settlement_balances(settlement)
