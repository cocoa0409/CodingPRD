"""Counter price resolution and pinned document-totals ladder (PRD §3.4, §3.6)."""
from test_helpers import (
    ApiErrorId,
    create_draft_order,
    create_order_line_payload,
    create_order_payload,
    create_quote_payload,
    create_quoted,
    make_account,
    make_branch,
    make_product,
    make_stock,
    setup_branch_product_account,
    validate_error,
    validate_success,
)


def _gold_setup(sku="P1", product_overrides=None):
    """Branch + product + GOLD account (10% tier). Returns (branch, product, account)."""
    return setup_branch_product_account(sku=sku, product_overrides=product_overrides)


class TestCounterPriceResolution:
    def test_promo_price_wins_when_strictly_lower(self, api, counterrep_headers):
        """PRD §3.6: "When the product carries a `promo_price_cents`, the resolved
        price is the lower of the tier price and the promotional price — the line
        stamps `price_source` `PROMO` when the promotional price is strictly
        lower, otherwise `COUNTER_TIER`."

        GOLD tier price is 9000; promo 8500 is strictly lower, so the line
        resolves to 8500 with price_source PROMO.

        Design: Difficulty/combinatorial_formula/counter_price_tier_promo_override_floor
        """
        branch, promo, account = _gold_setup(
            sku="PPRO", product_overrides={"promo_price_cents": 8500, "cubes_per_unit": 1}
        )
        order, _ = create_draft_order(account["id"], branch["id"], [])
        line = validate_success(
            api.add_order_line(order["id"], create_order_line_payload(promo["id"], 1), counterrep_headers),
            201,
        )
        assert line["unit_price_cents"] == 8500, (
            f"min(tier 9000, promo 8500) must be 8500, got {line['unit_price_cents']}"
        )
        assert line["price_source"] == "PROMO"

    def test_tier_price_applies_without_promo(self, api, counterrep_headers):
        """PRD §3.6: "`SILVER`, `GOLD`, and `PLATINUM` earn 5, 10, and 15 percent
        off respectively; the tier price is the product's `list_price_cents`
        reduced by that percentage, rounded half up to a whole cent."
        PRD §3.6: "the line stamps `price_source` `PROMO` when the promotional
        price is strictly lower, otherwise `COUNTER_TIER`."

        GOLD list 10000 resolves to 9000 with price_source COUNTER_TIER.

        Design: Difficulty/combinatorial_formula/counter_price_tier_promo_override_floor
        """
        branch, plain, account = _gold_setup(sku="PT", product_overrides={
            "description": "Plain tee", "category": "FITTING", "cubes_per_unit": 1,
        })
        order, _ = create_draft_order(account["id"], branch["id"], [])
        line = validate_success(
            api.add_order_line(order["id"], create_order_line_payload(plain["id"], 1), counterrep_headers),
            201,
        )
        assert line["unit_price_cents"] == 9000, (
            f"GOLD tier price of list 10000 must be 9000, got {line['unit_price_cents']}"
        )
        assert line["price_source"] == "COUNTER_TIER"


class TestPriceFloorAndOverrides:
    def test_price_override_by_counterrep_rejected(self, api, counterrep_headers):
        """PRD §3.6: "A manual `price_override_cents` may instead be supplied,
        under two guards: the acting role must be `BranchManager` (anyone else
        is rejected with `ERR_OVERRIDE_REQUIRES_MANAGER`)".

        The override 5300 is at or above the floor (5250), so only the role
        guard can fire.

        Design: Corner/validations/price_override_by_counterrep_rejected
        """
        branch, product, account = _gold_setup()
        order, _ = create_draft_order(account["id"], branch["id"], [])
        res = api.add_order_line(
            order["id"],
            create_order_line_payload(product["id"], 1, price_override_cents=5300),
            counterrep_headers,
        )
        validate_error(res, ApiErrorId.ERR_OVERRIDE_REQUIRES_MANAGER)

    def test_price_override_below_floor_rejected(self, api, manager_headers):
        """PRD §3.6: "A manual `price_override_cents` may instead be supplied, under two guards: the acting role must be `BranchManager` (anyone else is rejected with `ERR_OVERRIDE_REQUIRES_MANAGER`), and the override must respect the same price floor as quotes — at least one hundred and five percent of the product's `cost_cents`, rounded up to a whole cent (a violation is `ERR_PRICE_FLOOR_VIOLATION`, and per §2.7 the floor rejection outranks the role rejection when both fail)."

        Floor for cost 5000 is ceil(5250.0) = 5250: 5200 is rejected, 5250 is
        accepted and stamped MANUAL_OVERRIDE.

        Design: Corner/validations/price_override_below_floor_rejected
        """
        branch, product, account = _gold_setup()
        order, _ = create_draft_order(account["id"], branch["id"], [])

        res = api.add_order_line(
            order["id"],
            create_order_line_payload(product["id"], 1, price_override_cents=5200),
            manager_headers,
        )
        validate_error(res, ApiErrorId.ERR_PRICE_FLOOR_VIOLATION)

        ok = api.add_order_line(
            order["id"],
            create_order_line_payload(product["id"], 1, price_override_cents=5250),
            manager_headers,
        )
        line = validate_success(ok, 201)
        assert line["unit_price_cents"] == 5250
        assert line["price_source"] == "MANUAL_OVERRIDE"

    def test_quote_line_below_floor_rejected(self, api, sales_headers):
        """PRD §3.4: "every line must respect the price floor: at least one
        hundred and five percent of the product's `cost_cents`, rounded up to a
        whole cent; a line below the floor rejects the creation with
        `ERR_PRICE_FLOOR_VIOLATION`."

        Design: Corner/validations/quote_line_below_floor_rejected
        """
        branch, product, account = _gold_setup()
        res = api.create_quote(
            create_quote_payload(
                account["id"], branch["id"],
                [{"product_id": product["id"], "qty": 1, "unit_price_cents": 5200}],
            ),
            sales_headers,
        )
        validate_error(res, ApiErrorId.ERR_PRICE_FLOOR_VIOLATION)


class TestDocumentTotals:
    def test_volume_tier_keys_on_pre_discount_subtotal(self, api, sales_headers):
        """PRD §3.6: "Second, `volume_discount_pct` is selected from the volume
        ladder against the pre-discount subtotal only: a subtotal of at least
        500,000 cents earns 2 percent, and a subtotal of at least 2,000,000 cents
        earns 5 percent, with the highest qualifying tier applying."
        PRD §3.6: "Re-tiering the volume discount against the post-discount value
        is forbidden; the tier keys on the first step alone."

        Subtotal 56 x 9000 = 504000 (>= 500000) selects 2% even though the
        post-discount value 493920 is below 500000.

        Design: Difficulty/combinatorial_formula/document_totals_pinned_evaluation_order
        """
        branch, product, account = _gold_setup()
        quote = create_quoted(
            account["id"], branch["id"],
            [{"product_id": product["id"], "qty": 56, "unit_price_cents": 9000}],
            job_name="JOB-T",
        )
        assert quote["subtotal_cents"] == 504000
        assert quote["volume_discount_pct"] == 2, (
            f"tier must key on the pre-discount 504000, got pct {quote['volume_discount_pct']}"
        )
        assert quote["discount_cents"] == 10080

    def test_freight_keys_on_post_discount_subtotal(self, api, sales_headers):
        """PRD §3.6: "Fifth, `freight_cents` is 0 when the post-discount subtotal
        is at least 50,000 cents, and a flat 2,500 cents otherwise. Sixth,
        `total_cents` is the post-discount subtotal plus freight."

        Post-discount 493920 >= 50000 ships free; total is 493920.

        Design: Difficulty/combinatorial_formula/document_totals_pinned_evaluation_order
        """
        branch, product, account = _gold_setup()
        quote = create_quoted(
            account["id"], branch["id"],
            [{"product_id": product["id"], "qty": 56, "unit_price_cents": 9000}],
            job_name="JOB-T",
        )
        assert quote["freight_cents"] == 0, (
            f"post-discount 493920 >= 50000 must ship free, got freight {quote['freight_cents']}"
        )
        assert quote["total_cents"] == 493920

    def test_freight_tier_boundary_49999_vs_50000(self, api, sales_headers):
        """PRD §3.6: "Fifth, `freight_cents` is 0 when the post-discount subtotal
        is at least 50,000 cents, and a flat 2,500 cents otherwise."

        A STANDARD account pays list: subtotal 49999 incurs 2500 freight while
        exactly 50000 ships free.

        Design: Corner/calculations/freight_tier_boundary_49999_vs_50000
        """
        branch = make_branch()
        pa = make_product(sku="PA", description="A", category="FITTING",
                          list_price_cents=49999, cost_cents=1000, cubes_per_unit=1)
        pb = make_product(sku="PB", description="B", category="FITTING",
                          list_price_cents=50000, cost_cents=1000, cubes_per_unit=1)
        account = make_account(company_name="Std Co", pricing_tier="STANDARD",
                               terms="COD", credit_limit_cents=10000000)
        make_stock(branch["id"], pa["id"], 1)
        make_stock(branch["id"], pb["id"], 1)

        order_a, _ = create_draft_order(account["id"], branch["id"], [(pa["id"], 1)])
        order_b, _ = create_draft_order(account["id"], branch["id"], [(pb["id"], 1)])

        a = validate_success(api.get_order(order_a["id"], sales_headers))
        b = validate_success(api.get_order(order_b["id"], sales_headers))
        assert a["freight_cents"] == 2500 and a["total_cents"] == 52499, (
            f"49999 post-discount must incur flat freight: {a['freight_cents']}/{a['total_cents']}"
        )
        assert b["freight_cents"] == 0 and b["total_cents"] == 50000, (
            f"50000 post-discount must ship free: {b['freight_cents']}/{b['total_cents']}"
        )

    def test_volume_tier_top_band_5pct(self, api, sales_headers):
        """PRD §3.6: "Second, `volume_discount_pct` is selected from the volume
        ladder against the pre-discount subtotal only: a subtotal of at least
        500,000 cents earns 2 percent, and a subtotal of at least 2,000,000 cents
        earns 5 percent, with the highest qualifying tier applying. Third,
        `discount_cents` is the subtotal multiplied by that percent and divided
        by 100, rounded half up to a whole cent".

        Subtotal 250 x 10000 = 2,500,000 selects the 5% band: discount 125000,
        total 2,375,000.

        Design: Corner/calculations/volume_tier_top_band_5pct
        """
        branch, product, account = _gold_setup()
        account = make_account(company_name="Big Co", pricing_tier="GOLD",
                               credit_limit_cents=100000000)
        quote = create_quoted(
            account["id"], branch["id"],
            [{"product_id": product["id"], "qty": 250, "unit_price_cents": 10000}],
            job_name="BIG",
        )
        assert quote["volume_discount_pct"] == 5
        assert quote["discount_cents"] == 125000
        assert quote["total_cents"] == 2375000

    def test_cut_item_line_extension_per_foot(self, api, counterrep_headers, sales_headers):
        """PRD §3.6: "`line_total_cents` is `qty_ordered` times `unit_price_cents`
        for ordinary items, and `qty_ordered` times `cut_length_ft` times
        `unit_price_cents` for cut items, since cut pricing is per foot."

        Cut product at 200/ft with GOLD 10% resolves to 180/ft; 2 cuts of 3 ft
        extend to 1080, and the order total is 1080 + 2500 freight = 3580.

        Design: Corner/calculations/cut_item_line_extension_per_foot
        """
        branch = make_branch()
        cut = make_product(sku="PC", is_cut_to_order=True, list_price_cents=200,
                           cost_cents=100, cubes_per_unit=1)
        account = make_account()
        make_stock(branch["id"], cut["id"], 20)
        order = validate_success(
            api.create_order(create_order_payload(account["id"], branch["id"]), counterrep_headers), 201
        )
        line = validate_success(
            api.add_order_line(
                order["id"], create_order_line_payload(cut["id"], 2, cut_length_ft=3),
                counterrep_headers,
            ),
            201,
        )
        assert line["unit_price_cents"] == 180, f"GOLD per-foot price must be 180, got {line['unit_price_cents']}"
        assert line["line_total_cents"] == 1080, (
            f"2 cuts x 3 ft x 180 must extend to 1080, got {line['line_total_cents']}"
        )
        order_after = validate_success(api.get_order(order["id"], sales_headers))
        assert order_after["total_cents"] == 3580, (
            f"order total must be 1080 + 2500 freight = 3580, got {order_after['total_cents']}"
        )
