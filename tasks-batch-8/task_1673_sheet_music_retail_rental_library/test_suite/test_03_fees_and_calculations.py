"""Fee arithmetic: provisional vs final variants, tiers, rounding discipline."""
from test_helpers import (
    advance_clock,
    check_in_order,
    confirm_order,
    create_account,
    create_order,
    create_publisher,
    create_rental_set,
    create_work,
    dispatch_order,
    fetch_order,
    get_success_data,
    reserve_order,
    run_sweep,
    setup_order_on_loan,
    setup_shipped_perusal,
    validate_success,
)

from test_helpers import BILLING, CLERK


class TestProvisionalVsFinalFee:
    def test_provisional_fee_stamped_at_reserve_final_null_until_return(self, api):
        """PRD §3.5: "`estimated_fee_cents` is first stamped at reservation, and
        `final_fee_cents` remains null until the order is returned."
        PRD §3.5: "The gross fee is that tier rate multiplied by `loan_periods`
        and by `copies_requested`."

        Design: Difficulty/dual_variant_calc/rental_fee_provisional_vs_final_on_late_return
        """
        ws = setup_order_on_loan(
            order_copies=5, publisher_name="Pub One", work_title="Suite No.1",
            catalog_number="P1-001", base_rate=10000,
            license_format="PRINT_AND_DIGITAL", set_code="SET-001",
            account_overrides={"account_name": "Riverside HS",
                               "credit_tier": "STANDARD", "credit_limit_cents": 0},
        )
        order = fetch_order(ws["order"]["id"])
        # 5 copies x 10000 cents x 1 period; no volume or publisher discount.
        assert order["estimated_fee_cents"] == 50000
        assert order["final_fee_cents"] is None, (
            "the final fee must stay null while the order is still out on loan"
        )

    def test_final_fee_applies_late_tiers_on_late_return(self, api):
        """PRD §3.6: "A daily base is computed exactly once: the final base divided
        by the product of `loan_periods`, `copies_requested`, and 30, rounded
        half-up. The late days then split chronologically into tiers — the first
        seven late days form the first tier, the next twenty-three the second, and
        any remainder from day thirty-one onward the third — and each tier carries
        a per-copy-per-day rate derived from the rounded daily base and itself
        rounded half-up: ten percent of the daily base in the first tier,
        twenty-five percent in the second, and fifty percent in the third."
        PRD §3.6: "`final_fee_cents` is the base plus this surcharge."

        Design: Difficulty/dual_variant_calc/rental_fee_provisional_vs_final_on_late_return
        """
        ws = setup_order_on_loan(
            order_copies=5, publisher_name="Pub One", work_title="Suite No.1",
            catalog_number="P1-001", base_rate=10000,
            license_format="PRINT_AND_DIGITAL", set_code="SET-001",
            account_overrides={"account_name": "Riverside HS",
                               "credit_tier": "STANDARD", "credit_limit_cents": 0},
        )
        advance_clock("2026-09-14T00:00:00Z")
        run_sweep()

        returned = check_in_order(ws["order"]["id"], "A,A,A,A,A")
        # 10 late days: daily_base rhu(50000/(1*5*30)) = 333; tier1 7d x 33 x 5
        # = 1155; tier2 3d x rhu(333*0.25)=83 x 5 = 1245; surcharge 2400.
        assert returned["final_fee_cents"] == 52400
        order = fetch_order(ws["order"]["id"])
        assert order["estimated_fee_cents"] == 50000, (
            "the provisional variant must not be rewritten by the final fee"
        )
        assert order["final_fee_cents"] - order["estimated_fee_cents"] == 2400


class TestVolumeDiscountTiers:
    def _setup_two_sets(self):
        publisher = create_publisher("Pub Three")
        work = create_work(publisher["id"], title="Band Book", catalog_number="P3-001",
                           base_rental_rate_cents=10000, sale_price_cents=1500)
        set_a = create_rental_set(work["id"], set_code="SET-201", copy_count=30,
                                  replacement_value_cents=300000)
        set_b = create_rental_set(work["id"], set_code="SET-202", copy_count=30,
                                  replacement_value_cents=300000)
        account = create_account("Metro Schools", credit_tier="STANDARD",
                                 credit_limit_cents=0)
        advance_clock()
        return account, set_a, set_b

    def test_volume_tier_24_copies_ten_percent(self, api):
        """PRD §3.5: "A volume discount keyed to `copies_requested` then applies:
        no discount for fewer than ten copies, ten percent for ten through
        twenty-four copies, and twenty percent for twenty-five copies or more."

        Design: Difficulty/combinatorial_formula/rental_fee_tiered_volume_discount_inversion
        """
        account, set_a, _set_b = self._setup_two_sets()
        order = create_order(account["id"], set_a["id"], copies=24)
        reserved = reserve_order(order["id"])
        # 10000 x 1 period x 24 copies x (1 - 0.10) = 216000.
        assert reserved["estimated_fee_cents"] == 216000

    def test_volume_tier_25_copies_twenty_percent_inversion(self, api):
        """PRD §3.5: "A volume discount keyed to `copies_requested` then applies:
        no discount for fewer than ten copies, ten percent for ten through
        twenty-four copies, and twenty percent for twenty-five copies or more."

        Design: Difficulty/combinatorial_formula/rental_fee_tiered_volume_discount_inversion
        """
        account, set_a, set_b = self._setup_two_sets()
        order_24 = reserve_order(create_order(account["id"], set_a["id"], copies=24)["id"])
        order_25 = reserve_order(create_order(account["id"], set_b["id"], copies=25)["id"])
        # 10000 x 25 x (1 - 0.20) = 200000: one more copy costs LESS in total.
        assert order_25["estimated_fee_cents"] == 200000
        assert order_24["estimated_fee_cents"] == 216000
        assert order_24["estimated_fee_cents"] > order_25["estimated_fee_cents"], (
            "the 25-copy tier boundary must invert the total fee"
        )


class TestLateTierBoundary:
    def test_late_fee_tier_boundary_day7_vs_day8(self, api):
        """PRD §3.6: "The late days then split chronologically into tiers — the
        first seven late days form the first tier, the next twenty-three the
        second ... ten percent of the daily base in the first tier, twenty-five
        percent in the second".

        Design: Corner/calculations/late_fee_tier_boundary_day7_vs_day8
        """
        publisher = create_publisher("LB Pub")
        work = create_work(publisher["id"], title="LB Work", catalog_number="LB-1")
        rental_set = create_rental_set(work["id"], set_code="LB-SET", copy_count=30,
                                       replacement_value_cents=240000)
        account = create_account("LB Acct", credit_tier="STANDARD", credit_limit_cents=0)
        advance_clock()
        order_a = create_order(account["id"], rental_set["id"], copies=5)
        reserve_order(order_a["id"]); dispatch_order(order_a["id"])
        confirm_order(order_a["id"], account["id"])
        order_b = create_order(account["id"], rental_set["id"], copies=5)
        reserve_order(order_b["id"]); dispatch_order(order_b["id"])
        confirm_order(order_b["id"], account["id"])

        advance_clock("2026-09-11T00:00:00Z")
        returned_a = check_in_order(order_a["id"], "A,A,A,A,A")
        advance_clock("2026-09-12T00:00:00Z")
        returned_b = check_in_order(order_b["id"], "A,A,A,A,A")

        # 7 late days, all in tier 1: 7 x 33 x 5 = 1155 over the 50000 base.
        assert returned_a["final_fee_cents"] == 51155
        # Day 8 enters tier 2: 1155 + 1 x rhu(333 x 0.25)=83 x 5 = 1570 late.
        assert returned_b["final_fee_cents"] == 51570


class TestDigitalFeeFactor:
    def test_digital_fulfillment_fee_factor_applied(self, api):
        """PRD §3.5: "For `DIGITAL` fulfillment the net is finally multiplied by
        0.80 and rounded half-up once more."

        Design: Corner/calculations/digital_fulfillment_fee_factor_applied
        """
        publisher = create_publisher("DF Pub")
        work = create_work(publisher["id"], title="DF Work", catalog_number="DF-1",
                           license_format="PRINT_AND_DIGITAL")
        rental_set = create_rental_set(work["id"], set_code="DF-SET", copy_count=30,
                                       replacement_value_cents=240000)
        account = create_account("DF Acct", credit_tier="STANDARD", credit_limit_cents=0)
        advance_clock()
        order = create_order(account["id"], rental_set["id"], copies=5,
                             fulfillment_format="DIGITAL")

        reserved = reserve_order(order["id"])
        # rhu(50000 x 0.80) = 40000.
        assert reserved["estimated_fee_cents"] == 40000


class TestSettlementPreview:
    def test_settlement_preview_projection_variant(self, api):
        """PRD §3.5: "While an order is `ON_LOAN` or `OVERDUE`, a
        settlement-preview capability projects the same formula with
        `loan_periods` recomputed against the later of `due_date` and the current
        clock date — so an overdue order projects extended-period fees —
        returning `projected_fee_cents` and `late_days`."

        Design: Corner/calculations/settlement_preview_projection_variant
        """
        ws = setup_order_on_loan(
            order_copies=5, publisher_name="SP Pub", work_title="SP Work",
            catalog_number="SP-1", set_code="SP-SET",
            account_overrides={"account_name": "SP Acct", "credit_tier": "STANDARD",
                               "credit_limit_cents": 0},
        )
        advance_clock("2026-09-20T00:00:00Z")

        preview = validate_success(
            api.get_settlement_preview(ws["order"]["id"], BILLING)
        )
        # [08-05, 09-20) spans 46 days -> ceil(46/30) = 2 periods -> 2 x 10000 x 5.
        assert preview["projected_fee_cents"] == 100000
        assert preview["late_days"] == 16
        assert fetch_order(ws["order"]["id"])["estimated_fee_cents"] == 50000, (
            "the preview must not rewrite the stored provisional estimate"
        )


class TestSourcingQuote:
    def test_sourcing_quote_rights_class_and_set_adjustment(self, api):
        """PRD §3.1: "The estimate starts from a base of 45 days, adds 30 days when
        the work's `rights_class` is `GRAND_RIGHTS`, adds 60 days when it is
        `RESTRICTED`, and subtracts 15 days when a rental set for the work exists
        (whether in service or under repair) with a condition grade of `A` or `B`;
        the result never falls below 7 days."

        Design: Corner/calculations/sourcing_quote_rights_class_and_set_adjustment
        """
        publisher = create_publisher("OOP Pub", out_of_print=True)
        work_grand = create_work(
            publisher["id"], title="Rare Opera", catalog_number="OOP-1",
            ensemble_tier="ORCHESTRA", base_rental_rate_cents=9000,
            sale_price_cents=3000, rights_class="GRAND_RIGHTS",
        )
        work_standard = create_work(
            publisher["id"], title="Rare Etude", catalog_number="OOP-2",
            base_rental_rate_cents=5000, sale_price_cents=900,
        )
        create_rental_set(work_standard["id"], set_code="OOP-SET", copy_count=4,
                          replacement_value_cents=32000)

        quote_grand = validate_success(api.get_sourcing_quote(work_grand["id"], CLERK))
        # 45 + 30 (GRAND_RIGHTS), no in-library set credit.
        assert quote_grand["estimated_days"] == 75
        quote_standard = validate_success(
            api.get_sourcing_quote(work_standard["id"], CLERK)
        )
        # 45 - 15 (an A-grade set exists).
        assert quote_standard["estimated_days"] == 30


class TestPerusalConversionRounding:
    def test_conversion_unit_price_rounded_before_quantity(self, api):
        """PRD §3.7: "The perusal conversion discount is fifteen percent off the
        work's `sale_price_cents`. The discounted per-unit price is rounded
        half-up first — before any multiplication by quantity — and becomes the
        sale's `unit_price_cents`; `total_cents` is then that per-unit price
        multiplied by `quantity`, and `balance_due_cents` starts equal to
        `total_cents`."

        Design: Difficulty/combinatorial_formula/perusal_conversion_per_unit_rounding_order
        """
        ws = setup_shipped_perusal(
            publisher_overrides=None,
            work_overrides={"sale_price_cents": 1099, "title": "Chorales",
                            "catalog_number": "P4-001"},
            account_overrides={"account_name": "St Mary Choir School"},
        )

        converted = validate_success(api.convert_perusal_request(
            ws["perusal"]["id"],
            {"converted_target_kind": "PURCHASE", "quantity": 7},
            CLERK,
        ))
        sale = get_success_data(api.get_sale_record(converted["converted_target_id"], BILLING))
        # rhu(1099 x 0.85) = 934 per unit, pinned BEFORE the quantity multiply.
        assert sale["unit_price_cents"] == 934
        # 934 x 7 = 6538 (rounding the total instead would give 6539).
        assert sale["total_cents"] == 6538

    def test_conversion_balance_due_equals_total_and_invoiced(self, api):
        """PRD §3.7: "`total_cents` is then that per-unit price multiplied by
        `quantity`, and `balance_due_cents` starts equal to `total_cents`."
        PRD §3.8: "Every new sale opens `INVOICED` with `balance_due_cents` equal
        to `total_cents`".

        Design: Difficulty/combinatorial_formula/perusal_conversion_per_unit_rounding_order
        """
        ws = setup_shipped_perusal(
            work_overrides={"sale_price_cents": 1099, "title": "Chorales",
                            "catalog_number": "P4-001"},
            account_overrides={"account_name": "St Mary Choir School"},
        )

        converted = validate_success(api.convert_perusal_request(
            ws["perusal"]["id"],
            {"converted_target_kind": "PURCHASE", "quantity": 7},
            CLERK,
        ))
        sale = get_success_data(api.get_sale_record(converted["converted_target_id"], BILLING))
        assert sale["status"] == "INVOICED"
        assert sale["balance_due_cents"] == 6538
        assert sale["balance_due_cents"] == sale["total_cents"]
