"""Settlement cascade (sale -> artwork -> slot + artist ledger), the payout
approved-amount clamp, ledger conservation across payout reverse, and the
settled-sales report."""
from test_helpers import (
    validate_success, get_success_data,
    setup_paid_in_full_sale, setup_settled_sale, setup_artist_with_payable,
    setup_exhibition_with_placed_artwork, create_sale,
    create_payout, complete_payout,
    create_gallery, create_artist, create_artwork,
    assert_ledger_conservation,
    TEST_USERS,
)
from test_helpers import factories as f

ADMIN = TEST_USERS["gallery_admin_headers"]
SALES = TEST_USERS["sales_associate_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]


class TestSettleCascade:
    def test_settle_drives_artwork_sold_and_releases_slot(self, api):
        """PRD §3.5: "Settlement recomputes `artist_share_cents` with the final
        split variant, drives the artwork `RESERVED → SOLD`, releases any wall slot
        the work still held (setting that `PLACED` slot to `RELEASED` and
        recomputing the exhibition's slot counts), appends a sold provenance entry,
        and fires the ledger accrual".

        Design: Difficulty/transitive_cascade/settle_cascade_artwork_slot_ledger_depth3
        """
        gallery, artist, artwork, exhibition, wall_slot = \
            setup_exhibition_with_placed_artwork(wall_capacity=2)
        # Reserve the placed artwork, invoice, pay in full.
        sale = create_sale(gallery["id"], artwork["id"], buyer_state_code="NY",
                           gross_amount_cents=400_000, exhibition_id=exhibition["id"])
        invoiced = get_success_data(api.invoice_sale(sale["id"], SALES))
        get_success_data(api.post_payment(
            sale["id"], f.payment_payload(invoiced["buyer_total_cents"],
                                          invoiced["version"]), SALES))
        validate_success(api.settle_sale(sale["id"], SALES))
        aw_after = get_success_data(api.get_artwork(artwork["id"], ADMIN))
        assert aw_after["status"] == "SOLD", "hop 2: artwork RESERVED -> SOLD"
        slot_after = get_success_data(api.get_wall_slot(wall_slot["id"], ADMIN))
        assert slot_after["status"] == "RELEASED", "hop 3: held slot released"

    def test_settle_accrues_final_share_to_artist_ledger(self, api):
        """PRD §3.5: "the artist's `ledger_accrued_cents` increases by the final
        `artist_share_cents` and `ledger_payable_cents` is recomputed. This is the
        single point at which artist money becomes real."

        Design: Difficulty/transitive_cascade/settle_cascade_artwork_slot_ledger_depth3
        """
        gallery, artist, artwork, paid = setup_paid_in_full_sale(
            sale_overrides={"buyer_state_code": "NY", "gross_amount_cents": 400_000})
        before = get_success_data(api.get_artist(artist["id"], ADMIN))
        assert before["ledger_accrued_cents"] == 0
        validate_success(api.settle_sale(paid["id"], SALES))
        after = get_success_data(api.get_artist(artist["id"], ADMIN))
        # net 400000, default 50% split -> 200000 accrued.
        assert after["ledger_accrued_cents"] == 200000, \
            "hop 3: artist ledger accrues the final share"

    def test_settle_cascade_visible_in_same_request(self, api):
        """PRD §3.5: "the artist's `ledger_accrued_cents` increases by the final
        `artist_share_cents` and `ledger_payable_cents` is recomputed."
        PRD §2.10: "`ledger_payable_cents`, what the gallery still owes, which is
        the accrued amount minus the paid amount, floored at zero."

        Design: Corner/consistency_model/settle_cascade_visible_in_same_request
        """
        gallery, artist, artwork, paid = setup_paid_in_full_sale(
            sale_overrides={"buyer_state_code": "NY", "gross_amount_cents": 400_000})
        settled = validate_success(api.settle_sale(paid["id"], SALES))
        assert settled["settlement_status"] == "SETTLED"
        # Immediate follow-up read reflects the accrual atomically.
        artist_after = get_success_data(api.get_artist(artist["id"], ADMIN))
        assert artist_after["ledger_payable_cents"] == 200000, \
            "payable reflects accrual immediately after settle"
        assert artist_after["ledger_accrued_cents"] == 200000
        assert_ledger_conservation(artist_after)


class TestPayoutClamp:
    def test_approved_clamped_to_payable_when_requested_exceeds(self, api):
        """PRD §3.10: "its `approved_cents` — the amount actually swept — is set to
        the smaller of `requested_cents` and the artist's `ledger_payable_cents` at
        the moment of creation; the create response already carries this
        `approved_cents`."

        Design: Difficulty/dual_variant_calc/payout_approved_amount_clamp_vs_requested
        """
        gallery, artist, artwork, settled = setup_artist_with_payable(accrued_gross=400_000)
        # payable is 200000; request 300000.
        payable_before = get_success_data(api.get_artist(artist["id"], ADMIN))
        assert payable_before["ledger_payable_cents"] == 200000
        payout = validate_success(api.create_payout(
            f.create_payout_payload(artist["id"], 300_000), ADMIN), 201)
        assert payout["approved_cents"] == 200000, \
            "approved clamped to payable (200000), not requested (300000)"
        assert payout["requested_cents"] == 300000, \
            "requested is preserved as submitted"

    def test_approved_equals_requested_when_under_payable(self, api):
        """PRD §3.10: "its `approved_cents` — the amount actually swept — is set to
        the smaller of `requested_cents` and the artist's `ledger_payable_cents` at
        the moment of creation".

        Design: Difficulty/dual_variant_calc/payout_approved_amount_clamp_vs_requested
        """
        gallery, artist, artwork, settled = setup_artist_with_payable(accrued_gross=400_000)
        # payable 200000; request 150000 (< payable) -> approved == requested.
        payout = validate_success(api.create_payout(
            f.create_payout_payload(artist["id"], 150_000), ADMIN), 201)
        assert payout["approved_cents"] == 150000, \
            "when requested < payable, approved equals requested"
        assert payout["requested_cents"] == 150000


class TestPayoutReverseConservesLedger:
    def test_complete_then_reverse_restores_paid_and_payable(self, api):
        """PRD §3.10: "The compensating action is reversal: a `GalleryAdmin`
        reverses a `COMPLETED` payout, moving it `COMPLETED → REVERSED`, which
        decreases the artist's `ledger_paid_cents` by `approved_cents` and
        recomputes `ledger_payable_cents`, returning the paid figure to its
        pre-completion value."

        Design: Difficulty/compensating_invariant/payout_complete_then_reverse_conserves_ledger
        """
        gallery, artist, artwork, settled = setup_artist_with_payable(accrued_gross=400_000)
        payout = create_payout(artist["id"], 150_000)
        complete_payout(payout["id"])
        # After complete: paid 150000, payable 50000.
        mid = get_success_data(api.get_artist(artist["id"], ADMIN))
        assert mid["ledger_paid_cents"] == 150000
        validate_success(api.reverse_payout(payout["id"], ADMIN))
        after = get_success_data(api.get_artist(artist["id"], ADMIN))
        assert after["ledger_paid_cents"] == 0, "reverse returns paid to 0"
        assert after["ledger_payable_cents"] == 200000, "payable restored to 200000"

    def test_accrued_unchanged_and_conservation_holds_after_reverse(self, api):
        """PRD §2.10: "At every moment the accrued amount equals the paid amount
        plus the payable amount — a conservation invariant the system preserves
        through accruals, payout completions, and payout reversals alike."

        Design: Difficulty/compensating_invariant/payout_complete_then_reverse_conserves_ledger
        """
        gallery, artist, artwork, settled = setup_artist_with_payable(accrued_gross=400_000)
        payout = create_payout(artist["id"], 150_000)
        complete_payout(payout["id"])
        validate_success(api.reverse_payout(payout["id"], ADMIN))
        after = get_success_data(api.get_artist(artist["id"], ADMIN))
        assert after["ledger_accrued_cents"] == 200000, \
            "accrued is unchanged by complete/reverse"
        assert_ledger_conservation(after)


class TestSalesSummaryReport:
    def test_report_aggregates_settled_sales_only(self, api):
        """PRD §3.10: "The report aggregates over settled sales in the window and
        returns the count of settled sales as `settled_sale_count`, along with
        `gross_total_cents`, `net_total_cents`, `tax_total_cents`,
        `shipping_total_cents`, `artist_share_total_cents`, and
        `gallery_share_total_cents` — the running totals of each corresponding
        per-sale figure across those settled sales."

        Design: Corner/calculations/sales_summary_report_aggregates_settled_only
        """
        gallery = create_gallery(home_state_code="CA", sales_tax_rate_bps=875,
                                 default_consignment_split_bps=5000)
        artist = create_artist(gallery["id"])
        aw1 = create_artwork(gallery["id"], artist["id"],
                             list_price_cents=400_000, insured_value_cents=400_000)
        aw2 = create_artwork(gallery["id"], artist["id"],
                             list_price_cents=100_000, insured_value_cents=100_000)
        # Settle a 400000 (NY, tax-exempt) sale.
        s1 = validate_success(api.create_sale(f.create_sale_payload(
            gallery["id"], aw1["id"], buyer_state_code="NY",
            gross_amount_cents=400_000), SALES), 201)
        inv1 = get_success_data(api.invoice_sale(s1["id"], SALES))
        get_success_data(api.post_payment(
            s1["id"], f.payment_payload(inv1["buyer_total_cents"], inv1["version"]), SALES))
        get_success_data(api.settle_sale(s1["id"], SALES))
        # A RESERVED sale that must be excluded.
        create_sale_resp = api.create_sale(f.create_sale_payload(
            gallery["id"], aw2["id"], buyer_state_code="NY",
            gross_amount_cents=100_000), SALES)
        validate_success(create_sale_resp, 201)
        report = validate_success(api.sales_summary_report(ADMIN))
        assert report["settled_sale_count"] == 1, "only SETTLED sales counted"
        assert report["net_total_cents"] == 400000
        assert report["artist_share_total_cents"] == 200000
