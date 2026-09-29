"""Fixed-price purchases: the exact-ask rule, the premium tier table and freight."""

from test_helpers import (
    ADMIN,
    api_client,
    assert_bid,
    assert_instant,
    assert_sale_order,
    bid_payload,
    bootstrap_marketplace,
    buy_at_ask,
    create_listing,
    fixed_price_listing_payload,
    order_for_listing,
    pay_order,
    publish_listing,
    read_buyer,
    read_listing,
    read_lot,
    read_order,
    read_seller,
    set_clock,
    setup_approved_lot,
    setup_fixed_price_order,
    setup_open_fixed_price,
    total_count,
    validate_error,
    validate_success,
)

TWO_HUNDRED_UNIT_LINES = [
    {
        "sku": "APP-FP-0200",
        "unit_count": 200,
        "unit_retail_cents": 10_000,
        "declared_condition": "USED_GOOD",
    },
]

TWO_HUNDRED_ONE_UNIT_LINES = [
    {
        "sku": "HG-FP-0201",
        "unit_count": 201,
        "unit_retail_cents": 10_000,
        "declared_condition": "USED_GOOD",
    },
]

FIFTY_UNIT_LINES = [
    {
        "sku": "TOY-FP-0050",
        "unit_count": 50,
        "unit_retail_cents": 20_000,
        "declared_condition": "NEW",
    },
]


def test_a_purchase_at_the_exact_ask_fires_the_whole_sale_cascade_in_one_call():
    """One bid at the ask price wins outright, closes the listing, sells the lot and
    lands a fully costed provisional order with both deadlines fixed.

    PRD 3.5: "An accepted purchase creates a `Bid` with `bid_type` `LIVE` whose
    `bid_status` is `WON` immediately, advances the listing `OPEN → CLOSED_SOLD`,
    advances the lot `LISTED → SOLD`, and creates one sale order with `sale_source`
    `FIXED_PRICE_PURCHASE` and `hammer_price_cents` equal to `ask_price_cents`."
    PRD 3.6: "The waterfall itself runs in a fixed order. First,
    `pre_fee_total_cents` is `hammer_price_cents` plus `buyer_premium_cents` plus
    the freight term of the active `settlement_basis`."
    PRD 3.6: "Finally, two deadlines are fixed from the order's `created_at`:
    `payment_due_at` is three days after creation and `pickup_deadline_at` is ten
    days after creation."
    PRD 3.6: "`payment_status` tracks money and moves through `UNPAID`,
    `PARTIALLY_PAID`, `PAID` and `REFUND_ISSUED`."

    Design: Corner/state_machines/fixed_price_purchase_closes_the_listing_and_sells_the_lot
    """
    built = setup_fixed_price_order(lines=TWO_HUNDRED_UNIT_LINES)
    env = built["env"]

    bid = built["bid"]
    assert_bid(bid)
    assert bid["bid_status"] == "WON"
    assert bid["bid_type"] == "LIVE"
    assert bid["ceiling_cents"] == 1_000_000

    assert read_listing(env, built["listing"]["id"])["listing_status"] == "CLOSED_SOLD"
    assert read_lot(env, built["lot"]["id"])["lot_status"] == "SOLD"

    order = read_order(env, built["order"]["id"])
    assert_sale_order(order)
    assert order["sale_source"] == "FIXED_PRICE_PURCHASE"
    assert order["hammer_price_cents"] == 1_000_000
    assert order["buyer_premium_bps"] == 1_400
    assert order["buyer_premium_cents"] == 140_000
    assert order["pallet_count"] == 1
    assert order["estimated_freight_cents"] == 8_500
    assert order["settlement_basis"] == "PROVISIONAL"
    assert order["pre_fee_total_cents"] == 1_148_500
    assert order["total_due_cents"] == 1_148_500
    assert order["balance_due_cents"] == 1_148_500
    assert order["payment_status"] == "UNPAID"
    assert order["logistics_status"] == "AWAITING_APPOINTMENT"
    assert_instant(order["payment_due_at"], "2026-08-08T01:00:00Z")
    assert_instant(order["pickup_deadline_at"], "2026-08-15T01:00:00Z")
    assert read_buyer(env)["outstanding_exposure_cents"] == 1_148_500


def test_underpaying_and_overpaying_the_ask_are_both_refused():
    """A cent short and a cent over are the same mistake, and neither disturbs the
    open listing; only the exact amount buys the lot.

    PRD 3.5: "On a listing whose `listing_format` is `FIXED_PRICE`, a `Buyer`
    commits by placing a live bid whose `amount_cents` equals the listing's
    `ask_price_cents` exactly — not at least, exactly. Any other amount is
    `ERR_FIXED_PRICE_MISMATCH`."
    PRD 3.4: "The listing's `bid_count` counts this listing's bids whose
    `bid_status` is `STANDING`, `WINNING`, `WON` or `LOST`."

    Design: Corner/endpoints/fixed_price_bid_must_equal_the_ask_price_exactly
    """
    built = setup_open_fixed_price(lines=TWO_HUNDRED_UNIT_LINES)
    env = built["env"]
    listing = built["listing"]
    buyer_id = env["buyer"]["id"]

    too_low = api_client.place_bid(
        listing["id"], bid_payload(buyer_id, 999_999), env["buyer_headers"]
    )
    validate_error(too_low, "ERR_FIXED_PRICE_MISMATCH", 422)

    too_high = api_client.place_bid(
        listing["id"], bid_payload(buyer_id, 1_000_001), env["buyer_headers"]
    )
    validate_error(too_high, "ERR_FIXED_PRICE_MISMATCH", 422)

    still_open = read_listing(env, listing["id"])
    assert still_open["listing_status"] == "OPEN"
    assert still_open["bid_count"] == 0

    accepted = validate_success(
        api_client.place_bid(
            listing["id"], bid_payload(buyer_id, 1_000_000), env["buyer_headers"]
        ),
        201,
    )
    assert accepted["bid_status"] == "WON"
    assert accepted["ceiling_cents"] == 1_000_000

    assert read_listing(env, listing["id"])["listing_status"] == "CLOSED_SOLD"
    assert read_lot(env, built["lot"]["id"])["lot_status"] == "SOLD"
    assert total_count(
        api_client.list_sale_orders(ADMIN, {"listing_id": listing["id"]})
    ) == 1
    order = order_for_listing(listing["id"], ADMIN)
    assert order["sale_source"] == "FIXED_PRICE_PURCHASE"
    assert order["hammer_price_cents"] == 1_000_000
    assert order["total_due_cents"] == 1_148_500


def _open_fixed_price_lot(env, lines, ask_price_cents, *, title, category_code="TOYS"):
    """An approved lot of its own carrying a published FIXED_PRICE listing."""
    built = setup_approved_lot(
        env,
        lines,
        title=title,
        category_code=category_code,
        condition_grade="NEW_OVERSTOCK",
    )
    listing = create_listing(
        env, built["lot"]["id"], fixed_price_listing_payload(ask_price_cents)
    )
    return {"lot": built["lot"], "listing": publish_listing(env, listing["id"])}


def test_a_hammer_of_exactly_one_million_cents_still_pays_the_fourteen_percent_rate():
    """The first premium tier is inclusive at its top, so the round million is
    charged 1,400 basis points while one cent more drops to 1,200.

    PRD 3.6: "A `hammer_price_cents` of at most 1,000,000 cents selects a
    `buyer_premium_bps` of 1,400 basis points, that is 14 percent. A hammer price
    above 1,000,000 cents and at most 2,500,000 cents selects 1,200 basis points, 12
    percent."
    PRD 3.6: "`buyer_premium_cents` is then the hammer price multiplied by the
    selected rate, divided by 10,000, and rounded half up to a whole cent."
    PRD 3.6: "`pallet_count` is the lot's `declared_unit_count` divided by 200 units
    per pallet and rounded **up** to a whole pallet, so 400 units occupy 2 pallets
    while 401 units occupy 3, and 445 units also occupy 3."

    Design: Difficulty/boundary_precision_check/buyer_premium_tier_boundary_at_exactly_one_million_cents
    """
    env = bootstrap_marketplace()
    on_bound = _open_fixed_price_lot(
        env, FIFTY_UNIT_LINES, 1_000_000, title="Toys overstock P1"
    )
    past_bound = _open_fixed_price_lot(
        env, FIFTY_UNIT_LINES, 1_000_001, title="Toys overstock P2"
    )
    set_clock("2026-08-05T01:00:00Z")

    first = buy_at_ask(env, on_bound["listing"])["order"]
    second = buy_at_ask(env, past_bound["listing"])["order"]

    order_one = read_order(env, first["id"])
    assert order_one["hammer_price_cents"] == 1_000_000
    assert order_one["buyer_premium_bps"] == 1_400
    assert order_one["buyer_premium_cents"] == 140_000
    assert order_one["total_due_cents"] == 1_148_500

    order_two = read_order(env, second["id"])
    assert order_two["hammer_price_cents"] == 1_000_001
    assert order_two["buyer_premium_bps"] == 1_200
    assert order_two["buyer_premium_cents"] == 120_000
    assert order_two["total_due_cents"] == 1_128_501

    for order in (order_one, order_two):
        assert order["pallet_count"] == 1
        assert order["estimated_freight_cents"] == 8_500
        assert order["settlement_basis"] == "PROVISIONAL"


def test_the_dearer_lot_carries_the_cheaper_premium_and_the_smaller_total():
    """Because the table is flat rather than marginal, one extra cent of hammer price
    removes 20,000 cents of premium and 19,999 cents of exposure.

    PRD 3.6: "Both boundaries are inclusive at the top of their tier, so a hammer
    price of exactly 1,000,000 cents is charged 14 percent while a hammer price one
    cent higher is charged 12 percent **on the entire amount**, not merely on the
    excess."
    PRD 3.2: "The second part covers unsettled orders: over all of this buyer's sale
    orders whose `payment_status` is `UNPAID` or `PARTIALLY_PAID` and whose
    `logistics_status` is not `ABANDONED`, sum `balance_due_cents`."
    PRD 3.2: "Bids whose `bid_status` is `SUPERSEDED`, `WON` or `LOST` drop out of
    this part entirely; a `WON` commitment is represented by its sale order instead."

    Design: Difficulty/boundary_precision_check/buyer_premium_tier_boundary_at_exactly_one_million_cents
    """
    env = bootstrap_marketplace()
    on_bound = _open_fixed_price_lot(
        env, FIFTY_UNIT_LINES, 1_000_000, title="Toys overstock P1"
    )
    past_bound = _open_fixed_price_lot(
        env, FIFTY_UNIT_LINES, 1_000_001, title="Toys overstock P2"
    )
    set_clock("2026-08-05T01:00:00Z")

    order_one = read_order(env, buy_at_ask(env, on_bound["listing"])["order"]["id"])
    order_two = read_order(env, buy_at_ask(env, past_bound["listing"])["order"]["id"])

    assert order_two["hammer_price_cents"] - order_one["hammer_price_cents"] == 1
    assert order_one["buyer_premium_cents"] - order_two["buyer_premium_cents"] == 20_000
    assert order_one["total_due_cents"] - order_two["total_due_cents"] == 19_999
    assert order_two["buyer_premium_cents"] < order_one["buyer_premium_cents"]
    assert order_two["total_due_cents"] < order_one["total_due_cents"]
    assert read_buyer(env)["outstanding_exposure_cents"] == 2_277_001


def test_the_two_hundredth_and_two_hundred_first_unit_sit_on_opposite_sides_of_a_pallet():
    """Pallets are counted by ceiling, so one extra unit buys a whole second pallet
    and 8,500 more cents of freight at an unchanged hammer price.

    PRD 3.6: "**Freight** is billed per whole pallet. `pallet_count` is the lot's
    `declared_unit_count` divided by 200 units per pallet and rounded **up** to a
    whole pallet, so 400 units occupy 2 pallets while 401 units occupy 3, and 445
    units also occupy 3. `estimated_freight_cents` is that pallet count multiplied by
    8,500 cents per pallet."
    PRD 3.6: "Both are computed once, at order creation, from the lot's declared unit
    count as it stood at that instant."
    PRD 3.6: "A `hammer_price_cents` of at most 1,000,000 cents selects a
    `buyer_premium_bps` of 1,400 basis points, that is 14 percent."

    Design: Corner/calculations/freight_estimate_pallet_ceiling_flips_between_two_hundred_and_two_hundred_one_units
    """
    env = bootstrap_marketplace()
    one_pallet = _open_fixed_price_lot(
        env,
        TWO_HUNDRED_UNIT_LINES,
        1_000_000,
        title="Apparel pallet lot A",
        category_code="APPAREL",
    )
    two_pallets = _open_fixed_price_lot(
        env,
        TWO_HUNDRED_ONE_UNIT_LINES,
        1_000_000,
        title="Home goods pallet lot B",
        category_code="HOME_GOODS",
    )
    set_clock("2026-08-05T01:00:00Z")

    order_a = read_order(env, buy_at_ask(env, one_pallet["listing"])["order"]["id"])
    order_b = read_order(env, buy_at_ask(env, two_pallets["listing"])["order"]["id"])

    assert order_a["pallet_count"] == 1
    assert order_a["estimated_freight_cents"] == 8_500
    assert order_b["pallet_count"] == 2
    assert order_b["estimated_freight_cents"] == 17_000

    for order in (order_a, order_b):
        assert order["hammer_price_cents"] == 1_000_000
        assert order["buyer_premium_bps"] == 1_400
        assert order["buyer_premium_cents"] == 140_000

    assert order_a["total_due_cents"] == 1_148_500
    assert order_b["total_due_cents"] == 1_157_000
    assert order_b["total_due_cents"] - order_a["total_due_cents"] == 8_500
    assert read_buyer(env)["outstanding_exposure_cents"] == 2_305_500


def test_every_write_is_already_final_in_its_own_response_and_in_the_next_read():
    """The purchase resolves inside its own request, the cascade-created order is
    queryable on the very next call, the payment response carries the recomputed
    money, and a second read of the denormalised figures adds nothing.

    PRD 3.5: "An accepted purchase creates a `Bid` with `bid_type` `LIVE` whose
    `bid_status` is `WON` immediately, advances the listing `OPEN → CLOSED_SOLD`,
    advances the lot `LISTED → SOLD`, and creates one sale order with `sale_source`
    `FIXED_PRICE_PURCHASE` and `hammer_price_cents` equal to `ask_price_cents`."
    PRD 3.6: "An accepted payment increases `amount_paid_cents` by the paid amount
    and recomputes `balance_due_cents`. A payment smaller than the outstanding
    balance advances `UNPAID → PARTIALLY_PAID`; a payment exactly equal to the
    outstanding balance advances `UNPAID → PAID` or `PARTIALLY_PAID → PAID`, drives
    `balance_due_cents` to zero and stamps `paid_at` with the logical clock instant
    at which the balance first reached zero."
    PRD 3.6: "Every accepted payment recomputes the buyer's
    `outstanding_exposure_cents` and advances the order's `version` by one."
    PRD 3.9: "`gross_hammer_cents` is the sum of `hammer_price_cents` over that
    seller's orders whose `logistics_status` is not `ABANDONED`,
    `listed_retail_value_cents` is the sum of `declared_retail_value_cents` over that
    seller's lots whose `lot_status` is `LISTED`, `SOLD` or `RELIST_PENDING`, and
    `gross_recovery_rate` is the first divided by the second, rounded half up once to
    four decimal places, or exactly 0.0000 when the denominator is zero."

    Design: Corner/consistency_model/every_write_is_fully_visible_in_its_own_response_and_in_the_next_read
    """
    built = setup_open_fixed_price(
        lines=TWO_HUNDRED_UNIT_LINES,
        lot_overrides={"title": "Immediate visibility lot", "category_code": "TOYS"},
        clock="2026-08-06T01:00:00Z",
    )
    env = built["env"]
    listing = built["listing"]

    purchase = validate_success(
        api_client.place_bid(
            listing["id"],
            bid_payload(env["buyer"]["id"], 1_000_000),
            env["buyer_headers"],
        ),
        201,
    )
    assert purchase["bid_status"] == "WON"

    listed = validate_success(
        api_client.list_sale_orders(env["buyer_headers"], {"listing_id": listing["id"]})
    )
    assert len(listed) == 1
    order = listed[0]
    assert order["total_due_cents"] == 1_148_500

    receipt = pay_order(env, order, 500_000)
    assert receipt["amount_paid_cents"] == 500_000
    assert receipt["balance_due_cents"] == 648_500
    assert receipt["payment_status"] == "PARTIALLY_PAID"

    first_read = read_buyer(env)
    second_read = read_buyer(env)
    assert first_read["outstanding_exposure_cents"] == 648_500
    assert second_read["outstanding_exposure_cents"] == first_read["outstanding_exposure_cents"]

    seller = read_seller(env)
    assert seller["gross_hammer_cents"] == 1_000_000
    assert seller["listed_retail_value_cents"] == 2_000_000
    assert seller["gross_recovery_rate"] == 0.5

    assert read_listing(env, listing["id"])["listing_status"] == "CLOSED_SOLD"
    assert read_lot(env, built["lot"]["id"])["lot_status"] == "SOLD"
