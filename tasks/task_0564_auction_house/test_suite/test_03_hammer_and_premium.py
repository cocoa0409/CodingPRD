"""The fall of the hammer: reserve / no-bid guards, buy-ins, the tiered buyer's
premium, the round-then-sum invoice subtotal, and the hammer billing cascade.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    setup_open_lot,
    setup_single_hammer,
    setup_two_hammers_one_bidder,
    make_bidder,
    place_bid,
    assert_line_total_consistent,
    TEST_USERS,
)

STAFF = TEST_USERS["staff_headers"]
APPRAISER = TEST_USERS["appraiser_headers"]


# ─── Corner: hammer guards and buy-in ────────────────────────────────────

def test_hammer_with_no_bids_rejected(api):
    """PRD §3.5: "at least one `ACTIVE` bid must exist on the lot, else
    `ERR_NO_BIDS` (HTTP 409)".

    Design: Corner/state_machines/corner_hammer_no_bids_returns_conflict
    """
    bag = setup_open_lot(starting_bid_cents=100_000)
    res = api.hammer_lot(bag["lot"]["id"], STAFF)
    validate_error(res, "ERR_NO_BIDS")


def test_hammer_below_reserve_rejected(api):
    """PRD §3.5: "the lot's `current_high_bid_cents` must be at least its
    `reserve_cents`, else `ERR_RESERVE_NOT_MET` (HTTP 409)."

    Design: Corner/state_machines/corner_hammer_reserve_not_met_returns_conflict
    """
    bag = setup_open_lot(reserve_cents=500_000, starting_bid_cents=100_000,
                         estimate_low_cents=400_000, estimate_high_cents=900_000)
    bidder = make_bidder()
    place_bid(bag["lot"]["id"], bidder["id"], 100_000, bag["lot_version"])
    res = api.hammer_lot(bag["lot"]["id"], STAFF)
    validate_error(res, "ERR_RESERVE_NOT_MET")


def test_pass_lot_buys_in_and_outbids_without_invoice(api):
    """PRD §3.5: "Passing advances the lot `OPEN → PASSED`, transitions every
    `ACTIVE` bid on the lot `ACTIVE → OUTBID`, and creates no invoice and no
    invoice line."

    Design: Corner/state_machines/corner_lot_pass_buy_in_valid
    """
    bag = setup_open_lot(reserve_cents=500_000, starting_bid_cents=100_000,
                         estimate_low_cents=400_000, estimate_high_cents=900_000)
    bidder = make_bidder()
    bid = place_bid(bag["lot"]["id"], bidder["id"], 100_000, bag["lot_version"])
    lot = validate_success(api.pass_lot(bag["lot"]["id"], STAFF), 200)
    assert lot["sale_status"] == "PASSED"
    assert validate_success(api.get_bid(bid["id"], STAFF), 200)["status"] == "OUTBID"
    data, _ = validate_paginated(
        api.list_invoices(STAFF, params={"bidder_id": bidder["id"],
                                         "auction_id": bag["auction"]["id"]})
    )
    assert len(data) == 0


def test_appraiser_cannot_hammer(api):
    """PRD §2.1: "When the headers are valid but the role is not permitted to
    invoke the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/corner_appraiser_cannot_hammer_returns_403
    """
    bag = setup_open_lot(starting_bid_cents=200_000,
                         estimate_low_cents=100_000, estimate_high_cents=400_000)
    bidder = make_bidder()
    place_bid(bag["lot"]["id"], bidder["id"], 250_000, bag["lot_version"])
    res = api.hammer_lot(bag["lot"]["id"], APPRAISER)
    validate_error(res, "ERR_UNAUTHORIZED")


# ─── Difficulty: tiered buyer's premium (marginal, three bands) ──────────

def test_buyers_premium_tiered_marginal_amount(api):
    """PRD §3.5: "Twenty-five percent applies to the first 300,000 cents of hammer
    price; twenty percent applies to the portion of hammer price above 300,000
    cents and up to 2,000,000 cents; and fifteen percent applies to any portion
    above 2,000,000 cents. The three portions are summed, and the result is
    rounded once, using round-half-up, to whole cents to yield the line's
    `buyers_premium_cents`."

    Design: Difficulty/combinatorial_formula/cf_buyers_premium_tiered_marginal
    """
    bag = setup_single_hammer(500_000, starting_bid_cents=400_000)
    assert bag["lot"]["hammer_price_cents"] == 500_000
    assert bag["line"]["buyers_premium_cents"] == 115_000


def test_buyers_premium_line_total(api):
    """PRD §3.5: "the `line_total_cents` equal to the line's hammer price plus its
    premium".

    Design: Difficulty/combinatorial_formula/cf_buyers_premium_tiered_marginal
    """
    bag = setup_single_hammer(500_000, starting_bid_cents=400_000)
    assert bag["line"]["line_total_cents"] == 615_000
    assert_line_total_consistent(bag["line"])


# ─── Difficulty: round-per-line-then-sum premium subtotal ────────────────

def test_premium_subtotal_rounds_each_line_before_summing(api):
    """PRD §3.5: "`premium_subtotal_cents` becomes the sum of the already-rounded
    `buyers_premium_cents` over those same lines — because each line's premium was
    rounded when the line was created, summing introduces no further rounding."

    Design: Difficulty/combinatorial_formula/cf_invoice_premium_round_then_sum
    """
    bag = setup_two_hammers_one_bidder(100_001, 100_001,
                                       starting1=100_001, starting2=100_001,
                                       estimate_low_cents=100_000,
                                       estimate_high_cents=200_000)
    # round_half_up(0.25 * 100001) = round_half_up(25000.25) = 25000 per line.
    assert bag["invoice"]["premium_subtotal_cents"] == 50_000


def test_invoice_hammer_subtotal_and_total_after_two_lines(api):
    """PRD §3.5: "`hammer_subtotal_cents` becomes the sum of `hammer_price_cents`
    over the invoice's non-void (`ACTIVE`) lines".
    PRD §3.5: "The `total_due_cents` is then `hammer_subtotal_cents` plus
    `premium_subtotal_cents` plus `storage_fee_cents` plus `shipping_fee_cents`."

    Design: Difficulty/combinatorial_formula/cf_invoice_premium_round_then_sum
    """
    bag = setup_two_hammers_one_bidder(100_001, 100_001,
                                       starting1=100_001, starting2=100_001,
                                       estimate_low_cents=100_000,
                                       estimate_high_cents=200_000)
    assert bag["invoice"]["hammer_subtotal_cents"] == 200_002
    assert bag["invoice"]["total_due_cents"] == 250_002


# ─── Difficulty: hammer -> line -> invoice-total depth-3 cascade ─────────

def test_hammer_cascades_lot_and_line(api):
    """PRD §3.5: "Hammering advances the lot `OPEN → HAMMERED`".
    PRD §3.5: "A new `InvoiceLine` is created against that invoice, recording the
    `invoice_id`, the `lot_id`, the `hammer_price_cents` copied from the lot, the
    `buyers_premium_cents` computed for this line, and the `line_total_cents` equal
    to the line's hammer price plus its premium".

    Design: Difficulty/transitive_cascade/tc_hammer_lot_to_line_to_invoice_total
    """
    bag = setup_single_hammer(500_000, starting_bid_cents=400_000)
    assert bag["lot"]["sale_status"] == "HAMMERED"
    assert bag["line"]["buyers_premium_cents"] == 115_000
    assert bag["line"]["line_total_cents"] == 615_000


def test_hammer_cascade_recomputes_invoice_total(api):
    """PRD §3.5: "the invoice totals recompute: `hammer_subtotal_cents` becomes
    the sum of `hammer_price_cents` over the invoice's non-void (`ACTIVE`) lines".
    PRD §3.5: "The `total_due_cents` is then `hammer_subtotal_cents` plus
    `premium_subtotal_cents` plus `storage_fee_cents` plus `shipping_fee_cents`."

    Design: Difficulty/transitive_cascade/tc_hammer_lot_to_line_to_invoice_total
    """
    bag = setup_single_hammer(500_000, starting_bid_cents=400_000)
    assert bag["invoice"]["total_due_cents"] == 615_000
