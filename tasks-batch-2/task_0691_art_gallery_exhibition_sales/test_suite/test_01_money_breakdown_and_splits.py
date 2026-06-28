"""Sale money breakdown (net / tax / buyer total) and the consignment split.

Covers the tax-on-net rounding order, the provisional-vs-final split divergence,
the out-of-state and resale-threshold exemptions, the per-artist split override,
and the discount default.
"""
from test_helpers import (
    validate_success, get_success_data,
    setup_gallery_artist_artwork, create_gallery, create_artist, create_artwork,
    setup_invoiced_sale, setup_paid_in_full_sale,
    TEST_USERS,
)
from test_helpers import factories as f

ADMIN = TEST_USERS["gallery_admin_headers"]
SALES = TEST_USERS["sales_associate_headers"]


class TestMoneyBreakdown:
    def test_tax_computed_on_net_then_shipping_added(self, api):
        """PRD §3.4: "When the sale is exempt, `tax_amount_cents` is 0; otherwise
        `tax_amount_cents` is the net amount multiplied by the gallery's
        `sales_tax_rate_bps`, divided by 10000, rounded half up — tax is computed
        on the post-discount net, never on the gross."
        PRD §3.4: "The `buyer_total_cents` is then `net_amount_cents` plus
        `tax_amount_cents` plus `shipping_cents`; shipping is added to what the
        buyer owes but is never itself taxed."

        Design: Difficulty/combinatorial_formula/tax_on_net_then_add_shipping_rounding_order
        """
        gallery, artist, artwork = setup_gallery_artist_artwork(
            gallery_overrides={"home_state_code": "CA", "sales_tax_rate_bps": 875,
                               "default_consignment_split_bps": 5000},
            artwork_overrides={"list_price_cents": 1_000_000,
                               "insured_value_cents": 1_000_000})
        resp = api.create_sale(f.create_sale_payload(
            gallery["id"], artwork["id"], buyer_state_code="CA",
            gross_amount_cents=1_000_000, discount_bps=1000, shipping_cents=5000), SALES)
        sale = validate_success(resp, 201)
        assert sale["net_amount_cents"] == 900000, \
            f"net should be gross*0.9 = 900000, got {sale['net_amount_cents']}"
        assert sale["tax_amount_cents"] == 78750, \
            f"tax should be 8.75% of net = 78750, got {sale['tax_amount_cents']}"
        assert sale["buyer_total_cents"] == 983750, \
            f"buyer_total should be net+tax+shipping = 983750, got {sale['buyer_total_cents']}"

    def test_net_is_gross_after_discount(self, api):
        """PRD §3.4: "The `net_amount_cents` is the gross amount reduced by the
        discount: take `gross_amount_cents`, multiply by the quantity (10000 minus
        `discount_bps`), divide by 10000, and round half up to whole cents — this
        net is the consignment-split base."

        Design: Difficulty/combinatorial_formula/tax_on_net_then_add_shipping_rounding_order
        """
        gallery, artist, artwork = setup_gallery_artist_artwork(
            gallery_overrides={"home_state_code": "CA", "sales_tax_rate_bps": 875},
            artwork_overrides={"list_price_cents": 1_000_000,
                               "insured_value_cents": 1_000_000})
        # In-state buyer so the sale is taxable and we observe net feeding tax.
        resp = api.create_sale(f.create_sale_payload(
            gallery["id"], artwork["id"], buyer_state_code="CA",
            gross_amount_cents=1_000_000, discount_bps=1000, shipping_cents=5000), SALES)
        sale = validate_success(resp, 201)
        assert sale["net_amount_cents"] == 900000
        # tax = round_half_up(net * 875 / 10000) = round(78750.0) = 78750
        assert sale["tax_amount_cents"] == 78750

    def test_tax_exempt_for_out_of_state_buyer(self, api):
        """PRD §3.4: "the sale is **tax-exempt** if the buyer ships to a state
        different from the gallery's `home_state_code`, OR if the gallery's
        `resale_exempt_threshold_cents` is greater than 0 and the
        `gross_amount_cents` is strictly greater than that threshold".

        Design: Corner/calculations/tax_exempt_out_of_state_buyer
        """
        gallery, artist, artwork = setup_gallery_artist_artwork(
            gallery_overrides={"home_state_code": "CA", "sales_tax_rate_bps": 875},
            artwork_overrides={"list_price_cents": 800_000,
                               "insured_value_cents": 800_000})
        resp = api.create_sale(f.create_sale_payload(
            gallery["id"], artwork["id"], buyer_state_code="NY",
            gross_amount_cents=800_000), SALES)
        sale = validate_success(resp, 201)
        assert sale["tax_amount_cents"] == 0, "out-of-state buyer must be tax-exempt"
        assert sale["buyer_total_cents"] == 800_000, \
            "buyer_total equals net when exempt and no shipping"

    def test_resale_threshold_boundary_at_threshold_taxed_above_exempt(self, api):
        """PRD §3.4: "if the gallery's `resale_exempt_threshold_cents` is greater
        than 0 and the `gross_amount_cents` is strictly greater than that
        threshold (a wholesale or resale-certificate line; a threshold of 0
        disables this second path)."

        Design: Corner/calculations/resale_threshold_boundary_at_threshold_taxed
        """
        gallery = create_gallery(home_state_code="CA", sales_tax_rate_bps=875,
                                 resale_exempt_threshold_cents=500_000,
                                 default_consignment_split_bps=5000)
        artist = create_artist(gallery["id"])
        aw_at = create_artwork(gallery["id"], artist["id"],
                               list_price_cents=500_000, insured_value_cents=500_000)
        aw_above = create_artwork(gallery["id"], artist["id"],
                                  list_price_cents=600_000, insured_value_cents=600_000)
        # gross == threshold: NOT strictly above, in-state buyer -> taxed.
        s_at = validate_success(api.create_sale(f.create_sale_payload(
            gallery["id"], aw_at["id"], buyer_state_code="CA",
            gross_amount_cents=500_000), SALES), 201)
        # gross > threshold: exempt.
        s_above = validate_success(api.create_sale(f.create_sale_payload(
            gallery["id"], aw_above["id"], buyer_state_code="CA",
            gross_amount_cents=600_000), SALES), 201)
        assert s_at["tax_amount_cents"] == 43750, \
            "gross == threshold is not strictly above, so it is taxed"
        assert s_above["tax_amount_cents"] == 0, \
            "gross strictly above threshold is exempt"

    def test_discount_defaults_to_zero(self, api):
        """PRD §3.4: "a `discount_bps` (0 to 10000 inclusive, defaulting to 0)".
        PRD §3.4: "The `net_amount_cents` is the gross amount reduced by the
        discount: take `gross_amount_cents`, multiply by the quantity (10000 minus
        `discount_bps`), divide by 10000, and round half up to whole cents".

        Design: Corner/entities/sale_discount_default_zero_applied
        """
        gallery, artist, artwork = setup_gallery_artist_artwork(
            gallery_overrides={"home_state_code": "CA", "sales_tax_rate_bps": 875},
            artwork_overrides={"list_price_cents": 250_000,
                               "insured_value_cents": 250_000})
        # Omit discount_bps entirely.
        resp = api.create_sale({
            "gallery_id": gallery["id"], "artwork_id": artwork["id"],
            "buyer_name": "Dd", "buyer_state_code": "CA",
            "gross_amount_cents": 250_000}, SALES)
        sale = validate_success(resp, 201)
        assert sale["discount_bps"] == 0, "discount_bps must default to 0"
        assert sale["net_amount_cents"] == 250_000, \
            "with no discount, net equals gross"


class TestConsignmentSplit:
    def test_provisional_split_ignores_discount_then_final_applies_it(self, api):
        """PRD §3.4: "The **provisional** variant runs at reservation: the split
        is applied to the net derived from the *undiscounted* gross — that is, the
        gross rounded half up as if no discount applied — multiplied by the
        effective split basis points and divided by 10000, rounded half up."
        PRD §3.4: "The **final** variant runs at settlement: the split is applied
        to the realized `net_amount_cents` (post-discount), multiplied by the
        effective split basis points, divided by 10000, rounded half up, and this
        final figure replaces `artist_share_cents`."

        Design: Difficulty/dual_variant_calc/consignment_split_provisional_vs_final_on_sale
        """
        gallery, artist, artwork = setup_gallery_artist_artwork(
            gallery_overrides={"home_state_code": "CA", "sales_tax_rate_bps": 875,
                               "default_consignment_split_bps": 5000},
            artwork_overrides={"list_price_cents": 1_000_000,
                               "insured_value_cents": 1_000_000})
        # gross 1000000, 10% discount, in-state CA buyer, shipping 5000.
        sale = validate_success(api.create_sale(f.create_sale_payload(
            gallery["id"], artwork["id"], buyer_state_code="CA",
            gross_amount_cents=1_000_000, discount_bps=1000, shipping_cents=5000),
            SALES), 201)
        # Provisional: 50% of undiscounted gross-net 1000000 = 500000.
        assert sale["artist_share_cents"] == 500000, \
            f"provisional share should be 500000, got {sale['artist_share_cents']}"
        # Walk to settle: invoice, pay buyer_total (983750), settle.
        invoiced = get_success_data(api.invoice_sale(sale["id"], SALES))
        paid = get_success_data(api.post_payment(
            sale["id"], f.payment_payload(invoiced["buyer_total_cents"],
                                          invoiced["version"]), SALES))
        settled = validate_success(api.settle_sale(sale["id"], SALES))
        # Final: 50% of post-discount net 900000 = 450000.
        assert settled["artist_share_cents"] == 450000, \
            f"final share should be 450000, got {settled['artist_share_cents']}"
        assert settled["gallery_share_cents"] == 450000, \
            "gallery share is net minus artist share"

    def test_only_final_split_accrues_to_artist_ledger(self, api):
        """PRD §2.10: "Money accrues to the artist only at settlement, never at
        reservation: the provisional split that a sale shows while reserved is
        informational and is not added to the ledger."
        PRD §3.5: "the artist's `ledger_accrued_cents` increases by the final
        `artist_share_cents` and `ledger_payable_cents` is recomputed."

        Design: Difficulty/dual_variant_calc/consignment_split_provisional_vs_final_on_sale
        """
        gallery, artist, artwork, settled = setup_paid_in_full_sale(
            gallery_overrides={"home_state_code": "CA", "sales_tax_rate_bps": 875,
                               "default_consignment_split_bps": 5000},
            artwork_overrides={"list_price_cents": 1_000_000,
                               "insured_value_cents": 1_000_000},
            sale_overrides={"buyer_state_code": "CA", "gross_amount_cents": 1_000_000,
                            "discount_bps": 1000, "shipping_cents": 5000})
        # Before settle, artist payable still 0 (provisional not accrued).
        before = get_success_data(api.get_artist(artist["id"], ADMIN))
        assert before["ledger_accrued_cents"] == 0, \
            "provisional split must not accrue before settlement"
        get_success_data(api.settle_sale(settled["id"], SALES))
        after = get_success_data(api.get_artist(artist["id"], ADMIN))
        assert after["ledger_accrued_cents"] == 450000, \
            "only the final split (450000) lands in the accrued ledger"

    def test_artist_split_override_beats_gallery_default(self, api):
        """PRD §3.4: "using an effective rate of the artist's `split_override_bps`
        when that is set, otherwise the gallery's `default_consignment_split_bps`."
        PRD §3.1: "When `split_override_bps` is present it overrides the gallery
        default for that artist".

        Design: Corner/calculations/artist_split_override_beats_gallery_default
        """
        gallery = create_gallery(home_state_code="CA", sales_tax_rate_bps=875,
                                 default_consignment_split_bps=5000)
        artist = create_artist(gallery["id"], split_override_bps=6000)
        artwork = create_artwork(gallery["id"], artist["id"],
                                 list_price_cents=400_000, insured_value_cents=400_000)
        sale = validate_success(api.create_sale(f.create_sale_payload(
            gallery["id"], artwork["id"], buyer_state_code="NY",
            gross_amount_cents=400_000), SALES), 201)
        invoiced = get_success_data(api.invoice_sale(sale["id"], SALES))
        get_success_data(api.post_payment(
            sale["id"], f.payment_payload(invoiced["buyer_total_cents"],
                                          invoiced["version"]), SALES))
        settled = validate_success(api.settle_sale(sale["id"], SALES))
        # 60% of net 400000 == 240000.
        assert settled["artist_share_cents"] == 240000, \
            "override 6000bps applies, not the gallery 5000bps default"
        artist_after = get_success_data(api.get_artist(artist["id"], ADMIN))
        assert artist_after["ledger_accrued_cents"] == 240000
