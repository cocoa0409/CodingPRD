"""Tax substantiation: rate cards, receipt arithmetic, variant selection,
half-open periods, amendment, and the fiscal gates (PRD §3.7-§3.8)."""
from test_helpers import (
    TEST_USERS, validate_success, validate_error, ApiErrorId,
    create_donor, create_agency, create_driver, add_window, create_offer,
    create_rate_card, set_clock, dispatch_run, respond_run, record_pickup,
    record_delivery, verify_run, issue_receipt,
    assert_tax_receipt,
    setup_delivered_run, setup_verified_run,
    setup_two_donors_with_identical_verified_rescues,
)
from test_helpers.factories import create_rate_card_payload

ADMIN = TEST_USERS["admin_headers"]

PERIOD = ("2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z")


class TestStandardVsEnhancedDivergence:
    def test_standard_donor_deducts_fair_market_value(self, api):
        """PRD §3.8: "The receipt's `deductible_value_cents` is the enhanced
        total when the donor's `enhanced_deduction_eligible` flag is set, and
        the standard total otherwise."
        PRD §3.8: "Its standard value, `standard_cents`, is that weight
        multiplied by the card's fair-market-value rate for the category. Its
        enhanced per-pound rate is the smaller of two quantities: twice the
        basis rate, or the basis rate plus one-half of the excess of the
        fair-market-value rate over the basis rate — and that half-excess is
        rounded half-up to a whole cent before being added."

        Design: Difficulty/dual_variant_calc/tax_standard_vs_enhanced_diverge_for_identical_rescue
        """
        s = setup_two_donors_with_identical_verified_rescues()
        resp = issue_receipt(s["donor_std"]["id"], *PERIOD)
        receipt = validate_success(resp, 201)
        assert_tax_receipt(receipt)
        assert receipt["total_weight_lbs"] == 50
        # 50 lbs x 300 cents FMV (COLD_HELD).
        assert receipt["total_standard_value_cents"] == 15000
        # Enhanced rate: min(200, 100 + round_half_up(100)) = 200 -> 10000.
        assert receipt["total_enhanced_value_cents"] == 10000
        assert receipt["deductible_value_cents"] == 15000, (
            "enhanced_deduction_eligible=false selects the standard variant"
        )

    def test_enhanced_donor_deducts_less_for_identical_rescue(self, api):
        """PRD §3.8: "The receipt's `deductible_value_cents` is the enhanced
        total when the donor's `enhanced_deduction_eligible` flag is set, and
        the standard total otherwise."
        PRD §3.8: "Because the enhanced rate never exceeds the fair-market
        value, the enhanced variant is always at most the standard variant for
        identical data."

        Design: Difficulty/dual_variant_calc/tax_standard_vs_enhanced_diverge_for_identical_rescue
        """
        s = setup_two_donors_with_identical_verified_rescues()
        resp = issue_receipt(s["donor_std"]["id"], *PERIOD)
        std_receipt = validate_success(resp, 201)
        resp = issue_receipt(s["donor_enh"]["id"], *PERIOD)
        enh_receipt = validate_success(resp, 201)
        assert_tax_receipt(enh_receipt)
        assert enh_receipt["deductible_value_cents"] == 10000, (
            "enhanced_deduction_eligible=true selects the enhanced variant"
        )
        # Byte-identical rescues, different variants: the deductibles diverge
        # by exactly 15000 - 10000 = 5000 cents.
        assert (std_receipt["deductible_value_cents"]
                - enh_receipt["deductible_value_cents"]) == 5000


class TestEstimatedVsVerifiedWeight:
    def test_in_flight_run_carries_the_estimate(self, api):
        """PRD §3.7: "While any of a donor's offers sits in `MATCHED`,
        `SCHEDULED`, `PICKED_UP`, or `DELIVERED`, its `pending_estimated_lbs`
        carries the sum of those offers' `estimated_weight_lbs` — the donor's
        self-report."

        Design: Difficulty/dual_variant_calc/estimated_vs_verified_weight_diverge_for_same_rescue
        """
        ctx = setup_delivered_run(estimated_weight_lbs=80, actual_weight_lbs=60)
        assert ctx["run"]["run_status"] == "DELIVERED"
        resp = api.get_donor_site(ctx["donor"]["id"], ADMIN)
        donor = validate_success(resp)
        assert donor["pending_estimated_lbs"] == 80, (
            "the donor's self-reported estimate while the run is in flight"
        )
        assert donor["lifetime_weight_lbs"] == 0

    def test_verify_switches_estimate_to_scale_weight(self, api):
        """PRD §3.7: "At countersignature the estimate leaves
        `pending_estimated_lbs` and the run's agency-scale `actual_weight_lbs`
        enters `lifetime_weight_lbs`, so the verified total is the sum of actual
        weights over the donor's `VERIFIED` runs. The two variants diverge
        exactly when a scale reading disagrees with a donor estimate."

        Design: Difficulty/dual_variant_calc/estimated_vs_verified_weight_diverge_for_same_rescue
        """
        ctx = setup_delivered_run(estimated_weight_lbs=80, actual_weight_lbs=60)
        resp = api.get_donor_site(ctx["donor"]["id"], ADMIN)
        before = validate_success(resp)
        assert (before["pending_estimated_lbs"], before["lifetime_weight_lbs"]) == (80, 0)
        verify_run(ctx["run"]["id"], ctx["agency"]["id"])
        resp = api.get_donor_site(ctx["donor"]["id"], ADMIN)
        after = validate_success(resp)
        assert after["pending_estimated_lbs"] == 0
        assert after["lifetime_weight_lbs"] == 60, (
            "80 estimated vs 60 verified: the variants disagree on one rescue"
        )


class TestEnhancedRateRoundingOrder:
    def _setup(self, api):
        create_rate_card(cold_held_fmv_cents_per_lb=151,
                         cold_held_basis_cents_per_lb=100)
        donor = create_donor(legal_name="Round Bistro", ein="444444444",
                             contact_email="r@bistro.example",
                             enhanced_deduction_eligible=True)
        ctx = setup_verified_run(donor=donor, estimated_weight_lbs=10,
                                 actual_weight_lbs=10)
        return ctx

    def test_per_lb_rate_rounded_before_multiply(self, api):
        """PRD §3.8: "The rounding order is pinned: the per-pound enhanced rate
        is fully settled, including its half-up rounding, before it is
        multiplied by the line's weight to produce `enhanced_cents`; rounding
        the line total after multiplication is a different number and is not
        permitted. For example, at a fair-market value of 151 cents and a basis
        of 100 cents, the enhanced per-pound rate is 126 cents — the half-excess
        of 25.5 rounds half-up to 26, well under the doubling cap of 200 — so a
        ten-pound line is worth 1260 cents, not the 1255 that rounding after
        multiplication would yield."

        Design: Difficulty/combinatorial_formula/enhanced_rate_rounded_per_lb_before_multiply
        """
        ctx = self._setup(api)
        resp = issue_receipt(ctx["donor"]["id"], *PERIOD)
        receipt = validate_success(resp, 201)
        assert_tax_receipt(receipt)
        assert receipt["total_enhanced_value_cents"] == 1260, (
            "10 x 126 with the per-lb half-up rounding applied BEFORE multiply"
        )
        assert receipt["total_enhanced_value_cents"] != 1255, (
            "1255 is the forbidden round-after-multiply result"
        )
        assert receipt["deductible_value_cents"] == 1260

    def test_standard_total_uses_fmv_times_weight(self, api):
        """PRD §3.8: "Its standard value, `standard_cents`, is that weight
        multiplied by the card's fair-market-value rate for the category."

        Design: Difficulty/combinatorial_formula/enhanced_rate_rounded_per_lb_before_multiply
        """
        ctx = self._setup(api)
        resp = issue_receipt(ctx["donor"]["id"], *PERIOD)
        receipt = validate_success(resp, 201)
        assert_tax_receipt(receipt)
        assert receipt["total_standard_value_cents"] == 1510, "10 lbs x 151 cents"
        assert receipt["total_weight_lbs"] == 10


class TestReceiptPeriodHalfOpen:
    def test_verified_at_period_start_included_at_period_end_excluded(self, api):
        """PRD §3.8: "A run contributes exactly when it is `VERIFIED`, belongs
        to this donor, and its `verified_at` falls on or after `period_start`
        and strictly before `period_end`; if that set is empty the issuance
        stops with `ERR_RECEIPT_NO_VERIFIED_RESCUES`."

        Design: Corner/calculations/receipt_period_is_half_open_on_verified_at
        """
        create_rate_card()
        donor = create_donor(legal_name="HO Bistro", ein="100000010",
                             contact_email="ho@bistro.example")
        agency = create_agency(accepts_categories=("SHELF_STABLE",),
                               capacity_shelf_stable_lbs=100)
        driver = create_driver(cooler_slot_count=0)
        add_window(driver["id"], "2026-08-05T00:00:00Z", "2026-08-05T12:00:00Z")
        add_window(driver["id"], "2026-08-10T00:00:00Z", "2026-08-10T12:00:00Z")
        o1 = create_offer(donor["id"], food_category="SHELF_STABLE",
                          estimated_weight_lbs=10,
                          pickup_window_start="2026-08-05T06:00:00Z",
                          pickup_window_end="2026-08-05T08:00:00Z", publish=True)
        o2 = create_offer(donor["id"], food_category="SHELF_STABLE",
                          estimated_weight_lbs=20,
                          pickup_window_start="2026-08-10T06:00:00Z",
                          pickup_window_end="2026-08-10T08:00:00Z", publish=True)
        # R1 verified exactly AT the period start.
        set_clock("2026-08-04T09:00:00Z")
        r1 = dispatch_run(o1["id"], driver_id=driver["id"],
                          agency_id=agency["id"])
        respond_run(r1["id"], driver["id"], "ACCEPT")
        record_pickup(r1["id"], driver["id"],
                      pickup_time="2026-08-05T06:30:00Z")
        record_delivery(r1["id"], driver["id"],
                        arrival_time="2026-08-05T07:30:00Z", actual_weight_lbs=10)
        verify_run(r1["id"], agency["id"], set_clock_to="2026-08-05T09:00:00Z")
        # R2 verified exactly AT the period end.
        set_clock("2026-08-09T09:00:00Z")
        r2 = dispatch_run(o2["id"], driver_id=driver["id"],
                          agency_id=agency["id"])
        respond_run(r2["id"], driver["id"], "ACCEPT")
        record_pickup(r2["id"], driver["id"],
                      pickup_time="2026-08-10T06:30:00Z")
        record_delivery(r2["id"], driver["id"],
                        arrival_time="2026-08-10T07:30:00Z", actual_weight_lbs=20)
        verify_run(r2["id"], agency["id"], set_clock_to="2026-08-10T09:00:00Z")
        set_clock("2026-08-11T00:00:00Z")
        resp = issue_receipt(donor["id"], "2026-08-05T09:00:00Z",
                             "2026-08-10T09:00:00Z")
        receipt = validate_success(resp, 201)
        assert_tax_receipt(receipt)
        # [period_start, period_end): R1 (at the start) is in, R2 (at the end)
        # is out — only 10 of the 30 verified lbs are captured.
        assert receipt["total_weight_lbs"] == 10
        assert receipt["total_standard_value_cents"] == 1200, (
            "10 lbs x 120 cents (SHELF_STABLE)"
        )


class TestReceiptGatesAndAmendment:
    def _setup_delivered_unverified(self, api):
        create_rate_card()
        ctx = setup_delivered_run(food_category="SHELF_STABLE",
                                  estimated_weight_lbs=10, actual_weight_lbs=10,
                                  agency_capacity_lbs=100)
        return ctx

    def test_unverified_run_yields_no_verified_rescues_error(self, api):
        """PRD §3.8: "Two fiscal gates then fire in a fixed sequence: the
        verified-run set first, rate-card coverage second. A run contributes
        exactly when it is `VERIFIED`, belongs to this donor, and its
        `verified_at` falls on or after `period_start` and strictly before
        `period_end`; if that set is empty the issuance stops with
        `ERR_RECEIPT_NO_VERIFIED_RESCUES`. Runs still `DELIVERED` but not yet
        countersigned never contribute."

        Design: Corner/calculations/receipt_requires_verified_run_and_excludes_amended_from_aggregates
        """
        ctx = self._setup_delivered_unverified(api)
        resp = issue_receipt(ctx["donor"]["id"], *PERIOD)
        validate_error(resp, ApiErrorId.ERR_RECEIPT_NO_VERIFIED_RESCUES)

    def test_amended_receipt_excluded_from_lifetime_tax_value(self, api):
        """PRD §3.8: "Issuing a new receipt for the same donor with identical
        `period_start` and `period_end` supersedes the previously `ISSUED`
        receipt, which becomes `AMENDED`; an `AMENDED` receipt never contributes
        to anything downstream. The donor's `lifetime_tax_value_cents` is
        recomputed as the sum of `deductible_value_cents` over the donor's
        `ISSUED` receipts only, and the act of issuance increments the donor
        site's `version` by one — which is exactly what the
        `expected_donor_version` guard of §2.6 watches."

        Design: Corner/calculations/receipt_requires_verified_run_and_excludes_amended_from_aggregates
        """
        ctx = self._setup_delivered_unverified(api)
        verify_run(ctx["run"]["id"], ctx["agency"]["id"])
        resp = issue_receipt(ctx["donor"]["id"], *PERIOD)
        rc1 = validate_success(resp, 201)
        assert rc1["deductible_value_cents"] == 1200, "10 lbs x 120, standard"
        resp = api.get_donor_site(ctx["donor"]["id"], ADMIN)
        assert validate_success(resp)["lifetime_tax_value_cents"] == 1200
        # Reissue for the identical period: supersedes rc1, never double-counts.
        resp = issue_receipt(ctx["donor"]["id"], *PERIOD)
        rc2 = validate_success(resp, 201)
        assert rc2["deductible_value_cents"] == 1200
        resp = api.list_donor_tax_receipts(
            ctx["donor"]["id"], ADMIN, params={"status": "AMENDED"})
        amended = validate_success(resp)
        assert [r["id"] for r in amended] == [rc1["id"]]
        resp = api.list_donor_tax_receipts(
            ctx["donor"]["id"], ADMIN, params={"status": "ISSUED"})
        issued = validate_success(resp)
        assert [r["id"] for r in issued] == [rc2["id"]]
        resp = api.get_donor_site(ctx["donor"]["id"], ADMIN)
        assert validate_success(resp)["lifetime_tax_value_cents"] == 1200, (
            "the AMENDED receipt contributes nothing: no double count"
        )

    def test_no_rate_card_covering_period_end_rejected(self, api):
        """PRD §3.8: "Next, the unique rate card whose window contains
        `period_end` — `effective_start` on or before it, `effective_end`
        strictly after — must exist, else `ERR_NO_RATE_CARD_EFFECTIVE`."

        Design: Corner/errors/receipt_without_effective_rate_card_rejected
        """
        # The only card on file covers [2026-01-01, 2026-08-01): it does NOT
        # contain period_end 2026-09-01.
        create_rate_card(effective_end="2026-08-01T00:00:00Z")
        ctx = setup_verified_run(food_category="SHELF_STABLE",
                                 estimated_weight_lbs=10, actual_weight_lbs=10,
                                 agency_capacity_lbs=100,
                                 verify_clock="2026-08-02T13:20:00Z")
        resp = issue_receipt(ctx["donor"]["id"], *PERIOD)
        validate_error(resp, ApiErrorId.ERR_NO_RATE_CARD_EFFECTIVE)


class TestRateCardWindows:
    def test_overlap_rejected_adjacency_allowed_no_version_consumed(self, api):
        """PRD §3.8: "A new card's window must not overlap any existing card's
        window, with half-open adjacency allowed — a card starting exactly when
        another ends coexists with it — and an overlap is rejected with
        `ERR_RATE_CARD_WINDOW_OVERLAP`. Successful creations assign
        `card_version` monotonically starting at 1, in creation order; rejected
        creations never consume a version."

        Design: Corner/errors/rate_card_window_overlap_and_adjacency
        """
        resp = api.create_rate_card(
            create_rate_card_payload(effective_end="2026-07-01T00:00:00Z"), ADMIN)
        rc1 = validate_success(resp, 201)
        assert rc1["card_version"] == 1
        # [2026-06-15, 2026-08-01) intersects RC1's window.
        resp = api.create_rate_card(
            create_rate_card_payload(effective_start="2026-06-15T00:00:00Z",
                                     effective_end="2026-08-01T00:00:00Z"),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_RATE_CARD_WINDOW_OVERLAP)
        # Starting exactly at RC1's end is allowed; the rejected creation
        # consumed no version, so this card takes version 2.
        resp = api.create_rate_card(
            create_rate_card_payload(effective_start="2026-07-01T00:00:00Z"),
            ADMIN)
        rc2 = validate_success(resp, 201)
        assert rc2["card_version"] == 2
