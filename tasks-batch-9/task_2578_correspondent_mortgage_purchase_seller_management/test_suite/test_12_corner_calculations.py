"""Pricing constants, grid selection and the derived money on a purchase."""

from test_helpers import (
    ADMIN,
    QC,
    REVIEWER,
    TRADER,
    ApiErrorId,
    api_client,
    assert_commitment,
    assert_defect,
    assert_loan,
    assert_purchase_advice,
    assert_seller,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCommitmentPriceClamps:
    """Both ends of the permitted price band bite on real inputs."""

    @staticmethod
    def _two_products_at_the_extremes() -> dict:
        staged = fixtures.setup_lock_ready_seller(
            product_overrides={
                "product_code": "CLAMPHI",
                "base_price_pct": 103.900,
                "allowed_occupancies": ["PRIMARY"],
                "srp_pct": 1.000,
            },
            adjustment_overrides={
                "adjustment_code": "LLPA-HI-PLUS100",
                "price_adjustment_bps": 100,
            },
        )
        low = fixtures.setup_product_with_grid(
            adjustment_overrides={
                "adjustment_code": "LLPA-LO-MINUS300",
                "price_adjustment_bps": -300,
            },
            product_code="CLAMPLO",
            base_price_pct=98.100,
            allowed_occupancies=["PRIMARY"],
            srp_pct=1.000,
        )
        staged["low_product_id"] = low["product_id"]
        return staged

    def test_a_computed_price_above_the_ceiling_is_stored_at_the_ceiling(self):
        """105.150 of raw price is published as 104.000.

        A 103.900 base takes the mandatory spread and a full +100 basis points off
        the grid on a 15-day lock, which computes well past the top of the band, so
        the stored price sits on the ceiling while the grid contribution is still
        reported raw — the clamp is a price effect only.

        PRD: "That exact result is then clamped into the range from a floor of
        98.000 to a ceiling of 104.000 — a computed value below the floor becomes
        the floor, and one above the ceiling becomes the ceiling — and only the
        clamped value is rounded half up to three decimal places, becoming
        `commitment_price_pct`."

        Design: Corner/calculations/commitment_price_clamps_at_the_ceiling_and_the_floor_constants
        """
        staged = self._two_products_at_the_extremes()

        high = fixtures.setup_commitment(
            staged["seller_id"],
            staged["product_id"],
            delivery_expiry_date="2026-08-16",
        )

        assert_commitment(high)
        assert high["lock_term_days"] == 15
        assert high["llpa_bps_applied"] == 100
        assert high["commitment_price_pct"] == 104.000
        assert high["tolerance_cents"] == 2000000

    def test_a_computed_price_below_the_floor_is_stored_at_the_floor(self):
        """94.350 of raw price is published as 98.000.

        A 98.100 base loses 300 basis points on the grid, 40 more on the 60-day
        tier and 35 more for the best-efforts obligation, computing far below the
        bottom of the band, so the stored price sits on the floor. Being
        best-efforts, the line books no mandatory exposure alongside the ceiling
        line's full notional.

        PRD: "Clamping before rounding is the pinned order."

        Design: Corner/calculations/commitment_price_clamps_at_the_ceiling_and_the_floor_constants
        """
        staged = self._two_products_at_the_extremes()
        fixtures.setup_commitment(
            staged["seller_id"], staged["product_id"], delivery_expiry_date="2026-08-16"
        )

        low = fixtures.setup_commitment(
            staged["seller_id"],
            staged["low_product_id"],
            commitment_type="BEST_EFFORTS",
            delivery_expiry_date="2026-09-30",
        )

        assert low["lock_term_days"] == 60
        assert low["llpa_bps_applied"] == -300
        assert low["commitment_price_pct"] == 98.000
        assert low["tolerance_cents"] == 2000000

        seller = fixtures.read_seller(staged["seller_id"])
        assert seller["open_mandatory_exposure_cents"] == 100000000


class TestLlpaGridSelection:
    """Four selection rules separated on one grid and one lock term."""

    @staticmethod
    def _seller_with_a_three_row_grid() -> dict:
        staged = fixtures.setup_lock_ready_seller(
            product_overrides={
                "product_code": "GRID30F",
                "allowed_occupancies": ["PRIMARY"],
            },
            adjustment_overrides={
                "adjustment_code": "LLPA-F700-L85",
                "fico_min": 700,
                "fico_max": 739,
                "ltv_min_pct": 80.0,
                "ltv_max_pct": 85.0,
                "price_adjustment_bps": -50,
            },
        )
        fixtures.setup_pricing_adjustment(
            staged["product_id"],
            adjustment_code="LLPA-F740-L90",
            fico_min=740,
            fico_max=779,
            ltv_min_pct=85.0,
            ltv_max_pct=90.0,
            price_adjustment_bps=-15,
        )
        fixtures.setup_pricing_adjustment(
            staged["product_id"],
            adjustment_code="LLPA-RETIRED",
            fico_min=700,
            fico_max=779,
            ltv_min_pct=0.0,
            ltv_max_pct=100.0,
            price_adjustment_bps=-200,
            status="RETIRED",
        )
        return staged

    def test_the_band_bounds_decide_which_rows_a_reference_borrower_touches(self):
        """Three locks on touching 30-day windows, three different grid totals.

        A 700 FICO at 85.0 loan-to-value sits on the inclusive FICO floor and the
        inclusive upper leg of the band, so the -50 row applies and the lock prices
        at 100.880. A 740 FICO at 80.0 is past the inclusive 739 ceiling of that
        row and also fails its exclusive lower leg, so nothing matches and the lock
        prices at 101.380. A 740 FICO at 90.0 lands in the second row alone and
        prices at 101.230.

        PRD: "Every `PricingAdjustment` row belonging to the commitment's product
        whose `status` is `ACTIVE`, whose FICO band contains `reference_fico` with
        both `fico_min` and `fico_max` treated as inclusive, and whose
        loan-to-value band contains `reference_ltv_pct` with `ltv_min_pct` treated
        as exclusive and `ltv_max_pct` as inclusive, contributes its
        `price_adjustment_bps`."

        Design: Corner/calculations/llpa_grid_sums_matching_rows_with_inclusive_fico_and_exclusive_lower_ltv_bounds
        """
        staged = self._seller_with_a_three_row_grid()

        on_the_bounds = fixtures.setup_commitment(
            staged["seller_id"],
            staged["product_id"],
            notional_amount_cents=50000000,
            reference_fico=700,
            reference_ltv_pct=85.0,
        )
        outside_both = fixtures.setup_commitment(
            staged["seller_id"],
            staged["product_id"],
            notional_amount_cents=50000000,
            delivery_window_start="2026-08-31",
            delivery_expiry_date="2026-09-30",
            reference_fico=740,
            reference_ltv_pct=80.0,
        )
        second_row = fixtures.setup_commitment(
            staged["seller_id"],
            staged["product_id"],
            notional_amount_cents=50000000,
            delivery_window_start="2026-09-30",
            delivery_expiry_date="2026-10-30",
            reference_fico=740,
            reference_ltv_pct=90.0,
        )

        for commitment in (on_the_bounds, outside_both, second_row):
            assert commitment["lock_term_days"] == 30

        assert on_the_bounds["llpa_bps_applied"] == -50
        assert on_the_bounds["commitment_price_pct"] == 100.880
        assert outside_both["llpa_bps_applied"] == 0
        assert outside_both["commitment_price_pct"] == 101.380
        assert second_row["llpa_bps_applied"] == -15
        assert second_row["commitment_price_pct"] == 101.230

        seller = fixtures.read_seller(staged["seller_id"])
        assert seller["open_mandatory_exposure_cents"] == 150000000

    def test_a_retired_row_that_would_match_everything_contributes_nothing(self):
        """The -200 row spans every band in play and is still ignored.

        Its FICO span covers 700 through 779 and its loan-to-value span covers the
        whole range, so were it live it would take two full points off all three
        prices. None of the three prices moves, because a retired row is invisible
        to pricing.

        PRD: "Rows whose `status` is `RETIRED`, and rows belonging to any other
        product, are excluded entirely."

        Design: Corner/calculations/llpa_grid_sums_matching_rows_with_inclusive_fico_and_exclusive_lower_ltv_bounds
        """
        staged = self._seller_with_a_three_row_grid()

        prices = []
        for notional_window, fico, ltv in (
            (("2026-08-01", "2026-08-31"), 700, 85.0),
            (("2026-08-31", "2026-09-30"), 740, 80.0),
            (("2026-09-30", "2026-10-30"), 740, 90.0),
        ):
            commitment = fixtures.setup_commitment(
                staged["seller_id"],
                staged["product_id"],
                notional_amount_cents=50000000,
                delivery_window_start=notional_window[0],
                delivery_expiry_date=notional_window[1],
                reference_fico=fico,
                reference_ltv_pct=ltv,
            )
            prices.append(commitment["commitment_price_pct"])

        assert prices == [100.880, 101.380, 101.230]
        assert 99.380 not in prices
        assert 98.880 not in prices
        assert 99.230 not in prices

        rows, meta = validate_paginated(
            api_client.list_pricing_adjustments(staged["product_id"], ADMIN)
        )
        assert meta["total_count"] == 3
        assert sorted(row["status"] for row in rows) == ["ACTIVE", "ACTIVE", "RETIRED"]


class TestConditionalPassPenalties:
    """Five findings exactly, and the whole conditional tier that follows."""

    @staticmethod
    def _conditionally_passed_seller() -> dict:
        return fixtures.setup_lock_ready_seller(
            with_adjustment=False,
            findings_count=5,
            critical_findings_count=0,
            seller_overrides={
                "legal_name": "Meridian Home Lending",
                "tin": "308871462",
            },
        )

    def test_five_findings_halve_the_multiplier_and_name_the_tier_conditional(self):
        """The threshold is reached, not crossed, and the seller pays twice for it.

        Five ordinary findings with nothing critical yields a conditional pass, so
        the seller is approved onto the conditional tier with the frozen net worth
        multiplied by five rather than ten — 1,500,000,000 instead of
        3,000,000,000 — and is barred from retaining servicing.

        PRD: "The multiplier is ten times net worth for a `PASS` outcome and only
        five times net worth for a `CONDITIONAL_PASS` outcome, so the conditional
        tier is penalised twice over — once on servicing eligibility and once on how
        much mandatory exposure it may carry."

        Design: Corner/calculations/conditional_pass_qc_halves_the_exposure_multiplier_and_bars_retained_servicing
        """
        staged = self._conditionally_passed_seller()

        reviews = validate_paginated(
            api_client.list_qc_reviews(staged["seller_id"], QC)
        )[0]
        assert reviews[0]["outcome"] == "CONDITIONAL_PASS"
        assert reviews[0]["findings_count"] == 5
        assert reviews[0]["critical_findings_count"] == 0

        seller = fixtures.read_seller(staged["seller_id"])
        assert_seller(seller)
        assert seller["approval_status"] == "APPROVED"
        assert seller["approval_tier"] == "CONDITIONAL"
        assert seller["servicing_retained_eligible"] is False
        assert seller["mandatory_exposure_limit_cents"] == 1500000000
        assert seller["approved_tangible_net_worth_cents"] == 300000000
        assert seller["delivery_standing"] == "GOOD_STANDING"

    def test_the_same_file_is_refused_retained_and_accepted_released(self):
        """One field decides it: the conditional seller may not keep the servicing.

        The two delivery attempts differ only in the servicing election, and the
        retained one is refused outright while the released one is booked with its
        escrow balance, so exactly one of the two consumes capacity on the line.

        PRD: "A `servicing_election` of `RETAINED` is accepted only from a seller
        whose `servicing_retained_eligible` flag is true, else
        `ERR_SERVICING_RETAINED_NOT_ELIGIBLE`; a `RELEASED` election is always
        accepted."

        Design: Corner/calculations/conditional_pass_qc_halves_the_exposure_multiplier_and_bars_retained_servicing
        """
        staged = self._conditionally_passed_seller()
        commitment = fixtures.setup_commitment(
            staged["seller_id"], staged["product_id"]
        )

        validate_error(
            api_client.deliver_loan(
                commitment["id"],
                factories.loan_payload(
                    commitment["version"],
                    seller_loan_number="MH-0001",
                    servicing_election="RETAINED",
                ),
                staged["seller_headers"],
            ),
            ApiErrorId.ERR_SERVICING_RETAINED_NOT_ELIGIBLE,
            422,
        )
        assert validate_paginated(
            api_client.list_loans(staged["seller_headers"])
        )[1]["total_count"] == 0

        released = validate_success(
            api_client.deliver_loan(
                commitment["id"],
                factories.loan_payload(
                    commitment["version"],
                    seller_loan_number="MH-0001",
                    servicing_election="RELEASED",
                    escrow_balance_cents=320000,
                ),
                staged["seller_headers"],
            ),
            201,
        )

        assert_loan(released)
        assert released["servicing_election"] == "RELEASED"
        assert released["escrow_balance_cents"] == 320000
        assert fixtures.read_commitment(commitment["id"])["allocated_amount_cents"] == 40000000


class TestExpirySweepVariantAndSelection:
    """The sweep charges the flat variant and leaves working lines alone."""

    @staticmethod
    def _one_free_and_one_allocated_line_both_past_expiry() -> dict:
        staged = fixtures.setup_lock_ready_seller(with_adjustment=False)
        free = fixtures.setup_commitment(
            staged["seller_id"],
            staged["product_id"],
            delivery_expiry_date="2026-08-16",
        )
        allocated = fixtures.setup_commitment(
            staged["seller_id"],
            staged["product_id"],
            commitment_type="BEST_EFFORTS",
        )
        loan = fixtures.deliver_loan(allocated["id"], staged["seller_id"])
        fixtures.setup_clock("2026-08-31T00:00:00Z")
        staged["free_id"] = free["id"]
        staged["allocated_id"] = allocated["id"]
        staged["loan_id"] = loan["id"]
        return staged

    def test_the_sweep_expires_the_free_line_at_the_bare_administrative_charge(self):
        """No market price is observed, so no mark-to-market is assessed.

        The free mandatory line is 15 days past its expiry with its whole
        100,000,000 unfilled, which is billable well beyond tolerance, so the flat
        variant is recorded with the bare 25,000 charge, no market price and nothing
        in the paired-off bucket.

        PRD: "**Administrative flat**, recorded as `ADMINISTRATIVE_FLAT`, applies
        whenever a commitment leaves the live set with **no observed market price**
        — the expiry sweep, and cancellation driven by seller suspension or
        termination — and it applies that way for both commitment types."

        Design: Corner/calculations/expiry_sweep_picks_the_administrative_flat_variant_and_skips_allocated_lines
        """
        staged = self._one_free_and_one_allocated_line_both_past_expiry()

        summary = fixtures.sweep_due_commitments(staged["seller_id"])
        assert summary["expired_count"] == 1
        assert summary["expired_commitment_ids"] == [staged["free_id"]]
        assert summary["total_pair_off_fee_cents"] == 25000

        expired = fixtures.read_commitment(staged["free_id"])
        assert expired["status"] == "EXPIRED"
        assert expired["cancelled_amount_cents"] == 100000000
        assert expired["available_amount_cents"] == 0
        assert expired["pair_off_method"] == "ADMINISTRATIVE_FLAT"
        assert expired["pair_off_fee_cents"] == 25000
        assert expired["pair_off_market_price_pct"] is None
        assert expired["paired_off_amount_cents"] == 0

        seller = fixtures.read_seller(staged["seller_id"])
        assert seller["fee_receivable_cents"] == 25000
        assert seller["open_mandatory_exposure_cents"] == 0

    def test_a_line_carrying_a_delivered_loan_is_skipped_by_the_same_sweep(self):
        """Its expiry date has arrived too, and it survives untouched.

        The best-efforts line reached its own expiry instant on the sweep clock, but
        it still carries 40,000,000 of allocation for a loan in the pipeline, so the
        sweep passes over it: status, buckets and fee are exactly as they were, and
        the delivered file is undisturbed.

        PRD: "Commitments with loans still in the purchase pipeline are deliberately
        **skipped** rather than expired."

        Design: Corner/calculations/expiry_sweep_picks_the_administrative_flat_variant_and_skips_allocated_lines
        """
        staged = self._one_free_and_one_allocated_line_both_past_expiry()

        fixtures.sweep_due_commitments(staged["seller_id"])

        survivor = fixtures.read_commitment(staged["allocated_id"])
        assert survivor["status"] == "LOCKED"
        assert survivor["allocated_amount_cents"] == 40000000
        assert survivor["available_amount_cents"] == 60000000
        assert survivor["pair_off_fee_cents"] == 0
        assert survivor["pair_off_method"] is None
        assert fixtures.read_loan(staged["loan_id"])["purchase_status"] == "DELIVERED"

        _, meta = validate_paginated(
            api_client.list_commitments(TRADER, {"seller_id": staged["seller_id"]})
        )
        assert meta["total_count"] == 2


class TestVolumeIncentiveTier:
    """The loyalty rebate is measured over volume already bought."""

    @staticmethod
    def _first_hundred_million_purchased() -> dict:
        staged = fixtures.setup_lock_ready_seller(
            with_adjustment=False,
            product_overrides={
                "product_code": "BIGCONF",
                "base_price_pct": 100.500,
                "max_loan_amount_cents": 100000000,
                "allowed_commitment_types": ["MANDATORY"],
                "allowed_occupancies": ["PRIMARY"],
                "srp_pct": 1.000,
            },
        )
        commitment = fixtures.setup_commitment(
            staged["seller_id"], staged["product_id"], notional_amount_cents=200000000
        )
        loan = fixtures.deliver_loan(
            commitment["id"],
            staged["seller_id"],
            seller_loan_number="HP-1001",
            note_amount_cents=100000000,
            closing_date="2026-08-01",
        )
        fixtures.open_loan_review(loan["id"])
        fixtures.clear_loan_for_purchase(loan["id"])
        staged["commitment"] = commitment
        staged["commitment_id"] = commitment["id"]
        staged["first_loan_id"] = loan["id"]
        staged["first_advice"] = fixtures.issue_purchase_advice(loan["id"])
        return staged

    def test_the_first_advice_of_the_month_earns_no_rebate_at_all(self):
        """Nothing has been purchased yet, so the tier cannot engage.

        The 100.500 base plus the mandatory spread less the 30-day tier prices the
        line at 100.630, and the first advice carries that price unchanged: zero
        incentive, zero accrued days because the file closed on the issuance date,
        and no escrow or premium because the seller kept the servicing — leaving the
        flat wire fee as the only deduction.

        PRD: "The resulting `volume_incentive_bps` is 0 below 100,000,000 cents of
        month-to-date balance, 5 at or above 100,000,000 cents, and 10 at or above
        250,000,000 cents."

        Design: Corner/calculations/volume_incentive_tier_one_engages_at_exactly_one_hundred_million_of_prior_upb
        """
        staged = self._first_hundred_million_purchased()

        assert staged["commitment"]["commitment_price_pct"] == 100.630
        assert staged["commitment"]["tolerance_cents"] == 4000000

        advice = staged["first_advice"]
        assert_purchase_advice(advice)
        assert advice["volume_incentive_bps"] == 0
        assert advice["final_purchase_price_pct"] == 100.630
        assert advice["accrued_days"] == 0
        assert advice["accrued_interest_cents"] == 0
        assert advice["principal_purchase_cents"] == 100630000
        assert advice["escrow_funding_cents"] == 0
        assert advice["service_release_premium_cents"] == 0
        assert advice["defect_price_adjustment_cents"] == 0
        assert advice["wire_fee_cents"] == 3500
        assert advice["net_wire_cents"] == 100626500

    def test_the_second_advice_sees_exactly_the_threshold_and_takes_five_basis_points(self):
        """100,000,000 of purchased balance is at the tier, and the tier is inclusive.

        The second file is identical in every respect, yet it prices five basis
        points better at 100.680 because the first purchase now counts as
        month-to-date volume, and four days of interest at 6.500 percent join the
        wire. The two settlements together fill the line to its full notional.

        PRD: "The month-to-date unpaid principal balance is the sum of
        `note_amount_cents` over the **same seller's** loans whose `purchase_status`
        is `PURCHASED`, `REPURCHASE_DEMANDED` or `REPURCHASED` and whose
        `purchased_at` falls at or after `month_start` and strictly before the
        issuance instant."

        Design: Corner/calculations/volume_incentive_tier_one_engages_at_exactly_one_hundred_million_of_prior_upb
        """
        staged = self._first_hundred_million_purchased()
        fixtures.settle_purchase_advice(staged["first_advice"]["id"], "WIRE-0001")

        fixtures.setup_clock("2026-08-05T00:00:00Z")
        second = fixtures.deliver_loan(
            staged["commitment_id"],
            staged["seller_id"],
            seller_loan_number="HP-1002",
            note_amount_cents=100000000,
            closing_date="2026-08-01",
            first_payment_due_date="2026-10-01",
        )
        fixtures.open_loan_review(second["id"])
        fixtures.clear_loan_for_purchase(second["id"])
        advice = fixtures.issue_purchase_advice(second["id"])

        assert advice["volume_incentive_bps"] == 5
        assert advice["final_purchase_price_pct"] == 100.680
        assert advice["accrued_days"] == 4
        assert advice["accrued_interest_cents"] == 72222
        assert advice["principal_purchase_cents"] == 100680000
        assert advice["net_wire_cents"] == 100748722

        settled = fixtures.settle_purchase_advice(advice["id"], "WIRE-0002")
        assert settled["status"] == "SETTLED"
        assert settled["settled_by_user_id"] == "u-pr-2"
        assert fixtures.read_loan(second["id"])["purchase_status"] == "PURCHASED"
        assert fixtures.read_loan(staged["first_loan_id"])["purchase_status"] == "PURCHASED"

        commitment = fixtures.read_commitment(staged["commitment_id"])
        assert commitment["status"] == "FULFILLED"
        assert commitment["fulfilled_amount_cents"] == 200000000
        assert commitment["available_amount_cents"] == 0
        assert commitment["pair_off_fee_cents"] == 0

        seller = fixtures.read_seller(staged["seller_id"])
        assert seller["net_funded_cents"] == 201375222
        assert seller["open_mandatory_exposure_cents"] == 0


class TestDefectClassificationAndCureWindows:
    """Severity sets the rope; one category cancels it entirely."""

    @staticmethod
    def _four_findings_on_one_file() -> dict:
        staged = fixtures.setup_loan_in_review()
        staged["low"] = fixtures.record_defect(
            staged["loan_id"], "DOC-MISSING-1008", "DOCUMENTATION", "LOW"
        )
        staged["medium"] = fixtures.record_defect(
            staged["loan_id"], "COLL-APPR-3040", "COLLATERAL", "MEDIUM"
        )
        staged["high"] = fixtures.record_defect(
            staged["loan_id"], "CRED-DTI-2210", "CREDIT", "HIGH"
        )
        staged["compliance"] = fixtures.record_defect(
            staged["loan_id"], "COMP-TRID-4001", "COMPLIANCE", "HIGH"
        )
        return staged

    def test_each_severity_gets_its_own_rope_and_the_compliance_high_gets_none(self):
        """Fifteen, ten and five days, then a null where the category crossed in.

        Three findings of rising severity take shortening cure windows from the same
        2026-08-01 creation instant, and the fourth — high severity again, but in
        the compliance category — is unfixable and carries no deadline at all, which
        is what makes it count on the loan's non-curable tally.

        PRD: "The `cure_deadline_at` follows from the same derivation: a
        `NON_CURABLE` defect has none and carries null, while a `CURABLE` defect's
        deadline is its `created_at` advanced by a severity-dependent window — 15
        days for `LOW`, 10 days for `MEDIUM`, and only 5 days for `HIGH`."

        Design: Corner/calculations/defect_classification_and_cure_windows_follow_severity_and_category
        """
        staged = self._four_findings_on_one_file()

        assert_defect(staged["low"])
        assert staged["low"]["classification"] == "CURABLE"
        assert staged["low"]["cure_deadline_at"] == "2026-08-16T00:00:00.000Z"
        assert staged["medium"]["classification"] == "CURABLE"
        assert staged["medium"]["cure_deadline_at"] == "2026-08-11T00:00:00.000Z"
        assert staged["high"]["classification"] == "CURABLE"
        assert staged["high"]["cure_deadline_at"] == "2026-08-06T00:00:00.000Z"
        assert staged["compliance"]["classification"] == "NON_CURABLE"
        assert staged["compliance"]["cure_deadline_at"] is None

        loan = fixtures.read_loan(staged["loan_id"])
        assert loan["open_defect_count"] == 4
        assert loan["non_curable_defect_count"] == 1
        assert loan["purchase_status"] == "SUSPENDED"
        assert loan["review_cycle_count"] == 0

    def test_the_non_curable_finding_refuses_both_a_cure_and_a_waiver(self):
        """Neither the seller nor the reviewer can dispose of it.

        The finding is open, so the openness gate passes on both routes, and both
        are still refused for the same reason — a compliance failure in a closed
        file cannot be papered over — leaving the defect open and the file suspended.

        PRD: "A defect is `NON_CURABLE` when its `severity` is `CRITICAL`, and also
        when its `category` is `COMPLIANCE` and its `severity` is `HIGH`; in every
        other combination it is `CURABLE`."

        Design: Corner/calculations/defect_classification_and_cure_windows_follow_severity_and_category
        """
        staged = self._four_findings_on_one_file()
        defect_id = staged["compliance"]["id"]

        validate_error(
            api_client.cure_defect(
                defect_id,
                {"cure_document_reference": "TRID-FIX-1"},
                staged["seller_headers"],
            ),
            ApiErrorId.ERR_DEFECT_NOT_CURABLE,
            409,
        )
        validate_error(
            api_client.waive_defect(defect_id, {"price_adjustment_bps": -25}, REVIEWER),
            ApiErrorId.ERR_DEFECT_NOT_CURABLE,
            409,
        )

        still_open = [
            defect
            for defect in fixtures.read_loan_defects(staged["loan_id"])
            if defect["id"] == defect_id
        ][0]
        assert still_open["status"] == "OPEN"
        assert still_open["price_adjustment_bps"] == 0
        assert still_open["cured_at"] is None

        loan = fixtures.read_loan(staged["loan_id"])
        assert loan["open_defect_count"] == 4
        assert loan["non_curable_defect_count"] == 1
