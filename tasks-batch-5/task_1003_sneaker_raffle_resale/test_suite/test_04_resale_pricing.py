"""Fee, payout, and purchase-limit rules on the resale side."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_sku, create_account, create_listing, create_bid, buy_listing, setup_fixed_order,
    setup_verified_order, make_seller_headers, make_buyer_headers,
)

ADMIN = TEST_USERS["admin_headers"]


# --------------------------------------------------------------------------- #
# transaction_fee — tiered rate + high-value band + clamp (Difficulty)
# --------------------------------------------------------------------------- #
def test_transaction_fee_standard_high_value_band(api):
    """PRD §3.7: "The base commission rate is chosen from the seller's
    `seller_level` at the moment of evaluation: 0.09 for `STANDARD`, 0.07 for
    `PRO`, and 0.05 for `ELITE`."
    PRD §3.7: "When the order's `sale_price_cents` is at least 50000 cents (that
    is, 500 dollars), the effective rate is the base rate reduced by 0.01;
    otherwise the effective rate equals the base rate."

    Design: Difficulty/combinatorial_formula/transaction_fee_tiered_band_clamp_mode_a
    """
    ctx = setup_fixed_order(api, ask_price_cents=60000)
    # STANDARD 0.09 - 0.01 band = 0.08; 60000*0.08 = 4800; within [500, 10000].
    assert ctx["order"]["transaction_fee_cents"] == 4800


def test_transaction_fee_clamped_up_to_floor(api):
    """PRD §3.7: "Multiply `sale_price_cents` by the effective rate and round half
    up to whole cents to get a raw fee, then clamp that raw fee to lie between a
    floor of 500 cents and a ceiling of 10000 cents — raise it to 500 if it falls
    below, lower it to 10000 if it rises above."

    Design: Difficulty/combinatorial_formula/transaction_fee_tiered_band_clamp_mode_a
    """
    ctx = setup_fixed_order(api, ask_price_cents=5000)
    # STANDARD 0.09; 5000*0.09 = 450 raw < 500 floor -> clamped to 500.
    assert ctx["order"]["transaction_fee_cents"] == 500


# --------------------------------------------------------------------------- #
# buyer_charge_breakdown — processing fee on pre-fee subtotal (Difficulty)
# --------------------------------------------------------------------------- #
def test_processing_fee_charged_on_pre_fee_subtotal(api):
    """PRD §3.7: "form the subtotal as `sale_price_cents` plus `shipping_fee_cents`,
    multiply that subtotal by 0.029, add a flat 30 cents, and round the result
    half up to whole cents."

    Design: Difficulty/combinatorial_formula/processing_fee_pre_fee_subtotal_mode_c
    """
    ctx = setup_fixed_order(api, ask_price_cents=30000)
    # (30000 + 1500) * 0.029 = 913.5, + 30 = 943.5 -> round half up = 944.
    assert ctx["order"]["payment_processing_fee_cents"] == 944


def test_buyer_total_is_exact_sum_of_integer_cents(api):
    """PRD §3.7: "The `buyer_total_cents` is then the exact integer sum of
    `sale_price_cents`, `shipping_fee_cents`, and `payment_processing_fee_cents`."

    Design: Difficulty/combinatorial_formula/processing_fee_pre_fee_subtotal_mode_c
    """
    ctx = setup_fixed_order(api, ask_price_cents=30000)
    # 30000 + 1500 + 944 = 32444.
    assert ctx["order"]["buyer_total_cents"] == 32444


# --------------------------------------------------------------------------- #
# seller_payout — provisional vs final with downgrade (Difficulty)
# --------------------------------------------------------------------------- #
def test_provisional_payout_forces_zero_downgrade_at_creation(api):
    """PRD §3.7: "At order creation the `provisional_payout_cents` is the
    `sale_price_cents` minus the provisional `transaction_fee_cents`, with no
    downgrade deduction because the item has not yet been inspected — the
    `downgrade_adjustment_cents` is forced to 0 at this stage."

    Design: Difficulty/dual_variant_calc/order_payout_provisional_vs_final_downgrade
    """
    ctx = setup_fixed_order(api, ask_price_cents=30000, listed_condition="DEADSTOCK")
    # STANDARD 0.09; 30000*0.09 = 2700; 30000 - 2700 = 27300; downgrade 0.
    assert ctx["order"]["downgrade_adjustment_cents"] == 0
    assert ctx["order"]["provisional_payout_cents"] == 27300


def test_final_payout_applies_downgrade_after_authenticated_downgrade(api):
    """PRD §3.7: "if the authenticated condition ranks strictly below the declared
    condition — that is, the authenticator downgraded the pair — the adjustment is
    0.15 times `sale_price_cents` rounded half up to whole cents; otherwise the
    adjustment is 0. The `final_payout_cents` is then `sale_price_cents` minus the
    final `transaction_fee_cents` minus the `downgrade_adjustment_cents`".

    Design: Difficulty/dual_variant_calc/order_payout_provisional_vs_final_downgrade
    """
    ctx = setup_verified_order(api, ask_price_cents=30000,
                               listed_condition="DEADSTOCK", auth_condition="USED")
    order = ctx["order"]
    # downgrade = round_half_up(0.15 * 30000) = 4500.
    assert order["downgrade_adjustment_cents"] == 4500
    # final = 30000 - 2700 - 4500 = 22800.
    assert order["final_payout_cents"] == 22800


# --------------------------------------------------------------------------- #
# Per-SKU 24h purchase limit boundary (Difficulty)
# --------------------------------------------------------------------------- #
def _three_fixed_listings_and_buyer(api):
    sku = create_sku(api)
    seller = create_account(api, full_name="Limit Seller")
    buyer = create_account(api, full_name="Limit Buyer")
    listings = [
        create_listing(api, sku["id"], seller["id"], ask_price_cents=5000, size=size)
        for size in ("8", "8.5", "9")
    ]
    return buyer, listings


def test_third_fixed_buy_same_sku_rejected(api):
    """PRD §3.5: "That limit caps a buyer at fewer than two completed fixed-price
    buys of the same SKU within the trailing 24-hour window measured against the
    logical clock; a buyer who already has two such buys in that window is
    rejected with `ERR_PURCHASE_LIMIT_REACHED`."

    Design: Difficulty/boundary_precision_check/buy_rolling_limit_third_buy_rejected
    """
    buyer, listings = _three_fixed_listings_and_buyer(api)
    buy_listing(api, listings[0]["id"], buyer["id"])   # count 0 -> ok
    buy_listing(api, listings[1]["id"], buyer["id"])   # count 1 -> ok
    resp = api.buy_listing(listings[2]["id"], make_buyer_headers(buyer["id"]))  # count 2 -> reject
    validate_error(resp, ApiErrorId.ERR_PURCHASE_LIMIT_REACHED.value)


def test_second_fixed_buy_same_sku_allowed_at_boundary(api):
    """PRD §3.5: "That limit caps a buyer at fewer than two completed fixed-price
    buys of the same SKU within the trailing 24-hour window measured against the
    logical clock; a buyer who already has two such buys in that window is
    rejected with `ERR_PURCHASE_LIMIT_REACHED`."

    Design: Difficulty/boundary_precision_check/buy_rolling_limit_third_buy_rejected
    """
    buyer, listings = _three_fixed_listings_and_buyer(api)
    r1 = api.buy_listing(listings[0]["id"], make_buyer_headers(buyer["id"]))  # count 0
    r2 = api.buy_listing(listings[1]["id"], make_buyer_headers(buyer["id"]))  # count 1 (< 2)
    validate_success(r1, expected_status=201)
    validate_success(r2, expected_status=201)


# --------------------------------------------------------------------------- #
# Below-ask match rejected (Corner)
# --------------------------------------------------------------------------- #
def test_bid_below_ask_same_sku_rejected(api):
    """PRD §3.5: "the bid's `amount_cents` must be at least the listing's
    `ask_price_cents`, failing which the match is rejected with
    `ERR_BID_BELOW_ASK`."

    Design: Corner/validations/bid_below_ask_same_sku_rejected
    """
    sku = create_sku(api)
    seller = create_account(api, full_name="BA Seller")
    buyer = create_account(api, full_name="BA Buyer")
    listing = create_listing(api, sku["id"], seller["id"], ask_price_cents=30000,
                             size="10", pricing_mode="BID_ASK")
    bid = create_bid(api, sku["id"], buyer["id"], size="10", amount_cents=10000)
    resp = api.match_listing(listing["id"], {"bid_id": bid["id"],
                                             "expected_listing_version": listing["version"]},
                             make_seller_headers(seller["id"]))
    validate_error(resp, ApiErrorId.ERR_BID_BELOW_ASK.value)
