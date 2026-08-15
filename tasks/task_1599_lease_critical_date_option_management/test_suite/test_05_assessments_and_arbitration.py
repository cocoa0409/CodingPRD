"""Market-rate assessments, baseball arbitration, and the dispute window."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_arbitration_case,
    assert_assessment,
    create_comparable_assessment_payload,
    create_decision_payload,
    create_dispute_payload,
    create_notice_payload,
    create_option_payload,
    create_regression_assessment_payload,
    get_success_data,
    set_clock,
    setup_active_lease,
    setup_notice_sent,
    setup_option_on_active_lease,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestDualVariantFairMarketRent:
    def test_comparable_average_variant_computes_mean(self, api):
        """PRD §3.6: "With `COMPARABLE_AVERAGE`, the payload carries
        `comparable_rents_cents` — three to seven comparable annual rents in
        cents per square-foot-year, every one positive — and the provisional
        rent is their arithmetic mean, rounded half up to a whole cent."

        Design: Difficulty/dual_variant_calc/fmr_comparable_average_vs_psf_regression_diverge
        """
        ws = setup_option_on_active_lease(
            name="P1", region="WEST",
            option_overrides={
                "option_type": "RENEWAL",
                "notice_window_open_date": "2026-09-01T00:00:00Z",
                "notice_window_close_date": "2027-06-30T00:00:00Z",
                "target_commencement_date": "2028-01-01T00:00:00Z",
                "extension_years": 5,
                "rate_determination": "FAIR_MARKET",
            },
            rentable_square_feet=10000,
            base_rent_cents_per_rsf_year=5000,
        )
        opt = ws["option"]
        payload = create_comparable_assessment_payload(
            opt["version"], comparable_rents_cents=[5000, 5001, 5002, 5003])
        resp = api.create_assessment(ws["pid"], ws["lid"], ws["oid"], payload,
                                     ws["am_headers"])
        assessment = validate_success(resp, 201)
        assert_assessment(assessment)
        # mean of [5000,5001,5002,5003] = 5001.5 → round half up → 5002
        assert assessment["provisional_rent_cents"] == 5002
        assert assessment["method"] == "COMPARABLE_AVERAGE"
        assert assessment["status"] == "PROVISIONAL"

    def test_psf_regression_variant_diverges_from_comparable_average(self, api):
        """PRD §3.6: "With `PSF_REGRESSION`, the payload instead carries a
        positive `regression_base_cents` plus `regression_adjustments`, a
        possibly empty list of signed cent adjustments such as floor premiums or
        TI amortization; the provisional rent is the base plus the sum of the
        adjustments, floored at one cent so it can never come out zero or
        negative, with no mean and no rounding step."
        PRD §3.6: "Submitting a fresh assessment while an earlier one is still
        `PROVISIONAL` moves the earlier row to `SUPERSEDED`"

        Design: Difficulty/dual_variant_calc/fmr_comparable_average_vs_psf_regression_diverge
        """
        ws = setup_option_on_active_lease(
            name="P1b", region="WEST",
            option_overrides={
                "option_type": "RENEWAL",
                "notice_window_open_date": "2026-09-01T00:00:00Z",
                "notice_window_close_date": "2027-06-30T00:00:00Z",
                "target_commencement_date": "2028-01-01T00:00:00Z",
                "extension_years": 5,
                "rate_determination": "FAIR_MARKET",
            },
            rentable_square_feet=10000,
            base_rent_cents_per_rsf_year=5000,
        )
        opt = ws["option"]
        # First: COMPARABLE_AVERAGE — mean of [5000,5001,5002,5003] = 5002.
        a1 = validate_success(api.create_assessment(
            ws["pid"], ws["lid"], ws["oid"],
            create_comparable_assessment_payload(
                opt["version"], comparable_rents_cents=[5000, 5001, 5002, 5003]),
            ws["am_headers"]), 201)  # PRD §4: creating an assessment answers 201
        # Refresh option version after the supersede bumped it.
        opt_now = get_success_data(api.get_option(ws["pid"], ws["lid"], ws["oid"],
                                                  ws["am_headers"]))
        # Second: PSF_REGRESSION with base 4800 and adjustments [150,-75,300] → 5175.
        a2 = validate_success(api.create_assessment(
            ws["pid"], ws["lid"], ws["oid"],
            create_regression_assessment_payload(
                opt_now["version"],
                regression_base_cents=4800,
                regression_adjustments=[150, -75, 300]),
            ws["am_headers"]), 201)  # PRD §4: creating an assessment answers 201
        assert a2["provisional_rent_cents"] == 5175, (
            "PSF_REGRESSION: 4800 + (150 - 75 + 300) = 5175"
        )
        assert a2["method"] == "PSF_REGRESSION"
        assert a2["status"] == "PROVISIONAL"

        # The earlier provisional row was superseded by the fresh submission.
        a1_now = validate_success(api.get_assessment(
            ws["pid"], ws["lid"], ws["oid"], a1["id"], ws["am_headers"]))
        assert a1_now["status"] == "SUPERSEDED"
        # Two valid methods produced two different provisional rents on the same
        # subject option.
        assert a1_now["provisional_rent_cents"] != a2["provisional_rent_cents"]


class TestComparableAverageRounding:
    def test_comparable_average_rounding_half_up(self, api):
        """PRD §3.6: "the provisional rent is their arithmetic mean, rounded
        half up to a whole cent"

        Design: Corner/calculations/comparable_average_rounding_half_up
        """
        ws = setup_option_on_active_lease(
            name="C1", region="WEST",
            option_overrides={
                "option_type": "RENEWAL",
                "notice_window_open_date": "2026-08-01T00:00:00Z",
                "notice_window_close_date": "2026-12-31T00:00:00Z",
                "target_commencement_date": "2028-01-01T00:00:00Z",
                "extension_years": 5,
                "rate_determination": "FAIR_MARKET",
            })
        opt = ws["option"]
        # mean of [5000, 5001, 5003] = 5001.333... → round half up → 5001
        payload = create_comparable_assessment_payload(
            opt["version"], comparable_rents_cents=[5000, 5001, 5003])
        resp = api.create_assessment(ws["pid"], ws["lid"], ws["oid"], payload,
                                     ws["am_headers"])
        assessment = validate_success(resp, 201)
        assert assessment["provisional_rent_cents"] == 5001, (
            "mean 5001.333 rounds half-up to 5001 (not 5002)"
        )


class TestAssessmentShape:
    def test_assessment_shape_two_comparables_rejected(self, api):
        """PRD §3.6: "With `COMPARABLE_AVERAGE`, the payload carries
        `comparable_rents_cents` — three to seven comparable annual rents ...
        any shape violation is rejected with `ERR_ASSESSMENT_SHAPE`."

        Design: Corner/validations/assessment_shape_two_comparables_rejected
        """
        ws = setup_option_on_active_lease(
            name="V3", region="WEST",
            option_overrides={
                "option_type": "RENEWAL",
                "notice_window_open_date": "2026-08-01T00:00:00Z",
                "notice_window_close_date": "2026-12-31T00:00:00Z",
                "target_commencement_date": "2028-01-01T00:00:00Z",
                "extension_years": 5,
                "rate_determination": "FAIR_MARKET",
            })
        opt = ws["option"]
        payload = create_comparable_assessment_payload(
            opt["version"], comparable_rents_cents=[5000, 5100])  # only 2
        resp = api.create_assessment(ws["pid"], ws["lid"], ws["oid"], payload,
                                     ws["am_headers"])
        validate_error(resp, ApiErrorId.ERR_ASSESSMENT_SHAPE)


class TestDisputeWindow:
    def test_dispute_window_exactly_15_days_allowed(self, api):
        """PRD §3.6: "Disagreement becomes a formal dispute when the
        `AssetManager` files while the option is `NOTICE_SENT` or
        `IN_ARBITRATION` ... and while the clock date is on or before the
        assessment's creation date plus fifteen calendar days"
        PRD §3.6: "it creates an `ArbitrationCase` in `OPEN` whose
        `assessment_id` points at the disputed assessment and whose
        `submission_close_date` is server-stamped thirty calendar days after
        case creation"

        Design: Corner/calculations/dispute_window_exactly_15_days_allowed
        """
        ws = setup_notice_sent(
            name="C3", region="WEST",
            option_overrides={
                "option_type": "RENEWAL",
                "notice_window_open_date": "2026-08-01T00:00:00Z",
                "notice_window_close_date": "2026-12-31T00:00:00Z",
                "target_commencement_date": "2028-01-01T00:00:00Z",
                "extension_years": 5,
                "rate_determination": "FAIR_MARKET",
            },
            clock="2026-08-15T00:00:00Z")
        opt = get_success_data(api.get_option(ws["pid"], ws["lid"], ws["oid"],
                                              ws["am_headers"]))
        mid = get_success_data(api.create_assessment(
            ws["pid"], ws["lid"], ws["oid"],
            create_comparable_assessment_payload(
                opt["version"], comparable_rents_cents=[5001, 5002, 5003]),
            ws["am_headers"]))["id"]
        # Dispute filed at exactly creation + 15 days (inclusive bound).
        set_clock("2026-08-30T23:59:59Z")
        resp = api.dispute_assessment(
            ws["pid"], ws["lid"], ws["oid"], mid,
            create_dispute_payload(landlord_rent_cents=6000, tenant_rent_cents=5000),
            ws["am_headers"])
        arb = validate_success(resp, 201)
        assert_arbitration_case(arb)
        assert arb["status"] == "OPEN"
        # 2026-08-30 + 30 days = 2026-09-29
        assert arb["submission_close_date"].startswith("2026-09-29"), (
            "submission_close_date is stamped 30 calendar days after case creation"
        )

    def test_err_dispute_window_closed_at_plus_16_days(self, api):
        """PRD §3.6: "a later filing rejected as `ERR_DISPUTE_WINDOW_CLOSED`"

        Design: Corner/errors/err_dispute_window_closed_at_plus_16_days
        """
        ws = setup_notice_sent(
            name="X4", region="WEST",
            option_overrides={
                "option_type": "RENEWAL",
                "notice_window_open_date": "2026-08-01T00:00:00Z",
                "notice_window_close_date": "2026-12-31T00:00:00Z",
                "target_commencement_date": "2028-01-01T00:00:00Z",
                "extension_years": 5,
                "rate_determination": "FAIR_MARKET",
            },
            clock="2026-08-15T00:00:00Z")
        opt = get_success_data(api.get_option(ws["pid"], ws["lid"], ws["oid"],
                                              ws["am_headers"]))
        mid = get_success_data(api.create_assessment(
            ws["pid"], ws["lid"], ws["oid"],
            create_comparable_assessment_payload(
                opt["version"], comparable_rents_cents=[5001, 5002, 5003]),
            ws["am_headers"]))["id"]
        # Dispute filed at creation + 16 days — past the window.
        set_clock("2026-08-31T00:00:00Z")
        resp = api.dispute_assessment(
            ws["pid"], ws["lid"], ws["oid"], mid,
            create_dispute_payload(landlord_rent_cents=6000, tenant_rent_cents=5000),
            ws["am_headers"])
        validate_error(resp, ApiErrorId.ERR_DISPUTE_WINDOW_CLOSED)


class TestArbitrationAward:
    def _setup_disputed_assessment(self, api, name):
        """Common setup: dispute filed, option now IN_ARBITRATION."""
        ws = setup_notice_sent(
            name=name, region="WEST", with_lc=True, with_bk=True,
            option_overrides={
                "option_type": "RENEWAL",
                "notice_window_open_date": "2026-08-01T00:00:00Z",
                "notice_window_close_date": "2027-06-30T00:00:00Z",
                "target_commencement_date": "2028-01-01T00:00:00Z",
                "extension_years": 5,
                "rate_determination": "FAIR_MARKET",
            },
            clock="2026-08-15T00:00:00Z",
            rentable_square_feet=12000,
            base_rent_cents_per_rsf_year=5000)
        opt = get_success_data(api.get_option(ws["pid"], ws["lid"], ws["oid"],
                                              ws["am_headers"]))
        mid = get_success_data(api.create_assessment(
            ws["pid"], ws["lid"], ws["oid"],
            create_comparable_assessment_payload(
                opt["version"], comparable_rents_cents=[5001, 5002, 5003]),
            ws["am_headers"]))["id"]
        arb = get_success_data(api.dispute_assessment(
            ws["pid"], ws["lid"], ws["oid"], mid,
            create_dispute_payload(landlord_rent_cents=6000, tenant_rent_cents=5000),
            ws["am_headers"]))
        ws["mid"] = mid
        ws["arb"] = arb
        return ws

    def test_arbitration_tie_breaks_to_lower_submission(self, api):
        """PRD §3.6: "the `award_rent_cents` is whichever of the two submissions
        — `landlord_rent_cents` or `tenant_rent_cents` — lies nearest the
        guidance rent, and an exact tie resolves to the lower of the two
        submissions."

        Design: Difficulty/combinatorial_formula/arbitration_award_tiebreak_and_assessment_resolution_cycle
        """
        ws = self._setup_disputed_assessment(api, "P4")
        # Guidance 5500 is exactly midway between landlord 6000 and tenant 5000.
        resp = api.decide_arbitration(
            ws["pid"], ws["lid"], ws["oid"], ws["mid"],
            create_decision_payload(panel_guidance_rent_cents=5500),
            ws["lc_headers"])
        arb = validate_success(resp, 200)
        assert arb["status"] == "DECIDED"
        assert arb["award_rent_cents"] == 5000, (
            "Exact midpoint tie → the lower submission (tenant 5000) wins"
        )

    def test_arbitration_cascades_assessment_final_and_option_return(self, api):
        """PRD §3.6: "Deciding moves the case to `DECIDED` and cascades two
        hops. The assessment moves `DISPUTED` → `FINAL` with
        `determined_rent_cents` set to the award ... The option then returns
        `IN_ARBITRATION` → `NOTICE_SENT`, taking its determined rent from the
        now-final assessment"

        Design: Difficulty/combinatorial_formula/arbitration_award_tiebreak_and_assessment_resolution_cycle
        """
        ws = self._setup_disputed_assessment(api, "P4b")
        # Guidance 5500 ties; award → 5000.
        get_success_data(api.decide_arbitration(
            ws["pid"], ws["lid"], ws["oid"], ws["mid"],
            create_decision_payload(panel_guidance_rent_cents=5500),
            ws["lc_headers"]))
        assessment = validate_success(api.get_assessment(
            ws["pid"], ws["lid"], ws["oid"], ws["mid"], ws["am_headers"]))
        assert assessment["status"] == "FINAL"
        assert assessment["determined_rent_cents"] == 5000, (
            "The FINAL assessment adopts the award (not the 5002 provisional)"
        )
        opt = validate_success(api.get_option(ws["pid"], ws["lid"], ws["oid"],
                                              ws["am_headers"]))
        assert opt["status"] == "NOTICE_SENT", (
            "Option returns from IN_ARBITRATION to NOTICE_SENT"
        )


class TestArbitrationCycle:
    def test_option_in_arbitration_suspends_notice_path(self, api):
        """PRD §3.6: "it pushes the parent option `NOTICE_SENT` →
        `IN_ARBITRATION`. While the option sits in arbitration, notice-window
        lapse is suspended and its `PENDING` reminders remain pending but do
        not fire."

        Design: Difficulty/non_linear_state_machine/option_in_arbitration_cycle_suspends_and_resumes_notice_path
        """
        ws = setup_notice_sent(
            name="P6a", region="EAST", with_bk=True, with_lc=True,
            option_overrides={
                "option_type": "RENEWAL",
                "notice_window_open_date": "2026-08-01T00:00:00Z",
                "notice_window_close_date": "2027-06-30T00:00:00Z",
                "target_commencement_date": "2028-01-01T00:00:00Z",
                "extension_years": 5,
                "rate_determination": "FAIR_MARKET",
            },
            clock="2026-08-15T00:00:00Z",
            rentable_square_feet=12000)
        opt = get_success_data(api.get_option(ws["pid"], ws["lid"], ws["oid"],
                                              ws["am_headers"]))
        mid = get_success_data(api.create_assessment(
            ws["pid"], ws["lid"], ws["oid"],
            create_comparable_assessment_payload(
                opt["version"], comparable_rents_cents=[5001, 5002, 5003]),
            ws["am_headers"]))["id"]
        get_success_data(api.dispute_assessment(
            ws["pid"], ws["lid"], ws["oid"], mid,
            create_dispute_payload(landlord_rent_cents=6000, tenant_rent_cents=5000),
            ws["am_headers"]))
        opt_after = validate_success(api.get_option(
            ws["pid"], ws["lid"], ws["oid"], ws["am_headers"]))
        assert opt_after["status"] == "IN_ARBITRATION", (
            "Dispute pushes the option into IN_ARBITRATION"
        )

    def test_arbitration_resume_completes_exercise_with_award(self, api):
        """PRD §3.6: "The option then returns `IN_ARBITRATION` → `NOTICE_SENT`,
        taking its determined rent from the now-final assessment"
        PRD §3.5: "a `FAIR_MARKET` option requires a market-rate assessment in
        `FINAL`, whether finalized unchallenged or decided by arbitration"
        PRD §3.5: "fixes `determined_rent_cents_per_rsf_year`, with a `FIXED`
        option copying its `fixed_rent_cents_per_rsf_year` and a `FAIR_MARKET`
        option copying the `FINAL` assessment's `determined_rent_cents`"

        Design: Difficulty/non_linear_state_machine/option_in_arbitration_cycle_suspends_and_resumes_notice_path
        """
        ws = setup_notice_sent(
            name="P6b", region="EAST", with_bk=True, with_lc=True,
            option_overrides={
                "option_type": "RENEWAL",
                "notice_window_open_date": "2026-08-01T00:00:00Z",
                "notice_window_close_date": "2027-06-30T00:00:00Z",
                "target_commencement_date": "2028-01-01T00:00:00Z",
                "extension_years": 5,
                "rate_determination": "FAIR_MARKET",
            },
            clock="2026-08-15T00:00:00Z",
            rentable_square_feet=12000)
        opt = get_success_data(api.get_option(ws["pid"], ws["lid"], ws["oid"],
                                              ws["am_headers"]))
        mid = get_success_data(api.create_assessment(
            ws["pid"], ws["lid"], ws["oid"],
            create_comparable_assessment_payload(
                opt["version"], comparable_rents_cents=[5001, 5002, 5003]),
            ws["am_headers"]))["id"]
        get_success_data(api.dispute_assessment(
            ws["pid"], ws["lid"], ws["oid"], mid,
            create_dispute_payload(landlord_rent_cents=6000, tenant_rent_cents=5000),
            ws["am_headers"]))
        # Guidance 5300: |6000-5300|=700, |5000-5300|=300 → award 5000.
        get_success_data(api.decide_arbitration(
            ws["pid"], ws["lid"], ws["oid"], mid,
            create_decision_payload(panel_guidance_rent_cents=5300),
            ws["lc_headers"]))
        # After the case is DECIDED, the option returns to NOTICE_SENT.
        # Now deliver and acknowledge the notice to complete the exercise.
        get_success_data(api.deliver_notice(
            ws["pid"], ws["lid"], ws["oid"], ws["nid"], ws["bk_headers"]))
        get_success_data(api.acknowledge_notice(
            ws["pid"], ws["lid"], ws["oid"], ws["nid"], ws["lc_headers"]))
        opt = validate_success(api.get_option(ws["pid"], ws["lid"], ws["oid"],
                                              ws["am_headers"]))
        assert opt["status"] == "EXERCISED", (
            "NOTICE_SENT → IN_ARBITRATION → NOTICE_SENT → EXERCISED"
        )
        assert opt["determined_rent_cents_per_rsf_year"] == 5000, (
            "FAIR_MARKET copies the FINAL assessment's determined_rent_cents "
            "(arbitration award 5000), not the 5002 provisional"
        )
        notice = validate_success(api.get_notice(
            ws["pid"], ws["lid"], ws["oid"], ws["nid"], ws["am_headers"]))
        assert notice["status"] == "ACKNOWLEDGED"
