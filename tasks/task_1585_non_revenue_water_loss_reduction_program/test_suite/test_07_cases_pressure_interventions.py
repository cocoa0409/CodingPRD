"""Unauthorized-consumption cases (parallel state dimensions), pressure
projects (activation timing, target validation, FAVAD reduction), and
intervention proposal economics (dual-variant BCR, pinned evaluation order,
approval gate) — PRD §3.6, §3.7, §3.8."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_DEFAULTS,
    assert_intervention_proposal,
    assert_pressure_project,
    assert_unauthorized_consumption_case,
    create_active_pressure_project,
    create_approved_pressure_project,
    create_case_with_proposed_adjustment,
    create_dma,
    create_intervention_proposal,
    create_submitted_proposal,
    get_dma,
    make_investigator_headers,
    make_program_director_headers,
    make_utility_analyst_headers,
    setup_dma_with_finalized_balance,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

PD = TEST_DEFAULTS["PROGRAM_DIRECTOR"]
UA = TEST_DEFAULTS["UTILITY_ANALYST"]
INV = TEST_DEFAULTS["INVESTIGATOR"]


class TestCaseParallelDimensions:
    def _setup_proposed_case(self):
        dma = create_dma(code="DMA-NL2", connection_count=800,
                         mains_length_km=20.0, target_nrw_pct=12.0)
        case = create_case_with_proposed_adjustment(
            dma["id"], estimated_loss_m3=1200, proposed_adjustment_amount=5000,
            service_location_ref="LOC-77",
        )
        return dma, case

    def test_close_rejected_while_adjustment_proposed(self, api):
        """PRD §3.6: "Case closure depends on both dimensions. An `UNFOUNDED`
        case closes only while its billing dimension is still `NONE`. A
        `SUBSTANTIATED` case closes only when its billing dimension rests at
        `NONE`, `REJECTED`, or `POSTED` — a case with an adjustment still
        `PROPOSED` or `APPROVED` cannot be closed."
        PRD §2.7: "State-machine validity — the target entity is in a from-state
        that permits the invoked transition, and terminal states reject every
        transition; failure yields `ERR_INVALID_STATE` (HTTP 409)."

        Design: Difficulty/non_linear_state_machine/unauthorized_case_parallel_dimensions
        """
        dma, case = self._setup_proposed_case()
        assert case["investigation_status"] == "SUBSTANTIATED"
        assert case["billing_adjustment_status"] == "PROPOSED"

        res = api.close_case(case["id"], make_investigator_headers(INV))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

        reread = validate_success(
            api.get_unauthorized_consumption_case(
                case["id"], make_investigator_headers(INV)
            ),
            200,
        )
        assert reread["investigation_status"] == "SUBSTANTIATED"
        assert reread["billing_adjustment_status"] == "PROPOSED"

    def test_approve_post_then_close_leaves_billing_posted(self, api):
        """PRD §3.6: "Posting, performed by an `Investigator`, moves an
        `APPROVED` adjustment to `POSTED` and stamps the
        `posted_adjustment_amount` equal to the `proposed_adjustment_amount`;
        before posting, and on any non-posted case, `posted_adjustment_amount`
        remains null." and "`CLOSED` is terminal for the investigation
        dimension."

        Design: Difficulty/non_linear_state_machine/unauthorized_case_parallel_dimensions
        """
        dma, case = self._setup_proposed_case()

        approved = validate_success(
            api.approve_adjustment(
                case["id"], make_program_director_headers(PD)
            ),
            200,
        )
        assert approved["billing_adjustment_status"] == "APPROVED"
        assert approved["posted_adjustment_amount"] is None

        posted = validate_success(
            api.post_adjustment(case["id"], make_investigator_headers(INV)), 200
        )
        assert posted["billing_adjustment_status"] == "POSTED"
        assert posted["posted_adjustment_amount"] == pytest.approx(5000, abs=0.01)

        closed = validate_success(
            api.close_case(case["id"], make_investigator_headers(INV)), 200
        )
        assert_unauthorized_consumption_case(closed)
        assert closed["investigation_status"] == "CLOSED"
        assert closed["billing_adjustment_status"] == "POSTED"


class TestAdjustmentSegregation:
    def test_substantiator_cannot_approve_own_adjustment(self, api):
        """PRD §3.6: "approval moves billing from `PROPOSED` to `APPROVED` and
        enforces §2.11 — the director's `X-User-ID` must differ from
        `substantiated_by_user_id`, with violations rejected as
        `ERR_SEGREGATION_OF_DUTIES` — while rejection moves it from `PROPOSED`
        to `REJECTED`."

        Design: Difficulty/priority_pair_validation_conflict/segregation_error_beats_bcr_fiscal_gate
        """
        dma = create_dma(code="DMA-PP2", connection_count=800,
                         mains_length_km=20.0, target_nrw_pct=12.0)
        case = create_case_with_proposed_adjustment(
            dma["id"], estimated_loss_m3=500, proposed_adjustment_amount=5000,
            service_location_ref="LOC-88",
        )
        assert case["substantiated_by_user_id"] == INV

        # The substantiating user attempts approval in the director role.
        res = api.approve_adjustment(
            case["id"], make_program_director_headers(INV)
        )
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
                       expected_status=403)

        reread = validate_success(
            api.get_unauthorized_consumption_case(
                case["id"], make_investigator_headers(INV)
            ),
            200,
        )
        assert reread["billing_adjustment_status"] == "PROPOSED"


class TestPressureProjectLifecycle:
    def test_activate_before_planned_start_rejected_then_succeeds_after_clock(
        self, api, program_director_headers
    ):
        """PRD §3.7: "Activation moves an `APPROVED` project to `ACTIVE` once
        the logical clock has reached its `planned_start`, and — because active
        field work constrains the district — recomputes the DMA's posture,
        moving an `OPEN` district to `RESTRICTED`."
        PRD §2.5: "Before any client call has set it, the logical clock reads
        exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock
        time."

        Design: Corner/state_machines/pressure_project_activate_before_planned_start_rejected
        """
        dma = create_dma(code="DMA-SM5", connection_count=1000,
                         mains_length_km=30.0, target_nrw_pct=15.0)
        project = create_approved_pressure_project(
            dma["id"], name="PRV SM5",
            planned_start="2026-09-01T00:00:00Z",
            planned_end="2026-10-01T00:00:00Z",
        )
        assert project["status"] == "APPROVED"

        # Clock still reads 2026-08-01, earlier than planned_start 2026-09-01.
        early = api.activate_pressure_project(
            project["id"], program_director_headers
        )
        validate_error_is_one_of(
            early,
            [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_VALIDATION],
        )
        reread = validate_success(
            api.get_pressure_project(project["id"], program_director_headers), 200
        )
        assert reread["status"] == "APPROVED"

        validate_success(
            api.set_current_utc({"to_iso8601": "2026-09-01T00:00:00Z"},
                                program_director_headers),
            200,
        )
        active = validate_success(
            api.activate_pressure_project(project["id"], program_director_headers),
            200,
        )
        assert active["status"] == "ACTIVE"
        assert get_dma(dma["id"])["posture"] == "RESTRICTED"

    def test_target_at_baseline_rejected(self, api):
        """PRD §3.7: "the `target_pressure_m` after intervention (strictly
        greater than zero and strictly below the baseline; a target at or above
        the baseline is rejected with `ERR_VALIDATION`)"

        Design: Corner/validations/pressure_target_must_be_below_baseline
        """
        dma = create_dma(code="DMA-VAL2", connection_count=1000,
                         mains_length_km=30.0, target_nrw_pct=15.0)
        res = api.create_pressure_project(
            {
                "dma_id": dma["id"],
                "name": "PRV VAL2",
                "planned_start": "2026-08-01T00:00:00Z",
                "planned_end": "2026-09-01T00:00:00Z",
                "baseline_pressure_m": 60.0,
                "target_pressure_m": 60.0,
            },
            make_utility_analyst_headers(UA),
        )
        validate_error(res, ApiErrorId.ERR_VALIDATION, expected_status=422)

    def test_commission_computes_favad_reduction(self, api,
                                                 program_director_headers):
        """PRD §3.7: "The `pressure_reduction_pct` is the baseline minus the
        measured pressure, divided by the baseline, multiplied by 100, rounded
        half-up to 2 decimal places. The `estimated_leak_reduction_m3_per_year`
        applies the fixed-and-variable-area-discharge exponent: when a latest
        finalized, non-superseded balance period exists for the DMA (selected by
        latest `period_end`, ties broken by earliest `created_at`), the period's
        `real_loss_m3` is first annualized — multiplied by 365 divided by that
        period's length in days — and the reduction estimate is that annualized
        loss multiplied by one minus the ratio of measured to baseline pressure
        raised to the 1.15 power, rounded half-up to a whole cubic metre"

        Design: Corner/calculations/pressure_leak_reduction_uses_favad_exponent
        """
        dma, _ = setup_dma_with_finalized_balance(code="DMA-CALC2")
        project = create_active_pressure_project(
            dma["id"], name="PRV CALC2",
            planned_start="2026-08-01T00:00:00Z",
            planned_end="2026-09-01T00:00:00Z",
            baseline_pressure_m=60.0,
            target_pressure_m=42.0,
        )
        commissioned = validate_success(
            api.commission_pressure_project(
                project["id"], {"measured_pressure_m": 42.0},
                program_director_headers,
            ),
            200,
        )
        assert_pressure_project(commissioned)
        assert commissioned["status"] == "COMMISSIONED"
        assert commissioned["pressure_reduction_pct"] == pytest.approx(30.0, abs=0.01)
        # annualized real loss = 200000 * 365 / 90 = 811111.11;
        # 811111.11 * (1 - (42/60) ** 1.15) = 272912.2 -> 272912
        assert commissioned["estimated_leak_reduction_m3_per_year"] == pytest.approx(
            272912, abs=1.0
        )


class TestInterventionBenefitCost:
    def test_provisional_ratio_at_draft_and_submit(self, api,
                                                   utility_analyst_headers):
        """PRD §3.8: "while a proposal is `DRAFT` or `SUBMITTED`, the
        **provisional** variant uses a screening-grade 7 percent; once approved,
        the **bankable** variant uses an investment-grade 4 percent, so
        identical inputs always yield a strictly higher ratio once bankable."
        and "The `benefit_cost_ratio` is the present value of benefits divided
        by the larger of the present value of costs and a cost floor of 1.0,
        rounded half-up to 2 decimal places."

        Design: Difficulty/dual_variant_calc/intervention_bcr_provisional_vs_bankable
        """
        dma = create_dma(code="DMA-DV2", connection_count=3000,
                         mains_length_km=80.0, target_nrw_pct=18.0)
        proposal = create_intervention_proposal(
            dma["id"], kind="LEAK_REPAIR_PROGRAM", capital_cost=1271281.68,
            annual_om_cost=10000, expected_volume_saved_m3_per_year=100000,
        )
        assert_intervention_proposal(proposal)
        assert proposal["status"] == "DRAFT"
        # MID tier: 100000 * 1.30 = 130000 gross; pv_factor(7%, 20y, 6dp)
        # = 10.594014; pv_benefit = 1377221.82; pv_cost = 1271281.68 +
        # 105940.14 = 1377221.82; ratio = 1.00
        assert proposal["benefit_cost_ratio"] == pytest.approx(1.0, abs=0.005)

        submitted = validate_success(
            api.submit_intervention_proposal(proposal["id"],
                                             utility_analyst_headers),
            200,
        )
        assert submitted["status"] == "SUBMITTED"
        assert submitted["benefit_cost_ratio"] == pytest.approx(1.0, abs=0.005)

    def test_approve_recomputes_bankable_ratio(self, api,
                                               program_director_headers,
                                               utility_analyst_headers):
        """PRD §3.8: "once approved, the **bankable** variant uses an
        investment-grade 4 percent, so identical inputs always yield a strictly
        higher ratio once bankable." and "The `payback_years` is the simple
        payback: the annual net benefit is the annual gross benefit minus the
        `annual_om_cost`, and when that net benefit is zero or negative the
        payback is null; otherwise it is the `capital_cost` divided by the
        annual net benefit, rounded half-up to 1 decimal place."

        Design: Difficulty/dual_variant_calc/intervention_bcr_provisional_vs_bankable
        """
        dma = create_dma(code="DMA-DV2B", connection_count=3000,
                         mains_length_km=80.0, target_nrw_pct=18.0)
        proposal = create_submitted_proposal(
            dma["id"], kind="LEAK_REPAIR_PROGRAM", capital_cost=1271281.68,
            annual_om_cost=10000, expected_volume_saved_m3_per_year=100000,
        )
        approved = validate_success(
            api.approve_intervention_proposal(proposal["id"],
                                              program_director_headers),
            200,
        )
        assert approved["status"] == "APPROVED"
        # pv_factor(4%, 20y, 6dp) = 13.590326; pv_benefit = 1766742.38;
        # pv_cost = 1407184.94; ratio = 1.26
        assert approved["benefit_cost_ratio"] == pytest.approx(1.26, abs=0.005)
        # payback = 1271281.68 / (130000 - 10000) = 10.594 -> 10.6
        assert approved["payback_years"] == pytest.approx(10.6, abs=0.05)

    def test_pinned_evaluation_order_high_tier(self, api):
        """PRD §3.8: "The benefit–cost rule evaluates in a pinned order: gross
        benefit first, then discounting, then costs, then the ratio. The annual
        gross benefit is the expected annual volume saved multiplied by a
        marginal water value that depends on which volume tier the saving falls
        into: below 50,000 cubic metres per year the value is 1.10 per cubic
        metre; from 50,000 up to but excluding 200,000 the value is 1.30; at
        200,000 and above the value is 1.55 — tier boundaries are inclusive at
        the lower edge."

        Design: Difficulty/combinatorial_formula/intervention_bcr_pinned_evaluation_order
        """
        dma = create_dma(code="DMA-CF2", connection_count=2000,
                         mains_length_km=50.0, target_nrw_pct=15.0)
        proposal = create_intervention_proposal(
            dma["id"], kind="PRESSURE_MANAGEMENT", capital_cost=900000,
            annual_om_cost=20000, expected_volume_saved_m3_per_year=300000,
        )
        # HIGH tier: 300000 * 1.55 = 465000; pv_factor = 10.594014;
        # pv_benefit = 4926216.51; pv_cost = 900000 + 211880.28 = 1111880.28;
        # ratio = 4.43
        assert proposal["benefit_cost_ratio"] == pytest.approx(4.43, abs=0.005)

    def test_pinned_evaluation_order_payback(self, api):
        """PRD §3.8: "The `payback_years` is the simple payback: the annual net
        benefit is the annual gross benefit minus the `annual_om_cost`, and when
        that net benefit is zero or negative the payback is null; otherwise it
        is the `capital_cost` divided by the annual net benefit, rounded half-up
        to 1 decimal place."

        Design: Difficulty/combinatorial_formula/intervention_bcr_pinned_evaluation_order
        """
        dma = create_dma(code="DMA-CF2B", connection_count=2000,
                         mains_length_km=50.0, target_nrw_pct=15.0)
        proposal = create_intervention_proposal(
            dma["id"], kind="PRESSURE_MANAGEMENT", capital_cost=900000,
            annual_om_cost=20000, expected_volume_saved_m3_per_year=300000,
        )
        # net benefit = 465000 - 20000 = 445000; payback = 900000 / 445000
        #             = 2.022 -> 2.0
        assert proposal["payback_years"] == pytest.approx(2.0, abs=0.05)

    def test_below_threshold_approve_rejected(self, api,
                                              program_director_headers):
        """PRD §3.8: "Approval moves the proposal from `SUBMITTED` to `APPROVED`
        and enforces the program's investment gate: the benefit–cost ratio as
        last computed at submission must be at least 1.00 — the boundary is
        inclusive — or the approval is rejected with `ERR_BCR_BELOW_THRESHOLD`
        (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/segregation_error_beats_bcr_fiscal_gate
        """
        dma = create_dma(code="DMA-PP2B", connection_count=900,
                         mains_length_km=25.0, target_nrw_pct=12.0)
        proposal = create_submitted_proposal(
            dma["id"], kind="METER_REPLACEMENT_PROGRAM", capital_cost=900000,
            annual_om_cost=25000, expected_volume_saved_m3_per_year=60000,
        )
        # MID tier: 60000 * 1.30 = 78000; pv_benefit = 826333.09;
        # pv_cost = 900000 + 264850.35 = 1164850.35; ratio = 0.71
        assert proposal["benefit_cost_ratio"] == pytest.approx(0.71, abs=0.005)

        res = api.approve_intervention_proposal(proposal["id"],
                                                program_director_headers)
        validate_error(res, ApiErrorId.ERR_BCR_BELOW_THRESHOLD,
                       expected_status=422)

        reread = validate_success(
            api.get_intervention_proposal(proposal["id"],
                                          program_director_headers),
            200,
        )
        assert reread["status"] == "SUBMITTED"
