"""Verified financials aggregation, FPL percentage, and discount tier
assignment (verified path)."""
from test_helpers import (
    assert_decimal_eq,
    assert_discount_determination,
    build_under_review_application,
    create_active_policy,
    create_determination,
    get_application,
    reject_document,
    set_clock,
    setup_verified_application,
    upload_and_verify,
    upload_document,
)


class TestVerifiedFinancialsAggregation:
    def test_income_annualization_factors(self, api):
        """PRD §3.6: "The `annualized_verified_income_cents` is the sum, over
        the application's `VERIFIED` documents of type `PAY_STUB`,
        `BENEFIT_LETTER`, or `TAX_RETURN`, of each document's `amount_cents`
        multiplied by its annualization factor — 26 for a biweekly pay stub,
        12 for a monthly benefit letter, 1 for an annual tax return."

        Design: Corner/calculations/verified_income_annualization_per_doc_type
        """
        set_clock("2026-02-01T00:00:00Z")
        create_active_policy()
        ctx = build_under_review_application(
            patient_name="Annual Anna", mrn="MRN-ANN-1", ssn_last4="0018",
            date_of_birth="1990-03-01", reported_income=4200000,
            members=(("SELF", 35),),
        )
        app_id = ctx["application"]["id"]
        member_id = ctx["members"][0]["id"]
        upload_and_verify(
            app_id, member_id, doc_type="PAY_STUB", amount_cents=100000,
            period_start="2026-01-01", period_end="2026-01-14",
        )
        upload_and_verify(
            app_id, member_id, doc_type="BENEFIT_LETTER", amount_cents=50000,
            period_start="2026-01-01", period_end="2026-01-31",
        )
        upload_and_verify(
            app_id, member_id, doc_type="TAX_RETURN", amount_cents=1000000,
            period_start="2025-01-01", period_end="2025-12-31",
        )
        app = get_application(app_id)
        # 100000*26 + 50000*12 + 1000000*1 = 2600000 + 600000 + 1000000
        assert app["annualized_verified_income_cents"] == 4200000

    def test_unverified_documents_excluded_from_aggregates(self, api):
        """PRD §3.6: "Only `VERIFIED` rows feed these aggregates; `SUBMITTED`
        and `REJECTED` documents are excluded entirely."

        Design: Corner/calculations/income_excludes_submitted_and_rejected_documents
        """
        set_clock("2026-02-01T00:00:00Z")
        create_active_policy()
        ctx = build_under_review_application(
            patient_name="Filter Fiona", mrn="MRN-FILT-1", ssn_last4="0019",
            date_of_birth="1990-04-01", reported_income=1000000,
            members=(("SELF", 35),),
        )
        app_id = ctx["application"]["id"]
        member_id = ctx["members"][0]["id"]
        upload_and_verify(
            app_id, member_id, doc_type="TAX_RETURN", amount_cents=1000000,
        )
        upload_document(  # stays SUBMITTED — must not count
            app_id, doc_type="TAX_RETURN", period_start="2024-01-01",
            period_end="2024-12-31", amount_cents=9000000,
            household_member_id=member_id,
        )
        bank = upload_document(
            app_id, doc_type="BANK_STATEMENT", period_start="2026-01-01",
            period_end="2026-01-31", amount_cents=9000000,
            household_member_id=member_id,
        )
        reject_document(bank["id"], rejection_reason="unreadable")
        app = get_application(app_id)
        assert app["annualized_verified_income_cents"] == 1000000, (
            "SUBMITTED TAX_RETURN of 9000000 excluded from income"
        )
        assert app["verified_liquid_assets_cents"] == 0, (
            "REJECTED BANK_STATEMENT excluded from assets"
        )
        assert app["status"] == "PENDING_DOCUMENTS", "rejection cascades (PRD §3.5)"


class TestFplAndTierAssignment:
    def test_household_size_scales_fpl_guideline(self, api):
        """PRD §3.6: "The FPL guideline amount for the household is the pinned
        policy's `fpl_base_cents` plus the household size minus one, times the
        policy's `fpl_increment_cents`."

        Design: Corner/calculations/household_size_scales_fpl_and_discount
        """
        ctx = setup_verified_application(
            patient_name="Family Fran", mrn="MRN-FAM-1", ssn_last4="0023",
            date_of_birth="1990-08-01", reported_income=5000000,
            members=(("SELF", 36), ("SPOUSE", 38), ("CHILD", 7)),
            accounts=((100000, 0),),
            tax_return_amount=5000000,
        )
        app = get_application(ctx["application"]["id"])
        assert app["household_size"] == 3
        det = create_determination(
            app["id"], "VERIFIED_APPLICATION", [ctx["accounts"][0]["id"]]
        )
        assert_discount_determination(det)
        # guideline = 1500000 + (3-1)*500000 = 2500000; 5000000/2500000 = 200.0000%
        assert_decimal_eq(det["fpl_pct_snapshot"], 200.0000, "fpl_pct_snapshot")
        assert det["tier"] == "TIER_FULL", "200.0000% is at the inclusive full ceiling"
        assert_decimal_eq(det["discount_pct"], 100.00, "discount_pct")

    def test_assets_equal_to_limit_pass(self, api):
        """PRD §3.8: "On the verified path, the asset test is consulted first:
        if the application's `verified_liquid_assets_cents` is strictly greater
        than the pinned policy's `asset_limit_cents`, the tier is `INELIGIBLE`
        with `discount_pct` 0.00 — exactly equal to the limit passes the asset
        test."

        Design: Corner/calculations/asset_limit_exact_boundary_passes
        """
        ctx = setup_verified_application(
            patient_name="Asset Abe", mrn="MRN-ASB-1", ssn_last4="0024",
            date_of_birth="1990-09-01", reported_income=2000000,
            reported_assets=2500000,
            accounts=((100000, 0),),
            tax_return_amount=2000000,
            extra_verified_docs=(
                {"doc_type": "BANK_STATEMENT", "amount_cents": 2500000,
                 "period_start": "2026-01-01", "period_end": "2026-01-31"},
            ),
        )
        app = get_application(ctx["application"]["id"])
        assert app["verified_liquid_assets_cents"] == 2500000
        det = create_determination(
            app["id"], "VERIFIED_APPLICATION", [ctx["accounts"][0]["id"]]
        )
        assert det["tier"] == "TIER_FULL", (
            "assets exactly equal to the 2500000 limit pass (strict >); "
            "income 2000000 = 133.3333% <= 200 decides TIER_FULL"
        )

    def test_asset_override_forces_ineligible(self, api):
        """PRD §3.8: "On the verified path, the asset test is consulted first:
        if the application's `verified_liquid_assets_cents` is strictly greater
        than the pinned policy's `asset_limit_cents`, the tier is `INELIGIBLE`
        with `discount_pct` 0.00 — exactly equal to the limit passes the asset
        test."

        Design: Difficulty/combinatorial_formula/tier_assignment_mode_a_multivariable_sliding_scale
        """
        ctx = setup_verified_application(
            patient_name="Asset Heavy", mrn="MRN-ASSET-1", ssn_last4="5555",
            date_of_birth="1970-03-03", reported_income=3750000,
            reported_assets=2500001,
            accounts=((1000000, 0),),
            tax_return_amount=3750000,
            extra_verified_docs=(
                {"doc_type": "BANK_STATEMENT", "amount_cents": 2500001,
                 "period_start": "2026-01-01", "period_end": "2026-01-31"},
            ),
        )
        det = create_determination(
            ctx["application"]["id"], "VERIFIED_APPLICATION",
            [ctx["accounts"][0]["id"]],
        )
        assert det["tier"] == "INELIGIBLE", (
            "verified assets 2500001 > asset_limit 2500000 force INELIGIBLE "
            "regardless of income"
        )
        assert_decimal_eq(det["discount_pct"], 0.00, "discount_pct")

    def test_asset_override_keeps_fpl_snapshot(self, api):
        """PRD §3.6: "The FPL percentage itself is the application's
        `annualized_verified_income_cents` multiplied by 100 and divided by
        that guideline amount, rounded half-up to 4 decimal places, and frozen
        on the determination record at creation."
        PRD §3.8: "On the verified path, the asset test is consulted first: if
        the application's `verified_liquid_assets_cents` is strictly greater
        than the pinned policy's `asset_limit_cents`, the tier is `INELIGIBLE`
        with `discount_pct` 0.00 — exactly equal to the limit passes the asset
        test."

        Design: Difficulty/combinatorial_formula/tier_assignment_mode_a_multivariable_sliding_scale
        """
        ctx = setup_verified_application(
            patient_name="Asset Heavy", mrn="MRN-ASSET-1", ssn_last4="5555",
            date_of_birth="1970-03-03", reported_income=3750000,
            reported_assets=2500001,
            accounts=((1000000, 0),),
            tax_return_amount=3750000,
            extra_verified_docs=(
                {"doc_type": "BANK_STATEMENT", "amount_cents": 2500001,
                 "period_start": "2026-01-01", "period_end": "2026-01-31"},
            ),
        )
        det = create_determination(
            ctx["application"]["id"], "VERIFIED_APPLICATION",
            [ctx["accounts"][0]["id"]],
        )
        # income 3750000 / guideline 1500000 = 250.0000% — income alone would
        # have been TIER_PARTIAL 75.00; only the asset test explains INELIGIBLE.
        assert_decimal_eq(det["fpl_pct_snapshot"], 250.0000, "fpl_pct_snapshot")
        assert det["tier"] == "INELIGIBLE"


class TestPartialCeilingBoundary:
    def test_income_exactly_at_partial_ceiling_gets_floor_discount(self, api):
        """PRD §3.1: "`partial_discount_max_fpl_pct` (the FPL percentage
        strictly above which an applicant is ineligible — exactly equal still
        eligible)"
        PRD §3.8: "Otherwise, if the FPL percentage is at or below
        `partial_discount_max_fpl_pct`, the tier is `TIER_PARTIAL` and the
        discount percentage is the sliding-scale interpolation: the policy's
        `partial_discount_floor_pct` plus the product of (the partial ceiling
        minus the actual FPL percentage) and (100 minus the floor), divided by
        (the partial ceiling minus the full ceiling), the whole rounded half-up
        to 2 decimal places."

        Design: Difficulty/boundary_precision_check/fpl_partial_band_upper_boundary_300pct
        """
        ctx = setup_verified_application(
            patient_name="Boundary Ann", mrn="MRN-BND-A", ssn_last4="9090",
            reported_income=4500000, accounts=((100000, 0),),
            tax_return_amount=4500000,
        )
        det = create_determination(
            ctx["application"]["id"], "VERIFIED_APPLICATION",
            [ctx["accounts"][0]["id"]],
        )
        # 4500000 * 100 / 1500000 = 300.0000 — exactly the partial ceiling
        assert_decimal_eq(det["fpl_pct_snapshot"], 300.0000, "fpl_pct_snapshot")
        assert det["tier"] == "TIER_PARTIAL", "exactly 300.0000% is still eligible"
        assert_decimal_eq(det["discount_pct"], 50.00, "discount_pct")

    def test_one_cent_over_partial_ceiling_ineligible(self, api):
        """PRD §3.1: "`partial_discount_max_fpl_pct` (the FPL percentage
        strictly above which an applicant is ineligible — exactly equal still
        eligible)"
        PRD §3.8: "Above the partial ceiling the tier is `INELIGIBLE` with
        `discount_pct` 0.00."

        Design: Difficulty/boundary_precision_check/fpl_partial_band_upper_boundary_300pct
        """
        ctx = setup_verified_application(
            patient_name="Boundary Bob", mrn="MRN-BND-B", ssn_last4="9191",
            reported_income=4500001, accounts=((100000, 0),),
            tax_return_amount=4500001,
        )
        det = create_determination(
            ctx["application"]["id"], "VERIFIED_APPLICATION",
            [ctx["accounts"][0]["id"]],
        )
        # 4500001 * 100 / 1500000 = 300.0000666... -> 300.0001 (4dp half-up)
        assert_decimal_eq(det["fpl_pct_snapshot"], 300.0001, "fpl_pct_snapshot")
        assert det["tier"] == "INELIGIBLE", (
            "one cent of income past the 300.0000% boundary flips the tier"
        )
        assert_decimal_eq(det["discount_pct"], 0.00, "discount_pct")
