"""Award mathematics: share tiers, provisional vs final variants, caps, and
pinned per-component rounding."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_application_payload,
    make_cycle,
    make_defect,
    make_draft_notice,
    make_owner,
    make_owner_headers,
    make_parcel,
    make_segment,
    issue_notice,
    setup_application,
    setup_compliant_notice,
    setup_obligated_application,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
FINANCE = TEST_USERS["finance_headers"]


class TestDualVariantDivergence:
    def _setup_reimbursable(self):
        """100 sqft at share 50: provisional (engineer variant) = 60000."""
        bundle = setup_obligated_application(
            parcel_number="P-100", segment_code="S-100-1",
            owner_name="Ann Arbor", street_address="1 Main St",
            defect_type="VERTICAL_SEPARATION", measured_offset_inches=0.75,
            area_sqft=100, estimated_qty_sqft=100)
        return bundle

    def test_variants_diverge_on_actual_invoice(self, api):
        """PRD §3.5: "This engineer-estimate variant is deliberately
        forward-looking: it uses the flat engineer rate regardless of what the
        actual repair later costs, which is precisely where the actual-invoice
        variant of §3.6 diverges."
        PRD §3.6: "the repair part is `final_repair_cost_cents` multiplied by
        `share_pct` and divided by 100, rounded half-up"

        Design: Difficulty/dual_variant_calc/provisional_vs_final_award_divergence
        """
        bundle = self._setup_reimbursable()
        assert bundle["application"]["provisional_award_cents"] == 60000, \
            "engineer-rate variant: round_half_up(100 * 1200) * 50 / 100"
        setup_compliant_notice(bundle)

        app = validate_success(api.reimburse_application(
            bundle["application"]["id"],
            {"final_repair_cost_cents": 150000}, FINANCE))
        assert app["final_award_cents"] == 75000, \
            "actual-invoice variant: round_half_up(150000 * 50 / 100)"
        assert app["final_award_cents"] != \
            bundle["application"]["provisional_award_cents"]
        assert app["review_status"] == "REIMBURSED"
        assert app["payment_status"] == "DISBURSED"

    def test_cycle_ledger_reconciles_variants(self, api):
        """PRD §3.6: "On success the reservation unwinds — `committed_cents`
        drops by the provisional award while `disbursed_cents` grows by the
        final award — `payment_status` moves from `RESERVED` to `DISBURSED`"

        Design: Difficulty/dual_variant_calc/provisional_vs_final_award_divergence
        """
        bundle = self._setup_reimbursable()
        setup_compliant_notice(bundle)
        validate_success(api.reimburse_application(
            bundle["application"]["id"],
            {"final_repair_cost_cents": 150000}, FINANCE))

        cycle = validate_success(
            api.get_program_cycle(bundle["cycle"]["id"], COORD))
        assert cycle["committed_cents"] == 0
        assert cycle["disbursed_cents"] == 75000
        assert cycle["available_cents"] == 9_925_000


class TestTieredShareCapClamp:
    def test_share_capped_at_90_and_ramp_flag(self, api):
        """PRD §3.5: "The percentage is the sum of the three components, capped
        at 90 — so a low-income owner on an arterial fronts only 10 percent of
        the shared cost."
        PRD §3.5: "`ramp_upgrade_required` reads true exactly when at least one
        defect covered by the notice sits on a segment whose `is_corner_segment`
        is true and whose `has_existing_curb_ramp` is false"

        Design: Difficulty/combinatorial_formula/tiered_share_cap_clamp_with_ramp_branch
        """
        bundle = setup_application(
            parcel_number="P-300", segment_code="S-300-1",
            owner_name="Cora Cedar", street_address="3 Elm St",
            hardship_tier="LOW_INCOME", street_class="ARTERIAL",
            is_corner_lot=True, is_corner_segment=True,
            has_existing_curb_ramp=False, defect_type="SPALLING", area_sqft=20,
            estimated_qty_sqft=200)
        app = bundle["application"]
        assert app["share_pct"] == 90, "min(90, 50 + 20 + 30)"
        assert app["ramp_upgrade_required"] is True

    def test_award_clamped_by_per_application_cap(self, api):
        """PRD §3.5: "Finally, `provisional_award_cents` is the smallest of the
        400,000-cent (4,000-dollar) per-application cap, the uncapped award, and
        the lifetime remainder."

        Design: Difficulty/combinatorial_formula/tiered_share_cap_clamp_with_ramp_branch
        """
        bundle = setup_application(
            parcel_number="P-300", segment_code="S-300-1",
            owner_name="Cora Cedar", street_address="3 Elm St",
            hardship_tier="LOW_INCOME", street_class="ARTERIAL",
            is_corner_lot=True, is_corner_segment=True,
            has_existing_curb_ramp=False, defect_type="SPALLING", area_sqft=20,
            estimated_qty_sqft=200)
        # uncapped = round(240000 * 90 / 100) + 250000 = 216000 + 250000
        #          = 466000 -> clamped to the 400000 per-application cap
        assert bundle["application"]["provisional_award_cents"] == 400000


class TestUncappedTierSum:
    def test_collector_senior_share_80(self, api):
        """PRD §3.5: "The base city share is 50 percent. Street classification
        adds 20 points for an `ARTERIAL` parcel, 10 for a `COLLECTOR`, and
        nothing for a `LOCAL`. Hardship adds 30 points for a `LOW_INCOME` owner,
        20 for `SENIOR_65`, and nothing for `NONE`."

        Design: Corner/calculations/cost_share_pct_uncapped_tier_sum
        """
        bundle = setup_application(
            parcel_number="P-C3", segment_code="S-C3-1", owner_name="Rey Rowan",
            street_address="68 Rowan St", hardship_tier="SENIOR_65",
            street_class="COLLECTOR", is_corner_segment=False,
            has_existing_curb_ramp=True, defect_type="SPALLING", area_sqft=20,
            estimated_qty_sqft=100)
        app = bundle["application"]
        assert app["share_pct"] == 80, "50 base + 10 COLLECTOR + 20 SENIOR_65"
        assert app["ramp_upgrade_required"] is False
        # round_half_up(100 * 1200) = 120000; x 80/100 = 96000
        assert app["provisional_award_cents"] == 96000


class TestComponentRoundingOrder:
    def test_per_component_rounding_half_up(self, api):
        """PRD §2.6: "Where a computation produces a fraction, it is rounded
        half-up to the nearest whole cent, and — critically — rounding is
        applied **per component, in the pinned order each calculation specifies,
        before the components are summed**."
        PRD §3.5: "First, the repair estimate is the declared
        `estimated_qty_sqft` multiplied by the city engineer unit rate of 1,200
        cents per square foot — twelve dollars — rounded half-up."

        Design: Corner/calculations/provisional_award_component_rounding
        """
        bundle = setup_application(
            parcel_number="P-C4", segment_code="S-C4-1", owner_name="Sue Sumac",
            street_address="69 Sumac St", street_class="ARTERIAL",
            defect_type="SPALLING", area_sqft=11, estimated_qty_sqft=10.01)
        app = bundle["application"]
        assert app["share_pct"] == 70, "50 base + 20 ARTERIAL + 0 NONE"
        # repair estimate round_half_up(10.01 * 1200) = 12012;
        # city share round_half_up(12012 * 70 / 100) = round_half_up(8408.4)
        assert app["provisional_award_cents"] == 8408


class TestParcelLifetimeCap:
    def test_lifetime_cap_exhausted_rejects_creation(self, api):
        """PRD §3.5: "Fifth, the parcel's lifetime remaining allowance is
        800,000 cents (8,000 dollars) minus everything the parcel has already
        absorbed: the sum of `provisional_award_cents` over the parcel's
        applications in `APPROVED` or `OBLIGATED` status, plus the sum of
        `final_award_cents` over its `REIMBURSED` applications. When that
        remainder is zero or negative, creation fails outright with
        `ERR_PARCEL_LIFETIME_CAP_REACHED`."

        Design: Corner/errors/parcel_lifetime_cap_exhausted_rejected
        """
        cycle = make_cycle()
        owner = make_owner("Abe Alder", "108 Alder St")
        parcel = make_parcel(owner["id"], "P-T12", "108 Alder St", "LOCAL")
        owner_headers = make_owner_headers(owner["id"])

        notices = []
        for i in (1, 2, 3):
            segment = make_segment(parcel["id"], f"S-T12-{i}", length_ft=200)
            defect = make_defect(segment["id"], "SPALLING", 1000)
            notice = issue_notice(
                make_draft_notice(parcel["id"], [defect["id"]])["id"])
            notices.append(notice)

        app1 = validate_success(api.create_application(
            create_application_payload(notices[0]["id"], parcel["id"],
                                       cycle["id"], 1000),
            owner_headers), 201)
        assert app1["provisional_award_cents"] == 400000, \
            "per-application cap clamps round_half_up(1000*1200)*50/100 = 600000"
        validate_success(api.decide_application(
            app1["id"], {"outcome": "APPROVE"}, COORD))

        app2 = validate_success(api.create_application(
            create_application_payload(notices[1]["id"], parcel["id"],
                                       cycle["id"], 1000),
            owner_headers), 201)
        assert app2["provisional_award_cents"] == 400000, \
            "lifetime remaining 400000 clamps the second application"
        validate_success(api.decide_application(
            app2["id"], {"outcome": "APPROVE"}, COORD))

        # notice3 carries no application, so only the priority-11 lifetime
        # cap can reject this creation (800000 already absorbed).
        resp = api.create_application(
            create_application_payload(notices[2]["id"], parcel["id"],
                                       cycle["id"], 100),
            owner_headers)
        validate_error(resp, ApiErrorId.ERR_PARCEL_LIFETIME_CAP_REACHED)


class TestConditionalRampReceipt:
    def test_unrequired_ramp_receipt_rejected(self, api):
        """PRD §3.6: "The officer supplies the `final_repair_cost_cents` from
        the owner's invoice and, when the accessibility flag was set, a
        `ramp_receipt_cents`; supplying a nonzero ramp receipt for an
        application whose `ramp_upgrade_required` is false is rejected with
        `ERR_INVALID_REQUEST`."

        Design: Corner/errors/reimburse_with_unrequired_ramp_receipt_rejected
        """
        bundle = setup_obligated_application(
            parcel_number="P-T14", segment_code="S-T14-1",
            owner_name="Cy Cypress", street_address="110 Cypress St",
            defect_type="VERTICAL_SEPARATION", measured_offset_inches=0.75,
            area_sqft=100, is_corner_segment=False, estimated_qty_sqft=100)
        assert bundle["application"]["ramp_upgrade_required"] is False
        setup_compliant_notice(bundle)

        resp = api.reimburse_application(
            bundle["application"]["id"],
            {"final_repair_cost_cents": 100000, "ramp_receipt_cents": 5000},
            FINANCE)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        app = validate_success(api.reimburse_application(
            bundle["application"]["id"], {"final_repair_cost_cents": 100000},
            FINANCE))
        assert app["final_award_cents"] == 50000
        assert app["review_status"] == "REIMBURSED"
