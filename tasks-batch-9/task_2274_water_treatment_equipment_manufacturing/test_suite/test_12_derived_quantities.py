"""Derived money, flows, scores and margins, each computed in its pinned order."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    CLOCK_SEED,
    assert_flow,
    assert_money,
    assert_project_state,
    assert_skid_state,
    factories,
    fixtures,
    make_application_engineer_headers,
    make_contracts_administrator_headers,
    make_design_reviewer_headers,
    make_engineer_of_record_headers,
    make_fabrication_manager_headers,
    make_platform_admin_headers,
    make_quality_engineer_headers,
)

EARLY_GUARANTEE_DEADLINE = "2026-10-01T00:00:00.000Z"
LATE_CLOCK = "2027-01-10T00:00:00.000Z"
SECOND_WINDOW_START = "2026-12-01T00:00:00.000Z"
SECOND_WINDOW_END = "2026-12-31T00:00:00.000Z"


def _scoped_project(api, project_overrides=None, profile_overrides=None):
    """One accepted sample plus one turbidity objective, then a selection run."""
    state = fixtures.seed_catalog(api)
    project = fixtures.create_draft_project(api, **(project_overrides or {}))
    state["project"] = project
    state["influent_profile"] = fixtures.add_accepted_influent_profile(
        api, project["id"], **(profile_overrides or {})
    )
    state["turbidity_objective"] = fixtures.add_turbidity_objective(api, project["id"])
    stages = fixtures.run_selection(api, project["id"])
    state["stages"] = stages
    state["filtration_stage"] = stages[0]
    return state


def _project_with_an_early_guarantee_deadline(api):
    """The whole chain to COMMISSIONING on a contract of 400,000,000 cents whose
    guarantee is due on 2026-10-01, with all three deliverables accepted."""
    state = _scoped_project(
        api, project_overrides={"guarantee_deadline_at": EARLY_GUARANTEE_DEADLINE}
    )
    draft = fixtures.add_draft_package(
        api, state["filtration_stage"]["id"], state["material_spec"]["id"]
    )
    state["package"] = fixtures.approve_package(api, draft["id"])
    state.update(fixtures.preapproved_submittal(api, state["project"]["id"]))
    fixtures.post_bid(api, state["project"]["id"], 400000000)
    fixtures.record_award(api, state["project"]["id"], "AWARDED")
    fixtures.release_package(api, state["package"]["id"])
    skid = fixtures.skid_of_package(api, state["package"]["id"])
    state["skid"] = fixtures.drive_skid_fat_ready(api, skid["id"])
    state["fat_run"] = fixtures.schedule_fat_run(
        api, state["skid"], state["test_bay"]["id"]
    )
    fixtures.witness_run(api, state["fat_run"]["id"], "PASS", 0)
    fixtures.accept_all_deliverables(api, state["project"]["id"])
    return state


class TestProcessSelectionCosting:
    """The twenty-year evaluated cost and the capital basis it leaves behind."""

    def test_the_single_stage_is_sized_on_peak_flow_and_costed_over_twenty_years(
        self, api
    ):
        """6.000 mgd of microfiltration evaluates at 371,400,000 cents against a 240,000,000 basis.

        Filtration stages are sized on peak flow: "the stage's `design_flow_mgd` is the
        governing sample's `design_flow_mgd` multiplied by that sample's `peak_factor`,
        rounded half up to three decimal places." The capital term says "multiply the
        candidate's `unit_capex_cents_per_mgd` by the stage design flow and round the
        product **up** to the next whole cent. This capital figure is also what the stage
        stores as its `equipment_base_cost_cents`". The energy term says "multiply the
        candidate's `energy_kwh_per_mg` by the stage design flow, then by 365 days, then
        by the pinned energy price of 12 cents per kilowatt-hour, and round that annual
        figure **up** to the next whole cent. Multiply the rounded annual figure by the
        pinned twenty-year evaluation life."

        Design: Corner/calculations/process_selection_stamps_the_ranked_lifecycle_winner
        """
        state = _scoped_project(api)

        stages = state["stages"]
        assert len(stages) == 1
        stage = stages[0]
        assert stage["role"] == "FILTRATION"
        assert stage["stage_index"] == 1
        assert stage["upstream_stage_id"] is None
        assert_flow(stage["design_flow_mgd"], 6.000)
        assert_money(
            stage["equipment_base_cost_cents"], 240000000, "equipment_base_cost_cents"
        )
        assert_money(stage["evaluated_cost_cents"], 371400000, "evaluated_cost_cents")
        assert stage["status"] == "SELECTED"

        project = validate_success(
            api.get_project(state["project"]["id"], make_application_engineer_headers())
        )
        assert_project_state(project, status="SCOPED")
        assert (
            project["governing_influent_profile_id"] == state["influent_profile"]["id"]
        )

    def test_ineligible_technologies_never_reach_the_ranking(self, api):
        """Three cheaper rows are screened out and the only eligible row wins anyway.

        A technology "qualifies only if it satisfies five predicates simultaneously: its
        `role` equals the duty; its `status` is `ACTIVE`, so `DEPRECATED` catalog rows
        never compete; its `max_feed_turbidity_ntu` is at least the governing sample's
        `turbidity_ntu`; its `max_feed_tds_mg_l` is at least the governing sample's
        `tds_mg_l`; and the stage design flow falls inside its hydraulic window, meaning
        `min_design_flow_mgd` is at most the stage flow and `max_design_flow_mgd` is at
        least it — both ends inclusive."

        Design: Corner/calculations/deprecated_and_out_of_envelope_technologies_never_enter_the_pool
        """
        state = fixtures.seed_catalog(api)
        deprecated = fixtures.seed_filtration_technology(
            api,
            code="TECH-FILT-DEP",
            unit_capex_cents_per_mgd=8000000,
            status="DEPRECATED",
        )
        low_turbidity = fixtures.seed_filtration_technology(
            api,
            code="TECH-FILT-LOWTURB",
            unit_capex_cents_per_mgd=8000000,
            max_feed_turbidity_ntu=5.0,
        )
        large_only = fixtures.seed_filtration_technology(
            api,
            code="TECH-FILT-BIGONLY",
            unit_capex_cents_per_mgd=8000000,
            min_design_flow_mgd=10.000,
        )

        project = fixtures.create_draft_project(api)
        fixtures.add_accepted_influent_profile(api, project["id"])
        fixtures.add_turbidity_objective(api, project["id"])
        stages = fixtures.run_selection(api, project["id"])

        assert len(stages) == 1
        stage = stages[0]
        assert stage["technology_id"] == state["filtration_technology"]["id"]
        assert stage["technology_id"] not in (
            deprecated["id"],
            low_turbidity["id"],
            large_only["id"],
        )
        assert_money(stage["evaluated_cost_cents"], 371400000, "evaluated_cost_cents")
        assert_money(
            stage["equipment_base_cost_cents"], 240000000, "equipment_base_cost_cents"
        )

    def test_a_tight_footprint_allowance_adds_the_penalty_but_not_the_basis(self, api):
        """400 excess square feet add 18,000,000 cents to the evaluation only.

        The penalty term says "multiply the candidate's `footprint_sf_per_mgd` by the
        stage design flow and round half up to three decimal places to obtain the plan
        area the process would occupy. Subtract the project's
        `footprint_allowance_sf_per_stage`; if the result is negative, treat the excess
        as zero. Multiply the excess square footage by the pinned footprint penalty of
        45,000 cents — 450 dollars — per square foot and round **up** to the next whole
        cent." Only the capital term becomes the stage basis: "this capital figure is
        also what the stage stores as its `equipment_base_cost_cents`".

        Design: Corner/calculations/footprint_overrun_applies_the_penalty_constant
        """
        state = _scoped_project(
            api, project_overrides={"footprint_allowance_sf_per_stage": 5000.0}
        )

        stage = state["filtration_stage"]
        assert_flow(stage["design_flow_mgd"], 6.000)
        assert_money(
            stage["equipment_base_cost_cents"], 240000000, "equipment_base_cost_cents"
        )
        assert_money(stage["evaluated_cost_cents"], 389400000, "evaluated_cost_cents")

    def test_the_stage_flow_is_rounded_before_any_cost_term_is_taken(self, api):
        """5.70875 mgd becomes 5.709 first, so capital lands on 228,360,000 cents.

        The PRD says the stage's `design_flow_mgd` "is the governing sample's
        `design_flow_mgd` multiplied by that sample's `peak_factor`, rounded half up to
        three decimal places", and section 2.6 pins that "design flows in million gallons
        per day are carried and compared at three decimal places, rounded half up." Each
        cost term is then taken from that rounded flow, with the terms "each brought to
        whole cents before anything is added".

        Design: Corner/calculations/design_flow_is_rounded_to_three_places_before_costing
        """
        state = _scoped_project(
            api, profile_overrides={"design_flow_mgd": 4.567, "peak_factor": 1.250}
        )

        stage = state["filtration_stage"]
        assert_flow(stage["design_flow_mgd"], 5.709)
        assert_money(
            stage["equipment_base_cost_cents"], 228360000, "equipment_base_cost_cents"
        )
        assert_money(stage["evaluated_cost_cents"], 353387100, "evaluated_cost_cents")

    def test_two_objectives_lay_the_train_out_in_hydraulic_order_and_chain_it(self, api):
        """E. coli declared first, yet filtration is stage one and disinfection points back at it.

        Each active objective "maps to exactly one duty ... and five-day BOD and
        ammonia-nitrogen objectives both require `BIOLOGICAL`. The distinct duties so
        derived are then laid out in one pinned hydraulic order — biological treatment
        first, then filtration, then desalination, then disinfection — and only the
        duties actually required appear. Each retained duty becomes one **treatment
        stage**, numbered from 1 upward in that order as its `stage_index`, with `role`
        copied from the duty and `upstream_stage_id` pointing at the stage created
        immediately before it; the head stage carries null there."

        Design: Corner/calculations/two_role_train_is_ordered_and_chained_upstream_to_downstream
        """
        fixtures.seed_catalog(api, with_disinfection=True)
        project = fixtures.create_draft_project(api)
        fixtures.add_accepted_influent_profile(api, project["id"])
        fixtures.add_ecoli_objective(api, project["id"])
        fixtures.add_turbidity_objective(api, project["id"])

        stages = fixtures.run_selection(api, project["id"])

        assert len(stages) == 2
        filtration, disinfection = stages
        assert filtration["role"] == "FILTRATION"
        assert filtration["stage_index"] == 1
        assert filtration["upstream_stage_id"] is None
        assert_flow(filtration["design_flow_mgd"], 6.000)
        assert_money(
            filtration["evaluated_cost_cents"], 371400000, "evaluated_cost_cents"
        )

        assert disinfection["role"] == "DISINFECTION"
        assert disinfection["stage_index"] == 2
        assert disinfection["upstream_stage_id"] == filtration["id"]
        assert_flow(disinfection["design_flow_mgd"], 6.000)
        assert_money(
            disinfection["equipment_base_cost_cents"],
            72000000,
            "equipment_base_cost_cents",
        )
        assert_money(
            disinfection["evaluated_cost_cents"], 119304000, "evaluated_cost_cents"
        )


class TestFirmPricingAndTheVarianceFlag:
    """A costly alloy drags the firm price away from the budgetary one."""

    def test_a_thirty_five_percent_variance_raises_the_flag_and_the_posture(self, api):
        """Duplex alloy prices firm at 352,123,200 cents, a variance of 0.3500.

        The PRD says `firm_cost_cents` "is the base multiplied by the material cost
        index, by the pressure uplift, by the code-stamp surcharge, and by the escalation
        factor, rounded half up to whole cents exactly once at the end", and that
        "`cost_variance_pct` is the firm price minus the budgetary price, divided by the
        budgetary price, rounded half up to four decimal places ... `variance_flag`
        becomes true when that fraction is **strictly greater than** 0.15". Approval
        "stamps `approved_at` with the logical clock's current instant, stores
        `reviewed_by_user_id`, and freezes the firm price ... the parent stage
        transitions `SELECTED → ENGINEERED` and advances its own `version` by 1, and the
        project's `delivery_posture` is recomputed — becoming `AT_RISK` when the newly
        computed variance flag is set."

        Design: Corner/calculations/firm_cost_variance_above_fifteen_percent_raises_the_flag
        """
        state = _scoped_project(api)
        duplex = fixtures.seed_material_spec(
            api, code="MAT-DUPLEX-2205", cost_index=1.35
        )
        draft = fixtures.add_draft_package(
            api,
            state["filtration_stage"]["id"],
            duplex["id"],
            tag_number="F-100",
            design_pressure_psig=150,
        )
        validate_success(
            api.submit_package_for_review(
                draft["id"], make_application_engineer_headers()
            )
        )

        package = validate_success(
            api.decide_package_review(
                draft["id"], {"decision": "APPROVE"}, make_design_reviewer_headers()
            )
        )

        assert package["status"] == "APPROVED"
        assert_money(
            package["budgetary_cost_cents"], 260832000, "budgetary_cost_cents"
        )
        assert_money(package["firm_cost_cents"], 352123200, "firm_cost_cents")
        assert package["cost_variance_pct"] == 0.3500
        assert package["variance_flag"] is True
        assert package["approved_at"] == CLOCK_SEED
        assert package["reviewed_by_user_id"] == "rev-1"
        assert package["version"] == 3

        stage = validate_success(
            api.get_treatment_stage(
                state["filtration_stage"]["id"], make_application_engineer_headers()
            )
        )
        assert stage["status"] == "ENGINEERED"

        project = validate_success(
            api.get_project(state["project"]["id"], make_contracts_administrator_headers())
        )
        assert_project_state(project, delivery_posture="AT_RISK")


class TestComplianceRescoring:
    """Every child deviation keeps contributing, at its own multiplier."""

    def test_accepting_the_major_deviation_leaves_the_pending_minor_at_full_weight(
        self, api
    ):
        """15 points at a quarter plus 2 points at full weight scores the submittal 94.25.

        The PRD says "each deviation's `weighted_penalty_points` is its severity weight
        multiplied by its disposition multiplier, rounded half up to two decimal places.
        Severity weights are pinned: 2 points for `MINOR`, 6 for `MODERATE`, 15 for
        `MAJOR` and 30 for `FUNDAMENTAL`. Disposition multipliers are equally pinned: a
        `PENDING` deviation counts at full weight, a `REJECTED` one also counts at full
        weight, an `ACCEPTED` one counts at one quarter of its weight, and a `WITHDRAWN`
        one counts at zero." The roll-up says "the submittal's total penalty is the sum of
        those already-rounded per-deviation points, rounded half up to two decimal places
        again; `compliance_score` is 100 minus that total".

        Design: Corner/calculations/accepting_one_deviation_rescores_the_submittal_at_quarter_weight
        """
        state = fixtures.scoped_single_stage_project(api)
        submittal = fixtures.add_submittal(api, state["project"]["id"])
        major = fixtures.add_deviation(
            api, submittal["id"], "MAJOR", spec_paragraph="2.03.B"
        )
        minor = fixtures.add_deviation(
            api,
            submittal["id"],
            "MINOR",
            spec_paragraph="2.05.C",
            description="Nameplate layout differs from named basis",
        )
        validate_success(
            api.submit_or_equal_submittal(
                submittal["id"], make_application_engineer_headers()
            )
        )

        dispositioned = validate_success(
            api.disposition_spec_deviation(
                major["id"],
                {"disposition": "ACCEPTED"},
                make_engineer_of_record_headers(),
            )
        )

        assert dispositioned["disposition"] == "ACCEPTED"
        assert dispositioned["weighted_penalty_points"] == 3.75
        assert dispositioned["dispositioned_by_user_id"] == "eor-1"

        untouched = validate_success(
            api.get_spec_deviation(minor["id"], make_engineer_of_record_headers())
        )
        assert untouched["disposition"] == "PENDING"
        assert untouched["weighted_penalty_points"] == 2.00

        parent = validate_success(
            api.get_or_equal_submittal(
                submittal["id"], make_engineer_of_record_headers()
            )
        )
        assert parent["compliance_score"] == 94.25
        assert parent["open_fundamental_count"] == 0
        assert parent["status"] == "SUBMITTED"


class TestGuaranteeEvaluation:
    """The declared averaging basis picks which aggregate the readings fold to."""

    def test_a_monthly_average_basis_folds_the_readings_to_their_mean(self, api):
        """Readings of 0.200 and 0.295 average to 0.248, a margin of 17.33 percent.

        The PRD says "the `compared_value` depends on the objective's declared averaging
        `basis`. On a `MAX_DAY` basis it is the **maximum** of the samples; on a
        `MONTHLY_AVERAGE` basis it is the **arithmetic mean** of the samples. Either way
        it is rounded half up to three decimal places." The margin "is the shortfall from
        the limit expressed as a percentage of the limit: the limit minus the compared
        value, divided by the limit, multiplied by 100, rounded half up to two decimal
        places", and "if `min_margin_pct` is at least the guarantee margin band of 5.0
        percent, the result is `PASSED`".

        Design: Corner/calculations/monthly_average_basis_passes_readings_that_max_day_would_only_conditionally_pass
        """
        state = fixtures.commissioning_project(api)
        fixtures.accept_all_deliverables(api, state["project"]["id"])
        validate_success(
            api.create_treatment_objective(
                state["project"]["id"],
                factories.turbidity_objective_payload(
                    limit_value=0.300, basis="MONTHLY_AVERAGE"
                ),
                make_application_engineer_headers(),
            ),
            201,
        )
        demo = fixtures.record_demo(
            api,
            state["project"]["id"],
            state["skid"]["id"],
            [
                {"parameter": "TURBIDITY_NTU", "measured_value": 0.200},
                {"parameter": "TURBIDITY_NTU", "measured_value": 0.295},
            ],
        )

        certified = validate_success(
            api.certify_performance_demo(
                demo["id"], {"certification": "PASS"}, make_quality_engineer_headers()
            )
        )

        assert certified["result"] == "PASSED"
        assert certified["round_no"] == 1
        assert certified["min_margin_pct"] == 17.33
        assert certified["certified_by_user_id"] == "qa-1"

        entry = next(
            row
            for row in certified["evaluation"]
            if row["parameter"] == "TURBIDITY_NTU"
        )
        assert entry["basis"] == "MONTHLY_AVERAGE"
        assert entry["compared_value"] == 0.248
        assert entry["passed"] is True

        project = validate_success(
            api.get_project(state["project"]["id"], make_contracts_administrator_headers())
        )
        assert_project_state(project, status="GUARANTEED", guarantee_status="MET")
        assert_money(
            project["liquidated_damages_cents"], 0, "liquidated_damages_cents"
        )

    def test_a_second_failure_defaults_the_guarantee_and_caps_the_damages(self, api):
        """101 days past the deadline accrue 20,200,000 cents, truncated to the 20,000,000 cap.

        The PRD says "when the demonstration that ends in `FAILED` or
        `CONDITIONAL_PASS` is the **second** round, the project's last chance is gone. It
        moves `COMMISSIONING → REMEDIATION`, its `guarantee_status` becomes `DEFAULTED`,
        its `delivery_posture` is recomputed (to `AT_RISK` or `HELD`), and liquidated
        damages are computed and written to `liquidated_damages_cents`." The formula says
        "the elapsed delay is the whole days between `guarantee_deadline_at` and now,
        discarding any partial day and floored at zero. The daily rate is
        `contract_amount_cents` multiplied by 0.05 percent, rounded half up to whole cents
        *once*. The cap is `contract_amount_cents` multiplied by 5 percent, rounded half
        up to whole cents. The stored figure is the smaller of the daily rate multiplied
        by the whole elapsed days, and the cap."

        Design: Corner/calculations/liquidated_damages_accrual_is_capped_at_five_percent_of_contract
        """
        state = _project_with_an_early_guarantee_deadline(api)
        first = fixtures.record_demo(
            api,
            state["project"]["id"],
            state["skid"]["id"],
            [{"parameter": "TURBIDITY_NTU", "measured_value": 0.500}],
        )
        fixtures.certify_demo(api, first["id"], "FAIL")

        validate_success(
            api.set_clock(LATE_CLOCK, make_platform_admin_headers())
        )
        second = fixtures.record_demo(
            api,
            state["project"]["id"],
            state["skid"]["id"],
            [{"parameter": "TURBIDITY_NTU", "measured_value": 0.400}],
            SECOND_WINDOW_START,
            SECOND_WINDOW_END,
        )

        certified = validate_success(
            api.certify_performance_demo(
                second["id"], {"certification": "FAIL"}, make_quality_engineer_headers()
            )
        )

        assert certified["result"] == "FAILED"
        assert certified["round_no"] == 2
        assert certified["min_margin_pct"] == -33.33

        project = validate_success(
            api.get_project(state["project"]["id"], make_contracts_administrator_headers())
        )
        assert_project_state(
            project,
            status="REMEDIATION",
            delivery_posture="AT_RISK",
            guarantee_status="DEFAULTED",
        )
        assert_money(
            project["liquidated_damages_cents"], 20000000, "liquidated_damages_cents"
        )
        assert_money(
            project["contract_amount_cents"], 400000000, "contract_amount_cents"
        )


class TestFactoryTestOutcomeAggregation:
    """The punchlist count can override the result the witness asked for."""

    def test_a_pass_carrying_four_open_items_is_recorded_as_conditional(self, api):
        """Four items is strictly more than three, so the run lands on CONDITIONAL.

        The PRD says "a witness who asks for `PASS` while recording **more than** three
        open punchlist items is recorded as `CONDITIONAL`, never `PASSED`; the comparison
        is strictly greater-than, so a `PASS` carrying exactly three punchlist items
        stays `PASSED`." Posture then reads the run: "if any of those packages has its
        `variance_flag` set, **or** any factory test run on their skids ended `FAILED` or
        `CONDITIONAL`, **or** any performance demonstration of the project ended `FAILED`
        or `CONDITIONAL_PASS`, the posture is `AT_RISK`."

        Design: Corner/calculations/pass_with_four_punchlist_items_is_stored_as_conditional
        """
        state = fixtures.scheduled_fat_run_project(api)

        run = validate_success(
            api.witness_fat_run(
                state["fat_run"]["id"],
                {"result": "PASS", "punchlist_item_count": 4},
                make_quality_engineer_headers(),
            )
        )

        assert run["status"] == "CONDITIONAL"
        assert run["punchlist_item_count"] == 4
        assert run["witnessed_by_user_id"] == "qa-1"

        package = validate_success(
            api.get_equipment_package(
                state["package"]["id"], make_application_engineer_headers()
            )
        )
        assert package["status"] == "RELEASED_FOR_FAB"

        project = validate_success(
            api.get_project(state["project"]["id"], make_contracts_administrator_headers())
        )
        assert_project_state(
            project, status="IN_FABRICATION", delivery_posture="AT_RISK"
        )

        skid = fixtures.current_skid(api, state["skid"]["id"])
        assert_skid_state(skid, mechanical_status="MECH_COMPLETE", rework_count=0)

        bay = validate_success(
            api.get_test_bay(state["test_bay"]["id"], make_fabrication_manager_headers())
        )
        assert bay["reserved_footprint_minutes"] == 0


class TestBidWaterfallOnASingleStage:
    """One approved package, five pinned steps, one integer margin test."""

    def test_the_waterfall_lands_on_350194347_and_the_offer_clears_the_floor(self, api):
        """A 339,994,512 base takes the middle bond tier and 2 percent contingency.

        Step 1 says "each line's amount is that package's `firm_cost_cents` multiplied by
        one plus the pinned overhead of 18.5 percent, rounded half up to whole cents".
        Step 2 says "a base above that but at most 500,000,000 cents (five million
        dollars) takes 1.00 percent". Step 4 multiplies the base by "2 percent when the
        posture is `ON_TRACK`". The floor says "`offered_price_cents` multiplied by
        10,000 must be at least `evaluated_bid_price_cents` multiplied by 10,800."

        Design: Corner/calculations/bid_pricing_runs_the_pinned_six_step_waterfall
        """
        state = fixtures.bid_ready_single_stage_project(api)

        project = validate_success(
            api.submit_bid(
                state["project"]["id"],
                {"offered_price_cents": 378209895},
                make_contracts_administrator_headers(),
            )
        )

        assert project["status"] == "BID_SUBMITTED"
        assert_money(
            project["base_bid_amount_cents"], 339994512, "base_bid_amount_cents"
        )
        assert_money(project["bond_premium_cents"], 3399945, "bond_premium_cents")
        assert_money(project["contingency_cents"], 6799890, "contingency_cents")
        assert_money(
            project["evaluated_bid_price_cents"], 350194347, "evaluated_bid_price_cents"
        )
        assert_money(project["offered_price_cents"], 378209895, "offered_price_cents")
        assert_money(project["contract_amount_cents"], 0, "contract_amount_cents")
        assert project["awarded_at"] is None


class TestReserveReconciliation:
    """Two ledgers reported side by side over two posted draws."""

    def test_two_draws_reconcile_line_by_line_against_the_funded_reserve(self, api):
        """Accruals of 1,830,000 and 1,708,000 leave 8,662,000 cents available.

        The accrual line is "`quantity` multiplied by `catalog_unit_cost_cents`, marked up
        by 22 percent, rounded half up to whole cents", the settled line is the invoiced
        product "uplifted by 6.5 percent freight, rounded half up to whole cents", and
        section 2.11 pins the reserve invariant: "at every instant
        `reserve_committed_accrual_cents` plus `reserve_available_cents` equals
        `reserve_funded_cents`, in whole cents, with no rounding slack." The settlement
        ledger is separate: the agreement "recomputes `settlement_variance_cents` as the
        settled total minus the accrual total, and advances its `version` by 1."

        Design: Corner/calculations/agreement_totals_reconcile_across_two_draws
        """
        state = fixtures.service_active_project(api)
        fixtures.post_draw(
            api,
            state["agreement"]["id"],
            draw_type="CONSUMABLE",
            quantity=3,
            catalog_unit_cost_cents=500000,
            invoiced_unit_cost_cents=480000,
        )

        second = fixtures.post_draw(
            api,
            state["agreement"]["id"],
            draw_type="CONSUMABLE",
            item_code="MF-ELEM-8",
            quantity=2,
            catalog_unit_cost_cents=700000,
            invoiced_unit_cost_cents=690000,
        )

        assert_money(second["accrual_amount_cents"], 1708000, "accrual_amount_cents")
        assert_money(second["settled_amount_cents"], 1469700, "settled_amount_cents")
        assert_money(second["warranty_credit_cents"], 0, "warranty_credit_cents")

        agreement = fixtures.current_agreement(api, state["agreement"]["id"])
        assert_money(
            agreement["reserve_committed_accrual_cents"],
            3538000,
            "reserve_committed_accrual_cents",
        )
        assert_money(
            agreement["reserve_committed_settled_cents"],
            3003300,
            "reserve_committed_settled_cents",
        )
        assert_money(
            agreement["reserve_available_cents"], 8662000, "reserve_available_cents"
        )
        assert_money(
            agreement["settlement_variance_cents"], -534700, "settlement_variance_cents"
        )
        assert (
            agreement["reserve_committed_accrual_cents"]
            + agreement["reserve_available_cents"]
            == 12200000
        )
        assert agreement["status"] == "ACTIVE"
