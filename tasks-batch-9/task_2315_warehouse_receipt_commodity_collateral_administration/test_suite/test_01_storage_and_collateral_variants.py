"""
Two-variant calculations: the PROVISIONAL and FINAL storage accruals on the
same receipt, and the MARK_TO_MARKET versus FACE_ADVANCE collateral valuations
of the same pledged bushels.
"""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import factories as f
from test_helpers.assertions import assert_fields_equal


CLOCK_41_DAYS = "2026-09-14T09:00:00Z"
CLOCK_16_DAYS = "2026-08-20T09:00:00Z"


class TestStorageChargeProvisionalVersusFinal:
    def test_provisional_accrual_on_a_receipt_ignores_the_free_storage_days(
        self, api, base_full, set_clock
    ):
        """
        The read-time accrual on a receipt is the PROVISIONAL variant, which
        bills every one of the 41 inclusive days since issuance at 350
        millicents per bushel-day on 949 bushels and grants no free days:
        949 * 350 * 41 / 1000 = 13618 cents.

        PRD: "The **PROVISIONAL** variant sets the chargeable days equal to the
        day count and **ignores** the agreement's `free_storage_days` allowance
        entirely."

        Design: Difficulty/dual_variant_calc/storage_charge_provisional_vs_final_on_receipt
        """
        set_clock(CLOCK_41_DAYS)

        receipt = get_success_data(
            api.get_receipt(base_full["receipt_id"], base_full["operator_headers"]), 200
        )

        assert_fields_equal(
            receipt,
            {"quantity_bushels": 949, "provisional_storage_charge_cents": 13618},
        )

    def test_final_accrual_at_loadout_subtracts_the_free_storage_days(
        self, api, base_full, set_clock
    ):
        """
        Loadout uses the FINAL variant, which charges only 41 - 15 = 26 days on
        the receipt's whole outstanding 949 bushels: 949 * 350 * 26 / 1000 =
        8636 cents, 4982 cents below the provisional figure for the same day.

        PRD: "For the same receipt on the same date, the final figure is
        therefore never larger than the provisional one, and is strictly smaller
        whenever the day count is positive and free days were granted."

        Design: Difficulty/dual_variant_calc/storage_charge_provisional_vs_final_on_receipt
        """
        set_clock(CLOCK_41_DAYS)
        receipt = get_success_data(
            api.get_receipt(base_full["receipt_id"], base_full["operator_headers"]), 200
        )

        order = get_success_data(
            api.create_delivery_order(
                f.delivery_order_payload(
                    base_full["receipt_id"],
                    949,
                    "2026-09-14T10:00:00Z",
                    "2026-09-14T12:00:00Z",
                ),
                base_full["depositor_headers"],
            ),
            201,
        )
        loaded = get_success_data(
            api.load_delivery_order(
                order["id"], f.load_payload(949), base_full["operator_headers"]
            ),
            200,
        )

        assert_fields_equal(
            loaded, {"storage_charge_cents": 8636, "delivery_state": "LOADED"}
        )
        assert (
            receipt["provisional_storage_charge_cents"] - loaded["storage_charge_cents"]
            == 4982
        )


class TestLienValuationBasisDivergence:
    def test_mark_to_market_lien_prices_at_the_lender_mark_and_charges_the_admin_fee(
        self, api, base_full, set_clock
    ):
        """
        A MARK_TO_MARKET advance on 949 US_NO_1 bushels at 450 cents values the
        collateral at the lender's own mark: gross 427050, no grade discount so
        eligible 427050, a 25 bps admin fee of 1068 that joins the warehouseman
        lien of 12076 (5314 storage + 5694 receiving + 1068 fee), net 414974 and
        a 7000 bps limit of 290482.

        PRD: "Under `MARK_TO_MARKET`, the price is the lender's own
        `mark_price_cents_per_bushel`, the grade and impairment discounts of
        step 2 apply in full, and the step-4 administration fee is charged and
        therefore enters the warehouseman lien."

        Design: Difficulty/dual_variant_calc/lien_valuation_mark_to_market_vs_face_advance
        """
        set_clock(CLOCK_16_DAYS)

        lien = get_success_data(
            api.create_collateral_lien(
                f.collateral_lien_payload(
                    base_full["receipt_id"],
                    base_full["lender_id"],
                    principal_cents=250000,
                    valuation_basis="MARK_TO_MARKET",
                    mark_price_cents_per_bushel=450,
                    perfection_method="ELECTRONIC_CONTROL",
                ),
                base_full["lender_headers"],
            ),
            201,
        )

        assert_fields_equal(
            lien,
            {
                "gross_value_cents": 427050,
                "eligible_value_cents": 427050,
                "admin_fee_cents": 1068,
                "warehouseman_lien_cents": 12076,
                "net_collateral_cents": 414974,
                "advance_limit_cents": 290482,
            },
        )

    def test_face_advance_lien_prices_at_the_pinned_face_value_and_charges_no_fee(
        self, api, base_full, set_clock
    ):
        """
        A FACE_ADVANCE on the same receipt prices at the pinned 420-cent face
        value for a gross of 398580, forces the admin fee to zero so the
        warehouseman lien is only 11008 (5314 + 5694), and yields a limit of
        271300 — 19182 cents below the mark-to-market figure.

        PRD: "Under `FACE_ADVANCE`, the price is the receipt's
        `face_price_cents_per_bushel`, `grade_discount_bps` is forced to exactly
        zero because the declared face value already embeds the grade, and
        `admin_fee_cents` is exactly zero — which makes the warehouseman lien
        smaller as well."

        Design: Difficulty/dual_variant_calc/lien_valuation_mark_to_market_vs_face_advance
        """
        set_clock(CLOCK_16_DAYS)

        lien = get_success_data(
            api.create_collateral_lien(
                f.collateral_lien_payload(
                    base_full["receipt_id"],
                    base_full["lender_id"],
                    principal_cents=250000,
                    valuation_basis="FACE_ADVANCE",
                    mark_price_cents_per_bushel=450,
                    perfection_method="ELECTRONIC_CONTROL",
                ),
                base_full["lender_headers"],
            ),
            201,
        )

        assert_fields_equal(
            lien,
            {
                "gross_value_cents": 398580,
                "admin_fee_cents": 0,
                "warehouseman_lien_cents": 11008,
                "net_collateral_cents": 387572,
                "advance_limit_cents": 271300,
            },
        )

    def test_recording_two_advance_requests_commits_nothing_against_the_credit_line(
        self, api, base_full, set_clock
    ):
        """
        Both valuation bases can sit side by side as REQUESTED liens on one
        receipt without touching the lender's line, because credit is charged at
        perfection and not at request time.

        PRD: "**No credit is committed at this point** — recording a request
        costs the lender nothing against its line."

        Design: Difficulty/dual_variant_calc/lien_valuation_mark_to_market_vs_face_advance
        """
        set_clock(CLOCK_16_DAYS)
        for basis in ("MARK_TO_MARKET", "FACE_ADVANCE"):
            get_success_data(
                api.create_collateral_lien(
                    f.collateral_lien_payload(
                        base_full["receipt_id"],
                        base_full["lender_id"],
                        principal_cents=250000,
                        valuation_basis=basis,
                        mark_price_cents_per_bushel=450,
                        perfection_method="ELECTRONIC_CONTROL",
                    ),
                    base_full["lender_headers"],
                ),
                201,
            )

        lender = validate_success(
            api.get_party(base_full["lender_id"], base_full["lender_headers"])
        )

        assert lender["committed_advance_cents"] == 0
