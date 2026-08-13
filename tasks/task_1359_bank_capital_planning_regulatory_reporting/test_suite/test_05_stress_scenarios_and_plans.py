"""Stress scenarios and capital plans: activation caps, retire-in-use,
projection formulas, single-in-flight invariant, and the objection loop."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_bank,
    create_period,
    add_exposure,
    add_instrument,
    create_active_scenario,
    create_draft_plan,
    create_payment_period,
    create_prepared_call_report,
    create_proposed_distribution,
    create_stress_scenario_payload,
    advance_clock_past,
    setup_accepted_report,
    setup_accepted_report_with_live_scenario,
    setup_plan_approved,
    setup_plan_in_board_review,
    setup_plan_in_supervisory_review,
    set_clock,
    make_capital_analyst_headers,
    make_board_approver_headers,
    PREPARER_USER_ID,
    SEVERE_SCENARIO,
)


class TestStressScenarioCaps(object):
    def test_error_scenario_limit(self, api, system_operator_headers, capital_analyst_headers):
        """PRD §3.5: "A bank may hold at most two scenarios in ACTIVE at once
        — activating a third is rejected with ERR_SCENARIO_LIMIT (HTTP 409)."

        Design: Corner/errors/error_scenario_limit
        """
        bank = create_bank("CH-SCN-001", legal_name="ScenBank")
        period = create_period(bank["id"], "2026-06-30", 2026, "Q2")
        add_exposure(bank["id"], period["id"], exposure_at_default_cents=1_000_000)
        s1 = create_active_scenario(
            bank["id"], "S1", gdp_shock_bps=-100, unemployment_peak_bps=600,
            hpi_shock_bps=-500, cre_price_shock_bps=-500, market_shock_bps=-1000,
        )
        s2 = create_active_scenario(
            bank["id"], "S2", gdp_shock_bps=-200, unemployment_peak_bps=800,
            hpi_shock_bps=-1000, cre_price_shock_bps=-1500, market_shock_bps=-2000,
        )
        s3 = get_success_data(
            api.create_stress_scenario(
                bank["id"],
                create_stress_scenario_payload(scenario_code="S3", **SEVERE_SCENARIO),
                capital_analyst_headers,
            )
        )
        res = api.activate_stress_scenario(bank["id"], s3["id"], capital_analyst_headers)
        validate_error(res, ApiErrorId.ERR_SCENARIO_LIMIT)

    def test_error_scenario_in_use_on_retire(self, api, system_operator_headers, capital_analyst_headers):
        """PRD §3.5: "A scenario may be retired only while no capital plan in
        BOARD_REVIEW, SUBMITTED, SUPERVISORY_REVIEW, or APPROVED references
        it; retiring an in-use scenario is rejected with ERR_SCENARIO_IN_USE
        (HTTP 409)."

        Design: Corner/errors/error_scenario_in_use_on_retire
        """
        bank, period, report, scenario, plan = setup_plan_in_board_review(
            "CH-IUS-001", 10_000_000_000, 100_000_000_000, scenario_code="IN-USE"
        )
        assert plan["status"] == "BOARD_REVIEW"
        res = api.retire_stress_scenario(bank["id"], scenario["id"], capital_analyst_headers)
        validate_error(res, ApiErrorId.ERR_SCENARIO_IN_USE)


class TestStressLossProjection(object):
    def test_stress_loss_projection_computed_on_activation(self, api, system_operator_headers, capital_analyst_headers):
        """PRD §3.5: "On activation the server computes the scenario's
        projected_pre_tax_loss_cents" and "A CORPORATE exposure loses 200
        basis points plus the absolute value of gdp_shock_bps multiplied by 30
        and divided by 1000."

        Design: Difficulty/combinatorial_formula/stress_capital_buffer_mode_a_nested_min_max
        """
        bank = create_bank("CH-STR-001", legal_name="StressBank")
        period = create_period(bank["id"], "2026-06-30", 2026, "Q2")
        add_exposure(
            bank["id"], period["id"],
            exposure_class="CORPORATE", exposure_at_default_cents=100_000_000_000,
            risk_weight_bps=10000, obligor_grade="INVESTMENT_GRADE", collateral_haircut_bps=0,
        )
        # Period is still OPEN/FILING_DUE, so the exposure is inside the
        # activation-time inventory.
        scenario = create_active_scenario(bank["id"], "SEVERE-2026", **SEVERE_SCENARIO)
        # CORPORATE base_loss_bps = 200 + (300 * 30) / 1000 = 209 bps;
        # loss = floor(100e9 * 209 / 10000 * 1) = 2_090_000_000.
        assert scenario["projected_pre_tax_loss_cents"] == 2_090_000_000, (
            f"projected_pre_tax_loss_cents: expected 2090000000, "
            f"got {scenario['projected_pre_tax_loss_cents']}"
        )

    def test_stressed_min_cet1_lands_at_q9(self, api, system_operator_headers, capital_analyst_headers,
                                           regulator_reviewer_headers):
        """PRD §3.5: "the projected_pre_tax_loss_cents is distributed across
        nine quarters by a fixed weighting profile that sums to exactly 10000
        basis points — 800 in the first quarter, then 1000, 1200, 1400, 1300,
        1200, 1100, 1100, and 900. Cumulative pre-tax losses are reduced by a
        21 percent tax offset ... Each quarter's stressed CET1 ratio is the
        baseline CET1 minus cumulative after-tax losses and cumulative
        distributions, scaled by 10000, divided by baseline RWA grown by half
        a percent for each quarter elapsed (50 basis points per quarter, so
        the third quarter divides by baseline RWA times 10150 over 10000),
        floored to integer basis points; the minimum across the nine quarters
        is stressed_min_cet1_bps_9q."

        Design: Difficulty/combinatorial_formula/stress_capital_buffer_mode_a_nested_min_max
        """
        # Scenario activates while the period is still open so the severe
        # loss is in the inventory; the report is then accepted and seeds the
        # plan baseline.
        bank, period, report, scenario = setup_accepted_report_with_live_scenario(
            "CH-STR-002", 10_000_000_000, 100_000_000_000, "SEVERE-2026",
            scenario_overrides=SEVERE_SCENARIO,
        )
        assert scenario["projected_pre_tax_loss_cents"] == 2_090_000_000
        plan = create_draft_plan(bank["id"], period["id"], scenario["id"])
        plan = validate_success(
            api.submit_plan_board(
                bank["id"], plan["id"], make_capital_analyst_headers(PREPARER_USER_ID)
            )
        )
        assert plan["baseline_cet1_cents"] == 10_000_000_000
        assert plan["baseline_rwa_cents"] == 100_000_000_000
        # Q9 is the minimum: cumulative pre-tax 2_090_000_000, after-tax
        # floor(2_090_000_000 * 7900 / 10000) = 1_651_100_000; numerator
        # 10e9 - 1_651_100_000 = 8_348_900_000; denominator
        # 100e9 * (10000 + 450)/10000 = 104_500_000_000; ratio floors to 798.
        assert plan["stressed_min_cet1_bps_9q"] == 798, (
            f"stressed_min_cet1_bps_9q: expected 798, got {plan['stressed_min_cet1_bps_9q']}"
        )

    def test_stress_loss_projection_input_set_filtering(self, api, system_operator_headers,
                                                        capital_analyst_headers, regulator_reviewer_headers):
        """PRD §3.5: "the bank's current exposure inventory — every
        risk-exposure row attached to one of the bank's periods in OPEN or
        FILING_DUE"

        Design: Corner/calculations/stress_loss_projection_input_set_filtering
        """
        bank = create_bank("CH-FLT-001", legal_name="FiltBank")
        p1 = create_period(bank["id"], "2026-03-31", 2026, "Q1")
        p2 = create_period(bank["id"], "2026-06-30", 2026, "Q2")
        add_exposure(bank["id"], p1["id"], exposure_at_default_cents=50_000_000_000)
        add_exposure(bank["id"], p2["id"], exposure_at_default_cents=100_000_000_000)
        add_instrument(bank["id"], outstanding_amount_cents=10_000_000_000)
        # File, accept, and CLOSE P1 so its exposures leave the inventory.
        report1 = create_prepared_call_report(bank["id"], p1["id"])
        # Move both periods unambiguously to FILING_DUE before submitting.
        advance_clock_past("2026-06-30")
        validate_success(
            api.submit_call_report(
                bank["id"], p1["id"], report1["id"],
                make_capital_analyst_headers("analyst-submitter-1"),
            )
        )
        validate_success(api.accept_call_report(bank["id"], p1["id"], report1["id"], regulator_reviewer_headers))
        validate_success(api.close_reporting_period(bank["id"], p1["id"], capital_analyst_headers))
        scenario = create_active_scenario(bank["id"], "FILT-S", **SEVERE_SCENARIO)
        # Only P2's 100e9 CORPORATE counts: floor(100e9 * 209 / 10000) = 2.09e9.
        assert scenario["projected_pre_tax_loss_cents"] == 2_090_000_000


class TestPlanInvariants(object):
    def test_single_inflight_capital_plan_invariant(self, api, system_operator_headers, capital_analyst_headers):
        """PRD §3.5: "A bank may have only one plan in flight at a time:
        neither creation nor board submission is permitted while another plan
        of the same bank sits in BOARD_REVIEW, SUBMITTED, SUPERVISORY_REVIEW,
        or APPROVED, and a violation is rejected with ERR_INVARIANT_VIOLATION."

        Design: Corner/validations/single_inflight_capital_plan_invariant
        """
        bank, period, report = setup_accepted_report(
            "CH-INV-001", cet1_cents=10_000_000_000, rwa_cents=100_000_000_000
        )
        sc1 = create_active_scenario(
            bank["id"], "S1-INV", gdp_shock_bps=-100, unemployment_peak_bps=600,
            hpi_shock_bps=-500, cre_price_shock_bps=-500, market_shock_bps=-1000,
        )
        sc2 = create_active_scenario(
            bank["id"], "S2-INV", gdp_shock_bps=-200, unemployment_peak_bps=800,
            hpi_shock_bps=-1000, cre_price_shock_bps=-1500, market_shock_bps=-2000,
        )
        plan1 = create_draft_plan(bank["id"], period["id"], sc1["id"])
        plan1 = validate_success(
            api.submit_plan_board(bank["id"], plan1["id"], make_capital_analyst_headers(PREPARER_USER_ID))
        )
        assert plan1["status"] == "BOARD_REVIEW"
        # While plan1 sits in BOARD_REVIEW, creating a second plan violates
        # the single-in-flight invariant.
        res = api.create_capital_plan(
            bank["id"],
            {"plan_year": 2027, "baseline_period_id": period["id"], "stress_scenario_id": sc2["id"]},
            capital_analyst_headers,
        )
        validate_error(res, ApiErrorId.ERR_INVARIANT_VIOLATION)


class TestPlanObjectionLoop(object):
    def test_objection_cascades_to_distributions_and_supervisory_status(
        self, api, system_operator_headers, capital_analyst_headers, regulator_reviewer_headers
    ):
        """PRD §3.5: "It moves the plan to OBJECTED, escalates the bank's
        supervisory_status to UNDER_MOU, moves every attached distribution
        request in PROPOSED or APPROVED_NOT_EXECUTED to REJECTED with reserved
        capacity released back to mdba_cents, and increments the bank's
        version."

        Design: Difficulty/non_linear_state_machine/capital_plan_objection_loop
        """
        bank, period, report, scenario, plan = setup_plan_in_supervisory_review(
            "CH-PLN-001", 10_000_000_000, 100_000_000_000, scenario_code="BASE"
        )
        # Payment dates must fall inside the payment period's quarter and not
        # precede the current date (PRD §3.6); Q1 2027 / 2027-03-15 qualifies.
        pay_period = create_payment_period(bank["id"])
        dist = create_proposed_distribution(
            bank["id"], plan["id"], pay_period["id"],
            distribution_kind="DIVIDEND", distribution_amount_cents=100_000_000,
            proposed_payment_date="2027-03-15",
        )
        objected = validate_success(
            api.regulator_object_plan(bank["id"], plan["id"], regulator_reviewer_headers)
        )
        assert objected["status"] == "OBJECTED"
        dist_now = validate_success(
            api.get_distribution_request(bank["id"], dist["id"], capital_analyst_headers)
        )
        assert dist_now["status"] == "REJECTED"
        bank_now = validate_success(api.get_bank(bank["id"], capital_analyst_headers))
        assert bank_now["supervisory_status"] == "UNDER_MOU"

    def test_amend_reopens_objected_plan_to_draft(self, api, system_operator_headers,
                                                  capital_analyst_headers, regulator_reviewer_headers):
        """PRD §3.5: "An objected plan is not terminal: an analyst's amend
        action reopens it to DRAFT, incrementing the plan's own version by
        one."

        Design: Difficulty/non_linear_state_machine/capital_plan_objection_loop
        """
        bank, period, report, scenario, plan = setup_plan_in_supervisory_review(
            "CH-PLN-002", 10_000_000_000, 100_000_000_000, scenario_code="BASE-2"
        )
        objected = validate_success(
            api.regulator_object_plan(bank["id"], plan["id"], regulator_reviewer_headers)
        )
        version_at_objection = objected["version"]
        amended = validate_success(api.amend_plan(bank["id"], plan["id"], capital_analyst_headers))
        assert amended["status"] == "DRAFT"
        assert amended["version"] == version_at_objection + 1
        # Full cycle completed: DRAFT -> BOARD_REVIEW -> SUBMITTED ->
        # SUPERVISORY_REVIEW -> OBJECTED -> DRAFT.

    def test_plan_terminal_superseded_lockdown_amend_on_draft_rejected(
        self, api, system_operator_headers, capital_analyst_headers, regulator_reviewer_headers
    ):
        """PRD §3.5: "An objected plan is not terminal: an analyst's amend
        action reopens it to DRAFT"

        Design: Corner/state_machines/capital_plan_terminal_superseded_lockdown
        """
        bank, period, report, scenario, plan = setup_plan_in_supervisory_review(
            "CH-SUP-001", 10_000_000_000, 100_000_000_000, scenario_code="BASE-SUP"
        )
        validate_success(api.regulator_object_plan(bank["id"], plan["id"], regulator_reviewer_headers))
        amended = validate_success(api.amend_plan(bank["id"], plan["id"], capital_analyst_headers))
        assert amended["status"] == "DRAFT"
        # amend is only legal from OBJECTED; the plan is now DRAFT.
        res = api.amend_plan(bank["id"], plan["id"], capital_analyst_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


class TestScheduledPlanActivation(object):
    def test_scheduled_deferred_plan_effective_activation(self, api, system_operator_headers, capital_analyst_headers):
        """PRD §2.5: "approved capital plans activate to EFFECTIVE on the
        first day of their plan year"

        Design: Corner/cross_cutting_layers/scheduled_deferred_plan_effective_activation
        """
        bank, period, report, scenario, plan = setup_plan_approved(
            "CH-SCD-001", 10_000_000_000, 100_000_000_000, scenario_code="BASE-SCD"
        )
        assert plan["status"] == "APPROVED"
        # Cross into plan year 2027: 2027-01-01T00:00:00Z has been reached.
        set_clock("2027-01-01T00:00:01Z")
        plan_now = validate_success(api.get_capital_plan(bank["id"], plan["id"], capital_analyst_headers))
        assert plan_now["status"] == "EFFECTIVE"
