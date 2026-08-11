"""Settlement money computations: dual QUOTE/FINAL valuation variants, tiered
recycling fees, the pinned rebate evaluation order, grade multipliers,
per-line commission rounding, and variant-dependent sanitization fees
(PRD §2.7, §3.6, §3.8)."""
from test_helpers import (
    create_quote_settlement,
    list_item,
    log_sanitization,
    new_active_policy,
    reconcile_manifest,
    scan_and_triage,
    sell_listing,
    setup_received_manifest,
    setup_triaged_item,
    triage_item,
    validate_success,
    verify_sanitization_record,
)


def _two_laptop_resale_manifest():
    """RECEIVED DROPOFF manifest (declared 2) with two non-data grade-A laptops
    triaged RESALE. Returns (account, manifest, [item1, item2])."""
    account, manifest = setup_received_manifest(declared_item_count=2)
    items = [
        scan_and_triage(manifest["id"], "RESALE", serial_number=f"SN-L{i}",
                        category="LAPTOP", weight_kg=2.0, declared_grade="A")
        for i in (1, 2)
    ]
    return account, manifest, items


class TestQuoteVsFinalDivergence:
    def _setup(self):
        account, manifest, items = _two_laptop_resale_manifest()
        quote = create_quote_settlement(manifest["id"])
        for item in items:
            listing = list_item(item["id"], asking_price_cents=60000, floor_price_cents=50000)
            sell_listing(listing["id"], 60000)
        reconcile_manifest(manifest["id"])
        return account, manifest, quote

    def test_quote_gross_uses_catalog_estimates(self, api):
        """PRD §3.8: "The quote variant counts every item whose `disposition` is `RESALE` or `REFURB`, regardless of where it stands in processing, and values it per line: an item already `SOLD` contributes its realized `final_value_cents`, while an unsold item contributes its catalog estimate — a base value for its `category` multiplied by the multiplier for its `declared_grade`, rounded half-up to whole cents. The base values are 40000 cents for a `LAPTOP`, 25000 for a `DESKTOP`, 120000 for a `SERVER`, 15000 for a `PHONE`, 18000 for a `TABLET`, 8000 for a `MONITOR`, 0 for a `BATTERY`, and 5000 for `OTHER`; grade `A` values at full base, `B` at seventy percent, `C` at forty percent, and `D` at ten percent."

        Design: Difficulty/dual_variant_calc/settlement_quote_vs_final_value_divergence
        """
        _account, _manifest, quote = self._setup()
        # Both laptops unsold at quote time: 2 x (40000 x 1.0) = 80000.
        assert quote["kind"] == "QUOTE"
        assert quote["status"] == "QUOTE_OPEN"
        assert quote["gross_buyback_cents"] == 80000
        assert quote["total_fees_cents"] == 0
        assert quote["volume_rebate_cents"] == 0
        assert quote["net_amount_cents"] == 80000

    def test_final_settlement_uses_realized_proceeds(self, api, platform_admin_headers):
        """PRD §3.8: "and recomputes all four totals under the final variant: only `COMPLETE` items count, sold items contribute their realized net `final_value_cents`, recycled and unsold items contribute zero, fees are computed on the final basis, and the rebate rule runs unchanged."
        PRD §3.8: "First gross, then fees, then the pre-rebate net defined as `gross_buyback_cents` minus `total_fees_cents`; the rebate tier is keyed on this pre-rebate figure and never on the post-rebate result. A pre-rebate net of at least 500000 cents earns the `GOLD` tier at five percent; at least 100000 cents earns `SILVER` at two percent — both boundaries inclusive — and anything below earns no rebate tier."

        Design: Difficulty/dual_variant_calc/settlement_quote_vs_final_value_divergence
        """
        _account, _manifest, quote = self._setup()
        settlement = validate_success(api.finalize_settlement(quote["id"],
                                                              platform_admin_headers))
        # FINAL: 2 x (60000 - round_half_up(60000 x 0.15)) = 2 x 51000 = 102000.
        assert settlement["kind"] == "FINAL"
        assert settlement["status"] == "FINALIZED"
        assert settlement["gross_buyback_cents"] == 102000
        assert settlement["total_fees_cents"] == 0
        # Pre-rebate net 102000 >= 100000 -> SILVER 2% -> 2040.
        assert settlement["volume_rebate_cents"] == 2040
        assert settlement["net_amount_cents"] == 104040
        # Identical items, different variants, different money.
        assert settlement["gross_buyback_cents"] != 80000


class TestRecyclingFeeComposition:
    def _setup_monitor_recycle(self):
        """RECEIVED DROPOFF manifest with one 5.0 kg hazmat, non-data MONITOR
        triaged RECYCLE. Returns (manifest, quote)."""
        account, manifest = setup_received_manifest(declared_item_count=1)
        scan_and_triage(manifest["id"], "RECYCLE", serial_number="SN-M1",
                        category="MONITOR", weight_kg=5.0, hazmat_flag=True,
                        declared_grade="A")
        quote = create_quote_settlement(manifest["id"])
        return manifest, quote

    def test_mid_tier_boundary_weight_plus_hazmat_fee(self, api):
        """PRD §3.8: "Each recycle-routed item incurs a recycling fee of three parts: a category base fee — 800 cents for a `LAPTOP`, 1000 for a `DESKTOP`, 2500 for a `SERVER`, 300 for a `PHONE`, 400 for a `TABLET`, 1200 for a `MONITOR`, 1500 for a `BATTERY`, and 900 for `OTHER` — plus a weight charge and a flat 2000-cent hazmat surcharge when `hazmat_flag` is set. The weight charge multiplies the item's whole `weight_kg` by a single per-kilogram rate chosen by the item's total weight: under 5.0 kg the rate is 120 cents per kilogram, from 5.0 kg up to and including 20.0 kg the rate is 90 cents per kilogram, and above 20.0 kg the rate is 60 cents per kilogram; the product is rounded half-up to whole cents."

        Design: Difficulty/combinatorial_formula/recycling_fee_weight_tier_and_hazmat_branches
        """
        _manifest, quote = self._setup_monitor_recycle()
        # 5.0 kg lands in MID (inclusive lower bound): 1200 + 5.0 x 90 + 2000.
        assert quote["total_fees_cents"] == 3650

    def test_recycle_only_manifest_negative_net_no_rebate(self, api):
        """PRD §3.8: "Recycle-routed items contribute zero to the buyback in every variant."
        PRD §3.8: "The `volume_rebate_cents` is the pre-rebate net multiplied by the tier rate and rounded half-up to whole cents, computed only when the pre-rebate net is positive; a zero or negative pre-rebate net yields a rebate of exactly zero. The settlement's `net_amount_cents` is then the pre-rebate net plus the rebate: a positive net means the platform pays the customer (a buyback), a negative net means the customer owes fees."

        Design: Difficulty/combinatorial_formula/recycling_fee_weight_tier_and_hazmat_branches
        """
        _manifest, quote = self._setup_monitor_recycle()
        assert quote["gross_buyback_cents"] == 0
        assert quote["volume_rebate_cents"] == 0
        assert quote["net_amount_cents"] == -3650


class TestVolumeRebatePinnedOrder:
    def _setup_six_laptop_sales(self):
        """PICKUP manifest with six grade-A laptops, each sold at 100000
        (STANDARD commission 15% -> 85000 net each), reconciled, quoted,
        finalized. Returns the finalized settlement dict."""
        account, manifest = setup_received_manifest(
            declared_item_count=6, mode="PICKUP", pickup_route="R-1",
            scheduled_start="2026-06-02T09:00:00Z",
            scheduled_end="2026-06-02T11:00:00Z",
        )
        for i in range(1, 7):
            item = scan_and_triage(manifest["id"], "RESALE", serial_number=f"SN-R{i}",
                                   category="LAPTOP", weight_kg=2.0, declared_grade="A")
            listing = list_item(item["id"], asking_price_cents=100000,
                                floor_price_cents=90000, channel="B2B_AUCTION")
            sell_listing(listing["id"], 100000)
        reconcile_manifest(manifest["id"])
        return create_quote_settlement(manifest["id"])

    def test_rebate_scenario_gross_and_fees(self, api):
        """PRD §3.8: "Finally, when the manifest's `mode` is `PICKUP`, a flat pickup fee of 15000 cents applies in both variants."
        PRD §3.6: "the item's `final_value_cents` is computed per line as the sale price minus the platform's commission, where the commission is the sale price multiplied by the account-tier rate and rounded half-up to whole cents: fifteen percent for `STANDARD` accounts, fifteen percent for `VOLUME`, and ten percent for `ENTERPRISE`."

        Design: Difficulty/combinatorial_formula/volume_rebate_pinned_evaluation_order
        """
        quote = self._setup_six_laptop_sales()
        # All six SOLD before the quote: realized values 6 x 85000 = 510000.
        assert quote["gross_buyback_cents"] == 510000
        assert quote["total_fees_cents"] == 15000

    def test_rebate_tier_keyed_on_pre_rebate_net(self, api, platform_admin_headers):
        """PRD §3.8: "First gross, then fees, then the pre-rebate net defined as `gross_buyback_cents` minus `total_fees_cents`; the rebate tier is keyed on this pre-rebate figure and never on the post-rebate result. A pre-rebate net of at least 500000 cents earns the `GOLD` tier at five percent; at least 100000 cents earns `SILVER` at two percent — both boundaries inclusive — and anything below earns no rebate tier. The `volume_rebate_cents` is the pre-rebate net multiplied by the tier rate and rounded half-up to whole cents, computed only when the pre-rebate net is positive; a zero or negative pre-rebate net yields a rebate of exactly zero. The settlement's `net_amount_cents` is then the pre-rebate net plus the rebate: a positive net means the platform pays the customer (a buyback), a negative net means the customer owes fees."

        Design: Difficulty/combinatorial_formula/volume_rebate_pinned_evaluation_order
        """
        quote = self._setup_six_laptop_sales()
        settlement = validate_success(api.finalize_settlement(quote["id"],
                                                              platform_admin_headers))
        assert settlement["gross_buyback_cents"] == 510000
        assert settlement["total_fees_cents"] == 15000
        # Pre-rebate net is 495000 -> SILVER 2% -> 9900. Keying on the
        # post-rebate 504900 would wrongly select GOLD (24750).
        assert settlement["volume_rebate_cents"] == 9900
        assert settlement["net_amount_cents"] == 504900


class TestGradeMultiplier:
    def test_quote_grade_b_uses_grade_multiplier(self, api):
        """PRD §3.8: "The quote variant counts every item whose `disposition` is `RESALE` or `REFURB`, regardless of where it stands in processing, and values it per line: an item already `SOLD` contributes its realized `final_value_cents`, while an unsold item contributes its catalog estimate — a base value for its `category` multiplied by the multiplier for its `declared_grade`, rounded half-up to whole cents. The base values are 40000 cents for a `LAPTOP`, 25000 for a `DESKTOP`, 120000 for a `SERVER`, 15000 for a `PHONE`, 18000 for a `TABLET`, 8000 for a `MONITOR`, 0 for a `BATTERY`, and 5000 for `OTHER`; grade `A` values at full base, `B` at seventy percent, `C` at forty percent, and `D` at ten percent."

        Design: Corner/calculations/quote_estimate_uses_grade_multiplier
        """
        account, manifest = setup_received_manifest(declared_item_count=1)
        scan_and_triage(manifest["id"], "RESALE", serial_number="SN-G1",
                        category="LAPTOP", weight_kg=2.0, declared_grade="B")
        quote = create_quote_settlement(manifest["id"])
        assert quote["gross_buyback_cents"] == 28000


class TestCommissionRoundingOrder:
    def test_commission_rounded_per_line_then_summed(self, api, platform_admin_headers):
        """PRD §2.7: "All monetary amounts are represented as integer cents; there are no fractional cents anywhere in the API. Whenever a monetary formula produces a fractional intermediate, it is rounded using the round-half-up method. Settlement computations follow a pinned round-then-sum order: every per-line amount is rounded half-up to whole cents first, and only then are the rounded lines summed into totals."
        PRD §3.6: "the item's `final_value_cents` is computed per line as the sale price minus the platform's commission, where the commission is the sale price multiplied by the account-tier rate and rounded half-up to whole cents: fifteen percent for `STANDARD` accounts, fifteen percent for `VOLUME`, and ten percent for `ENTERPRISE`."

        Design: Corner/calculations/commission_rounding_per_line_then_sum
        """
        account, manifest = setup_received_manifest(declared_item_count=2)
        for serial in ("SN-RC1", "SN-RC2"):
            item = scan_and_triage(manifest["id"], "RESALE", serial_number=serial,
                                   category="OTHER", weight_kg=0.5, declared_grade="D")
            listing = list_item(item["id"], asking_price_cents=30, floor_price_cents=1)
            sell_listing(listing["id"], 30)
        reconcile_manifest(manifest["id"])
        quote = create_quote_settlement(manifest["id"])
        settlement = validate_success(api.finalize_settlement(quote["id"],
                                                              platform_admin_headers))
        # Per line: commission round_half_up(30 x 0.15) = 5 -> proceeds 25;
        # two lines sum to 50 (sum-then-round would give 51).
        assert settlement["gross_buyback_cents"] == 50
        assert settlement["total_fees_cents"] == 0
        assert settlement["volume_rebate_cents"] == 0
        assert settlement["net_amount_cents"] == 50


class TestSanitizationFeeVariants:
    def test_quote_default_vs_final_verified_method(self, api, platform_admin_headers):
        """PRD §3.8: "Every data-bearing item additionally incurs one sanitization fee: the quote variant assumes the default `NIST_CLEAR` method at 700 cents, while the final variant uses the method of the item's latest `VERIFIED` sanitization record, at 500 cents for `CRYPTO_ERASE`, 700 for `NIST_CLEAR`, 1000 for `NIST_PURGE`, and 1500 for `PHYSICAL_DESTROY`."

        Design: Corner/calculations/sanitization_fee_quote_default_vs_final_method
        """
        new_active_policy()
        ctx = setup_triaged_item(disposition="REFURB", data_bearing=True, declared_grade="A",
                                 serial_number="SN-SF1")
        record = log_sanitization(ctx["item"]["id"], method="NIST_PURGE", outcome="PASS")
        verify_sanitization_record(record["id"], verdict="APPROVE")
        triage_item(ctx["item"]["id"], "RESALE")
        listing = list_item(ctx["item"]["id"], asking_price_cents=60000, floor_price_cents=50000)
        sell_listing(listing["id"], 60000)
        reconcile_manifest(ctx["manifest"]["id"])
        quote = create_quote_settlement(ctx["manifest"]["id"])
        # Quote assumes NIST_CLEAR at 700 even though NIST_PURGE was verified.
        assert quote["total_fees_cents"] == 700

        settlement = validate_success(api.finalize_settlement(quote["id"],
                                                              platform_admin_headers))
        # Final uses the verified NIST_PURGE method at 1000.
        assert settlement["total_fees_cents"] == 1000
        assert settlement["gross_buyback_cents"] == 51000
        assert settlement["net_amount_cents"] == 50000
