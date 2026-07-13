"""The pricing engine: provisional vs final passes, bundles, gifts and samples."""

from test_helpers import (
    add_line_payload,
    line,
    new_customer,
    new_gwp_promotion,
    new_lot,
    new_product,
    new_sample_promotion,
    new_store,
    new_variant,
    new_bundle_promotion,
    read_lines,
    read_lines_by_promotion,
    read_lot,
    setup_draft_order,
    validate_success,
)


def _gwp_world(*, sale_units_in_stock, gift_units_in_stock=10, threshold_cents=7500):
    """Store + a 2500-cent sale variant + a zero-priced gift variant + a GWP promotion.

    Returns (store, v_sale, sale_lot, v_gift, gift_lot, promo, customer)."""
    store = new_store()
    product = new_product(name="Velvet Lip", base_price_cents=2500)
    v_sale = new_variant(
        product["id"], shade_name="Warm Sand", shade_code="WS-01", finish="MATTE",
        undertone="WARM", depth_index=6, price_cents=2500,
    )
    gift_product = new_product(
        name="Mini Serum", category="SKINCARE", base_price_cents=0
    )
    v_gift = new_variant(
        gift_product["id"], shade_name="Universal", shade_code="UNI-00", finish="DEWY",
        undertone="NEUTRAL", depth_index=6, price_cents=0,
    )
    sale_lot = new_lot(store["id"], v_sale["id"], units_received=sale_units_in_stock)
    gift_lot = new_lot(store["id"], v_gift["id"], units_received=gift_units_in_stock)
    promo = new_gwp_promotion(v_gift["id"], threshold_cents, name="GWP 75", priority=10)
    customer = new_customer()  # INSIDER: zero tier discount, so subtotal == discounted
    return store, v_sale, sale_lot, v_gift, gift_lot, promo, customer


def test_provisional_quote_prices_the_requested_quantities(api, associate_headers):
    """PRD §3.5: "On the draft passes the value is `PROVISIONAL`: quantities are taken
    exactly as requested, stock is not consulted at all, `gwp_eligible` is advisory
    only, and **no** gift or sample line rows are created."
    PRD §3.5: "`gwp_eligible` is true exactly when such a promotion was found, and
    false when none was."

    Only 2 units are on the shelf but 3 are requested; the provisional pass ignores
    stock entirely and quotes 3 x 2500 = 7500, clearing the 7500 gift threshold.

    Design: Difficulty/dual_variant_calc/order_pricing_provisional_vs_final_diverge_on_short_pick
    """
    store, v_sale, sale_lot, _, _, _, customer = _gwp_world(sale_units_in_stock=2)

    order = validate_success(
        api.create_order(
            {
                "customer_id": customer["id"], "store_id": store["id"],
                "channel": "SHIP_FROM_STORE", "allow_partial": True,
                "lines": [line(v_sale["id"], 3)],
            },
            associate_headers,
        ),
        201,
    )

    assert order["subtotal_cents"] == 7500, "the provisional pass prices 3 requested units"
    assert order["gwp_eligible"] is True, "7500 >= the 7500 threshold"
    assert order["pricing_variant"] == "PROVISIONAL"

    assert len(read_lines(order["id"])) == 1, "no gift line rows are created on a draft"
    lot = read_lot(sale_lot["id"])
    assert lot["on_hand_units"] == 2 and lot["reserved_units"] == 0, (
        "stock is not consulted at all on the draft pass"
    )


def test_final_pass_after_clipping_reprices_and_drops_the_gift(api, associate_headers):
    """PRD §3.6: "Because clipping can shrink the basket, the `FINAL` pass may see
    strictly less than the `PROVISIONAL` pass did, and `discounted_subtotal_cents` can
    drop below a gift threshold the provisional quote had cleared — in which case no
    gift line is created at all, from an identical request payload. This is intended."
    PRD §3.6: "with `allow_partial` true, each sale line's `quantity` is instead
    clipped down to the units that can actually be drawn, and the reservation proceeds
    on the smaller basket."

    Design: Difficulty/dual_variant_calc/order_pricing_provisional_vs_final_diverge_on_short_pick
    """
    store, v_sale, sale_lot, _, _, promo, customer = _gwp_world(sale_units_in_stock=2)

    draft = validate_success(
        api.create_order(
            {
                "customer_id": customer["id"], "store_id": store["id"],
                "channel": "SHIP_FROM_STORE", "allow_partial": True,
                "lines": [line(v_sale["id"], 3)],
            },
            associate_headers,
        ),
        201,
    )
    assert draft["subtotal_cents"] == 7500 and draft["gwp_eligible"] is True

    reserved = validate_success(api.reserve_order(draft["id"], associate_headers))

    assert reserved["pricing_variant"] == "FINAL"
    assert reserved["subtotal_cents"] == 5000, "clipped to the 2 drawable units"
    assert reserved["gwp_eligible"] is False, "5000 no longer clears the 7500 threshold"
    assert reserved["total_due_cents"] == 5000

    assert len(read_lines(reserved["id"])) == 1, "no GWP line was materialised"
    assert read_lines_by_promotion(promo["id"]) == []

    lot = read_lot(sale_lot["id"])
    assert lot["reserved_units"] == 2 and lot["on_hand_units"] == 0


def test_bundle_discount_is_rounded_per_line_then_summed(api, associate_headers):
    """PRD §3.5: "For each sale line whose `variant_id` is one of the winning bundle's
    `bundle_variant_ids`, `line_discount_cents` is that line's `line_gross_cents`
    multiplied by the winning `bundle_discount_pct` and **rounded half up on that line,
    on its own**; for every other line it is 0."
    PRD §3.5: "The per-line rounding matters: taking the percentage against the summed
    gross of the bundle members and rounding the result once produces a different cent
    figure, and that figure is wrong."

    Three 350-cent lines at 15%: round_half_up(52.5) = 53 per line, so subtotal is
    3 x 297 = 891. Rounding the summed 1050 x 0.15 = 157.5 once gives 158 and a
    subtotal of 892 — the wrong answer.

    Design: Difficulty/combinatorial_formula/bundle_discount_rounded_per_line_then_summed_not_summed_then_rounded
    """
    store = new_store(name="SEP-NY", region_code="NY")
    product = new_product(name="Mini Trio", base_price_cents=350)
    v_a = new_variant(product["id"], shade_name="Trio A", shade_code="TA",
                      finish="MATTE", undertone="WARM", depth_index=4, price_cents=350)
    v_b = new_variant(product["id"], shade_name="Trio B", shade_code="TB",
                      finish="SATIN", undertone="COOL", depth_index=5, price_cents=350)
    v_c = new_variant(product["id"], shade_name="Trio C", shade_code="TC",
                      finish="DEWY", undertone="NEUTRAL", depth_index=6, price_cents=350)
    for v in (v_a, v_b, v_c):
        new_lot(store["id"], v["id"], units_received=5)
    new_bundle_promotion(
        [v_a["id"], v_b["id"], v_c["id"]], 0.15, name="Trio Bundle 15", priority=5
    )
    customer = new_customer()  # INSIDER: nothing else perturbs the cents

    order = validate_success(
        api.create_order(
            {
                "customer_id": customer["id"], "store_id": store["id"],
                "channel": "SHIP_FROM_STORE",
                "lines": [line(v_a["id"], 1), line(v_b["id"], 1), line(v_c["id"], 1)],
            },
            associate_headers,
        ),
        201,
    )

    assert order["subtotal_cents"] == 891, (
        f"per-line rounding gives 891; got {order['subtotal_cents']} "
        "(892 means the discount was rounded once against the summed gross)"
    )
    assert order["subtotal_cents"] != 892
    assert order["tier_discount_cents"] == 0, "an INSIDER earns no tier discount"
    assert order["total_due_cents"] == 891


def test_every_bundle_member_line_carries_its_own_rounded_discount(
    api, associate_headers
):
    """PRD §3.5: "For each sale line whose `variant_id` is one of the winning bundle's
    `bundle_variant_ids`, `line_discount_cents` is that line's `line_gross_cents`
    multiplied by the winning `bundle_discount_pct` and **rounded half up on that line,
    on its own**; for every other line it is 0. `line_net_cents` is then
    `line_gross_cents` less `line_discount_cents`."

    Design: Difficulty/combinatorial_formula/bundle_discount_rounded_per_line_then_summed_not_summed_then_rounded
    """
    store = new_store(name="SEP-NY", region_code="NY")
    product = new_product(name="Mini Trio", base_price_cents=350)
    v_a = new_variant(product["id"], shade_name="Trio A", shade_code="TA",
                      finish="MATTE", undertone="WARM", depth_index=4, price_cents=350)
    v_b = new_variant(product["id"], shade_name="Trio B", shade_code="TB",
                      finish="SATIN", undertone="COOL", depth_index=5, price_cents=350)
    v_c = new_variant(product["id"], shade_name="Trio C", shade_code="TC",
                      finish="DEWY", undertone="NEUTRAL", depth_index=6, price_cents=350)
    for v in (v_a, v_b, v_c):
        new_lot(store["id"], v["id"], units_received=5)
    new_bundle_promotion(
        [v_a["id"], v_b["id"], v_c["id"]], 0.15, name="Trio Bundle 15", priority=5
    )
    customer = new_customer()

    order = validate_success(
        api.create_order(
            {
                "customer_id": customer["id"], "store_id": store["id"],
                "channel": "SHIP_FROM_STORE",
                "lines": [line(v_a["id"], 1), line(v_b["id"], 1), line(v_c["id"], 1)],
            },
            associate_headers,
        ),
        201,
    )

    lines = read_lines(order["id"])
    assert len(lines) == 3
    for ln in lines:
        assert ln["line_gross_cents"] == 350
        assert ln["line_discount_cents"] == 53, (
            "round_half_up(350 * 0.15) == round_half_up(52.5) == 53 on each line"
        )
        assert ln["line_net_cents"] == 297, "350 less its own 53-cent discount"


def test_gwp_line_materialises_at_exactly_the_threshold(api, associate_headers):
    """PRD §3.6: "A `GWP` line — `line_type` of `GWP`, `unit_price_cents` of 0,
    `promotion_id` pointing at the winning promotion, `quantity` equal to that
    promotion's `gift_quantity` — is created only when `discounted_subtotal_cents` is
    at least the selected gift promotion's `threshold_cents` **and** the gifted variant
    has drawable stock at this store; if either condition fails, no gift line appears."
    PRD §3.5: "Among `ACTIVE` `GWP` promotions, those whose `threshold_cents` is less
    than or equal to `discounted_subtotal_cents` qualify"

    Design: Difficulty/boundary_precision_check/gwp_threshold_fires_at_exactly_equal_discounted_subtotal
    """
    store, v_sale, _, v_gift, _, promo, customer = _gwp_world(sale_units_in_stock=10)

    draft = validate_success(
        api.create_order(
            {
                "customer_id": customer["id"], "store_id": store["id"],
                "channel": "SHIP_FROM_STORE", "lines": [line(v_sale["id"], 3)],
            },
            associate_headers,
        ),
        201,
    )
    reserved = validate_success(api.reserve_order(draft["id"], associate_headers))

    assert reserved["discounted_subtotal_cents"] == 7500, "exactly equal to the threshold"
    assert reserved["gwp_eligible"] is True, "the comparison is at least, not more than"
    assert reserved["total_due_cents"] == 7500, "the gift adds nothing to the price"

    assert len(read_lines(reserved["id"])) == 2, "the sale line plus the gift line"
    gift_lines = read_lines_by_promotion(promo["id"])
    assert len(gift_lines) == 1
    assert gift_lines[0]["line_type"] == "GWP"
    assert gift_lines[0]["unit_price_cents"] == 0
    assert gift_lines[0]["quantity"] == 1
    assert gift_lines[0]["variant_id"] == v_gift["id"]


def test_gwp_line_is_not_materialised_one_cent_below_the_threshold(
    api, associate_headers
):
    """PRD §3.5: "Among `ACTIVE` `GWP` promotions, those whose `threshold_cents` is
    less than or equal to `discounted_subtotal_cents` qualify; they are ranked by
    `threshold_cents` from largest to smallest, ties broken by `priority` smallest
    first and then by `created_at` oldest first, and the top one is selected.
    `gwp_eligible` is true exactly when such a promotion was found, and false when
    none was."

    A discounted subtotal of 7499 — one cent under the 7500 threshold — must not
    qualify.

    Design: Difficulty/boundary_precision_check/gwp_threshold_fires_at_exactly_equal_discounted_subtotal
    """
    store = new_store()
    product = new_product(name="Velvet Lip", base_price_cents=7499)
    v_sale = new_variant(
        product["id"], shade_name="Warm Sand", shade_code="WS-01", finish="MATTE",
        undertone="WARM", depth_index=6, price_cents=7499,
    )
    gift_product = new_product(name="Mini Serum", category="SKINCARE", base_price_cents=0)
    v_gift = new_variant(
        gift_product["id"], shade_name="Universal", shade_code="UNI-00", finish="DEWY",
        undertone="NEUTRAL", depth_index=6, price_cents=0,
    )
    new_lot(store["id"], v_sale["id"], units_received=10)
    new_lot(store["id"], v_gift["id"], units_received=10)
    promo = new_gwp_promotion(v_gift["id"], 7500, name="GWP 75", priority=10)
    customer = new_customer()

    draft = validate_success(
        api.create_order(
            {
                "customer_id": customer["id"], "store_id": store["id"],
                "channel": "SHIP_FROM_STORE", "lines": [line(v_sale["id"], 1)],
            },
            associate_headers,
        ),
        201,
    )
    reserved = validate_success(api.reserve_order(draft["id"], associate_headers))

    assert reserved["discounted_subtotal_cents"] == 7499, "one cent below the threshold"
    assert reserved["gwp_eligible"] is False
    assert read_lines_by_promotion(promo["id"]) == [], "no gift line at 7499"
    assert len(read_lines(reserved["id"])) == 1, "the sale line stands alone"


def test_adding_a_line_reruns_the_provisional_quote(api, associate_headers):
    """PRD §3.5: "Every touch of the basket — creating the order, and every line added
    afterwards — reprices the whole order and hands back a fresh quote."
    PRD §2.8: "The reason is that every line addition re-runs the pricing engine and
    supersedes the quote the client was looking at: bundle eligibility, gift
    eligibility and every total can shift."
    PRD §2.5: "...and `version`, an integer that starts at 1 on creation and increments
    by one on every mutation of that record."

    Design: Corner/calculations/order_pricing_provisional_recomputes_on_line_add
    """
    ctx = setup_draft_order(quantity=1)
    order, variant = ctx["order"], ctx["variant"]
    assert order["subtotal_cents"] == 2500

    updated = validate_success(
        api.add_order_line(
            order["id"],
            add_line_payload(variant["id"], 2, order["version"]),
            associate_headers,
        )
    )

    assert updated["subtotal_cents"] == 7500, "2500 + 2 x 2500"
    assert updated["pricing_variant"] == "PROVISIONAL", "the draft pass is still provisional"
    assert updated["version"] == order["version"] + 1
    assert len(read_lines(order["id"])) == 2


def test_sample_line_is_free_and_draws_no_stock(api, associate_headers):
    """PRD §3.6: "Sample lines are materialised for every eligible `SAMPLE` promotion —
    that is, every `ACTIVE` `SAMPLE` promotion whose `threshold_cents` is at most
    `discounted_subtotal_cents` — with `line_type` of `SAMPLE`, a zero
    `unit_price_cents` and the promotion's `gift_quantity`; sample lines never touch an
    inventory lot at all, so no stock is drawn for them and none is ever returned."
    PRD §3.5: "`subtotal_cents` is the sum of `line_net_cents` across the **sale** lines
    only. Gift and sample lines contribute nothing, because their price is zero."

    Design: Corner/calculations/sample_promotion_line_does_not_consume_inventory
    """
    store = new_store()
    product = new_product(base_price_cents=2500)
    v_sale = new_variant(product["id"], price_cents=2500)
    sample_product = new_product(name="Sachet", category="SKINCARE", base_price_cents=0)
    v_sample = new_variant(
        sample_product["id"], shade_name="Sachet", shade_code="SA-01", finish="DEWY",
        undertone="NEUTRAL", depth_index=6, price_cents=0,
    )
    new_lot(store["id"], v_sale["id"], units_received=10)
    sample_lot = new_lot(store["id"], v_sample["id"], units_received=4)
    promo = new_sample_promotion(v_sample["id"], 5000, name="Sample 50", priority=20)
    customer = new_customer()

    draft = validate_success(
        api.create_order(
            {
                "customer_id": customer["id"], "store_id": store["id"],
                "channel": "SHIP_FROM_STORE", "lines": [line(v_sale["id"], 2)],
            },
            associate_headers,
        ),
        201,
    )
    reserved = validate_success(api.reserve_order(draft["id"], associate_headers))

    assert reserved["subtotal_cents"] == 5000, "the sample line contributes nothing"
    assert reserved["total_due_cents"] == 5000

    sample_lines = read_lines_by_promotion(promo["id"])
    assert len(sample_lines) == 1
    assert sample_lines[0]["line_type"] == "SAMPLE"
    assert sample_lines[0]["unit_price_cents"] == 0
    assert sample_lines[0]["line_net_cents"] == 0

    lot = read_lot(sample_lot["id"])
    assert lot["on_hand_units"] == 4 and lot["reserved_units"] == 0, (
        "sample lines never touch an inventory lot"
    )


def test_gwp_line_skipped_when_the_gift_variant_has_no_stock(api, associate_headers):
    """PRD §3.6: "A `GWP` line — `line_type` of `GWP`, `unit_price_cents` of 0,
    `promotion_id` pointing at the winning promotion, `quantity` equal to that
    promotion's `gift_quantity` — is created only when `discounted_subtotal_cents` is
    at least the selected gift promotion's `threshold_cents` **and** the gifted variant
    has drawable stock at this store; if either condition fails, no gift line appears."

    The threshold is met but the gift lot is empty: the reservation still succeeds and
    the basket still costs 7500 — only the gift line is absent.

    Design: Corner/cross_cutting_layers/gwp_line_silently_skipped_when_the_gift_variant_is_out_of_stock
    """
    store, v_sale, _, _, gift_lot, promo, customer = _gwp_world(
        sale_units_in_stock=10, gift_units_in_stock=0
    )

    draft = validate_success(
        api.create_order(
            {
                "customer_id": customer["id"], "store_id": store["id"],
                "channel": "SHIP_FROM_STORE", "lines": [line(v_sale["id"], 3)],
            },
            associate_headers,
        ),
        201,
    )
    reserved = validate_success(api.reserve_order(draft["id"], associate_headers))

    assert reserved["fulfillment_status"] == "RESERVED", (
        "a missing gift must not fail the reservation"
    )
    assert reserved["total_due_cents"] == 7500

    assert read_lines_by_promotion(promo["id"]) == [], "no gift line appears"
    assert len(read_lines(reserved["id"])) == 1

    lot = read_lot(gift_lot["id"])
    assert lot["on_hand_units"] == 0 and lot["reserved_units"] == 0
