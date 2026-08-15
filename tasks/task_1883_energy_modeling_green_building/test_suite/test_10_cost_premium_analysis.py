"""The cost premium analysis: pinned evaluation order, the incentive stacking
waterfall and its cap, the 1:1 constraint, and recalculation reconciliation
(PRD §3.7)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    apply_incentive,
    approve_incentive,
    assert_analysis_invariants,
    assert_cost_premium_analysis,
    create_analysis,
    create_incentive_program,
    create_locked_models,
    create_members,
    create_project,
    get_success_data,
    make_project_administrator_headers,
    setup_certified_project,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
ANY = TEST_USERS["any_headers"]


def _project_with_locked_models(api, project_name="Tower D",
                                rating_system="LEED_ID_C"):
    members = create_members()
    project = create_project(
        members["admin"]["id"], project_name=project_name,
        rating_system=rating_system, target_level="SILVER")
    baseline, proposed = create_locked_models(
        project["id"], members["modeler"]["id"])
    return members, project, baseline, proposed


def _approve_program(ctx, **program_overrides):
    program = create_incentive_program(**program_overrides)
    application = apply_incentive(
        ctx["project"]["id"], program["id"], ctx["members"]["admin"]["id"])
    approve_incentive(application["id"])
    return program, application


class TestPinnedEvaluationOrder:
    def test_analysis_computes_pinned_chain_without_incentives(self, api):
        """PRD §3.7: "First, `annual_energy_savings_cents` is the locked baseline's `annual_energy_cost_confirmed_only_cents` minus the locked proposed model's `annual_energy_cost_confirmed_only_cents`. Second, `incentive_total_cents` runs the stacking waterfall: applications in `APPROVED` or `DISBURSED` are eligible while `APPLIED` ones contribute nothing; applications under combinable programs contribute their full claimed amounts; applications under non-combinable programs contribute, per `incentive_type`, only the largest claimed amount among that type's eligible applications — zero for a type with none; the raw total of the combinable sum plus those per-type maxima is then capped at forty percent of `incremental_construction_cost_cents`, the cap truncated down to a whole cent, and the incentive total is the smaller of the raw total and the cap. The cap's base is always the pre-incentive incremental cost, never the net premium — computing it from the net premium would be circular and is forbidden. Third, `net_cost_premium_cents` is `incremental_construction_cost_cents` minus `incentive_total_cents`. Fourth, `simple_payback_years` is `net_cost_premium_cents` divided by `annual_energy_savings_cents`, rounded half up to one decimal place, using the stored integer-cent operands of the preceding steps."

        Design: Difficulty/combinatorial_formula/cost_premium_pinned_evaluation_order
        """
        members, project, baseline, proposed = _project_with_locked_models(api)
        analysis = validate_success(
            api.create_cost_premium_analysis(
                {"project_id": project["id"],
                 "incremental_construction_cost_cents": 50000000},
                make_project_administrator_headers(members["admin"]["id"])),
            201,
        )
        assert_cost_premium_analysis(analysis)
        assert analysis["annual_energy_savings_cents"] == 600000, "step 1"
        assert analysis["incentive_total_cents"] == 0, "step 2: no eligible applications"
        assert analysis["net_cost_premium_cents"] == 50000000, "step 3"
        assert analysis["simple_payback_years"] == 83.3, (
            "step 4: round_half_up(50000000/600000, 1dp)")
        assert analysis["analysis_version"] == 1
        assert_analysis_invariants(analysis)

    def test_recalculate_increments_analysis_version(self, api):
        """PRD §3.7: "The analysis carries an `analysis_version` starting at 1, and recalculating it — after new incentive approvals or a re-locked model — recomputes all four figures against current data and increments `analysis_version` by one."

        Design: Difficulty/combinatorial_formula/cost_premium_pinned_evaluation_order
        """
        members, project, baseline, proposed = _project_with_locked_models(api)
        analysis = create_analysis(project["id"], members["admin"]["id"])
        assert analysis["analysis_version"] == 1

        recalculated = validate_success(
            api.recalculate_cost_premium_analysis(
                analysis["id"], make_project_administrator_headers(members["admin"]["id"]))
        )
        assert recalculated["analysis_version"] == 2
        assert recalculated["annual_energy_savings_cents"] == 600000
        assert recalculated["incentive_total_cents"] == 0
        assert recalculated["net_cost_premium_cents"] == 50000000
        assert recalculated["simple_payback_years"] == 83.3


class TestAnalysisPrerequisites:
    def test_analysis_without_locked_models_rejected(self, api):
        """PRD §3.7: "It is one-to-one with the project — creating a second one is rejected with `ERR_ANALYSIS_EXISTS` (HTTP 409) — and it requires the project's `LOCKED` baseline and `LOCKED` proposed models to exist, otherwise `ERR_PROPOSED_MODEL_NOT_LOCKED` (HTTP 409)."

        Design: Corner/validations/analysis_without_locked_models_rejected
        """
        members = create_members()
        project = create_project(members["admin"]["id"], project_name="NoModel Tower")
        resp = api.create_cost_premium_analysis(
            {"project_id": project["id"],
             "incremental_construction_cost_cents": 50000000},
            make_project_administrator_headers(members["admin"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PROPOSED_MODEL_NOT_LOCKED)

    def test_second_analysis_blocked(self, api):
        """PRD §3.7: "It is one-to-one with the project — creating a second one is rejected with `ERR_ANALYSIS_EXISTS` (HTTP 409) — and it requires the project's `LOCKED` baseline and `LOCKED` proposed models to exist, otherwise `ERR_PROPOSED_MODEL_NOT_LOCKED` (HTTP 409)."

        Design: Corner/validations/second_analysis_blocked
        """
        members, project, baseline, proposed = _project_with_locked_models(
            api, project_name="OneAnalysis Tower", rating_system="LEED_BD_C")
        analysis = create_analysis(project["id"], members["admin"]["id"])

        resp = api.create_cost_premium_analysis(
            {"project_id": project["id"],
             "incremental_construction_cost_cents": 51000000},
            make_project_administrator_headers(members["admin"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ANALYSIS_EXISTS)
        after = validate_success(api.get_cost_premium_analysis(analysis["id"], ANY))
        assert after["analysis_version"] == 1

    def test_cost_premium_analysis_subresource_read(self, api):
        """PRD §3.7: "The analysis is readable on its own and as a sub-resource of the project, where the one-to-one collection returns an array of zero or one element."
        PRD §3.7: "First, `annual_energy_savings_cents` is the locked baseline's `annual_energy_cost_confirmed_only_cents` minus the locked proposed model's `annual_energy_cost_confirmed_only_cents`."

        Design: Corner/endpoints/cost_premium_analysis_subresource_read
        """
        members, project, baseline, proposed = _project_with_locked_models(
            api, project_name="Sub Tower", rating_system="LEED_BD_C")

        before = validate_success(
            api.get_project_cost_premium_analysis(project["id"], ANY))
        assert isinstance(before, list) and len(before) == 0, (
            "the one-to-one collection is empty before creation")

        create_analysis(project["id"], members["admin"]["id"])

        after = validate_success(
            api.get_project_cost_premium_analysis(project["id"], ANY))
        assert isinstance(after, list) and len(after) == 1
        assert after[0]["annual_energy_savings_cents"] == 600000


class TestIncentiveStackingWaterfall:
    def _certified_performance_project(self, api):
        """PERFORMANCE-path project certified at level CERTIFIED (40 awarded
        points) with locked models (savings 600000)."""
        return setup_certified_project(
            design_credits=[
                {"code": "EAp1", "points": 20, "is_prerequisite": True,
                 "phase_eligibility": "BOTH", "award": 20},
                {"code": "WEc1", "points": 10, "category": "WATER", "award": 10},
            ],
            construction_credits=[
                {"code": "MRc1", "points": 10, "category": "MATERIALS",
                 "phase_eligibility": "CONSTRUCTION", "award": 10},
            ],
            project_overrides={"project_name": "Tower C",
                               "compliance_path": "PERFORMANCE"},
            with_models=True,
        )

    def test_stacking_waterfall_cap_binds(self, api):
        """PRD §3.7: "Second, `incentive_total_cents` runs the stacking waterfall: applications in `APPROVED` or `DISBURSED` are eligible while `APPLIED` ones contribute nothing; applications under combinable programs contribute their full claimed amounts; applications under non-combinable programs contribute, per `incentive_type`, only the largest claimed amount among that type's eligible applications — zero for a type with none; the raw total of the combinable sum plus those per-type maxima is then capped at forty percent of `incremental_construction_cost_cents`, the cap truncated down to a whole cent, and the incentive total is the smaller of the raw total and the cap."

        Design: Difficulty/combinatorial_formula/incentive_stacking_cap_waterfall
        """
        ctx = self._certified_performance_project(api)
        _approve_program(ctx, program_name="State Green Grant",
                         incentive_type="GRANT", benefit_amount_cents=8000000,
                         is_combinable=True)
        _approve_program(ctx, program_name="Utility Rebate",
                         incentive_type="UTILITY_REBATE", benefit_amount_cents=5000000,
                         is_combinable=True)
        _approve_program(ctx, program_name="Federal Tax Credit",
                         incentive_type="TAX_CREDIT", benefit_amount_cents=15000000,
                         is_combinable=False)
        _approve_program(ctx, program_name="State Tax Credit",
                         incentive_type="TAX_CREDIT", benefit_amount_cents=12000000,
                         is_combinable=False)

        analysis = create_analysis(
            ctx["project"]["id"], ctx["members"]["admin"]["id"],
            incremental_cost_cents=50000000)
        assert analysis["incentive_total_cents"] == 20000000, (
            "min(8000000 + 5000000 + max(15000000, 12000000) = 28000000, "
            "floor(0.40 * 50000000) = 20000000): the cap binds")
        assert analysis["annual_energy_savings_cents"] == 600000
        assert analysis["net_cost_premium_cents"] == 30000000
        assert analysis["simple_payback_years"] == 50.0
        assert_analysis_invariants(analysis)

    def test_per_type_max_and_applied_exclusion_below_cap(self, api):
        """PRD §3.7: "Second, `incentive_total_cents` runs the stacking waterfall: applications in `APPROVED` or `DISBURSED` are eligible while `APPLIED` ones contribute nothing; applications under combinable programs contribute their full claimed amounts; applications under non-combinable programs contribute, per `incentive_type`, only the largest claimed amount among that type's eligible applications — zero for a type with none; the raw total of the combinable sum plus those per-type maxima is then capped at forty percent of `incremental_construction_cost_cents`, the cap truncated down to a whole cent, and the incentive total is the smaller of the raw total and the cap."
        PRD §3.7: "Approval moves the application `APPLIED → APPROVED` and sets `claimed_amount_cents` to the program's `benefit_amount_cents`."

        Design: Difficulty/combinatorial_formula/incentive_stacking_cap_waterfall
        """
        ctx = self._certified_performance_project(api)
        _, app_g1 = _approve_program(
            ctx, program_name="State Green Grant", incentive_type="GRANT",
            benefit_amount_cents=8000000, is_combinable=True)
        _, app_t1 = _approve_program(
            ctx, program_name="Federal Tax Credit", incentive_type="TAX_CREDIT",
            benefit_amount_cents=15000000, is_combinable=False)
        _approve_program(
            ctx, program_name="State Tax Credit", incentive_type="TAX_CREDIT",
            benefit_amount_cents=12000000, is_combinable=False)
        # Merely APPLIED (never approved): contributes nothing to the waterfall.
        pending_program = create_incentive_program(
            program_name="City Grant", incentive_type="GRANT",
            benefit_amount_cents=9000000, is_combinable=True)
        pending = apply_incentive(
            ctx["project"]["id"], pending_program["id"], ctx["members"]["admin"]["id"])

        assert get_success_data(api.get_project_incentive(app_g1["id"], ANY))[
            "claimed_amount_cents"] == 8000000
        assert get_success_data(api.get_project_incentive(app_t1["id"], ANY))[
            "claimed_amount_cents"] == 15000000
        assert pending["status"] == "APPLIED"
        assert pending["claimed_amount_cents"] == 0

        analysis = create_analysis(
            ctx["project"]["id"], ctx["members"]["admin"]["id"],
            incremental_cost_cents=100000000)
        assert analysis["incentive_total_cents"] == 23000000, (
            "8000000 combinable + max(15000000, 12000000) per-type TAX_CREDIT; "
            "the APPLIED application contributes nothing; cap 40000000 not binding")
        assert analysis["net_cost_premium_cents"] == 77000000
        assert analysis["simple_payback_years"] == 128.3
        assert_analysis_invariants(analysis)


class TestRecalculateReconciliation:
    def test_recalculate_reconciles_after_approvals_below_cap(self, api):
        """PRD §3.7: "The analysis carries an `analysis_version` starting at 1, and recalculating it — after new incentive approvals or a re-locked model — recomputes all four figures against current data and increments `analysis_version` by one."
        PRD §3.7: "Second, `incentive_total_cents` runs the stacking waterfall: applications in `APPROVED` or `DISBURSED` are eligible while `APPLIED` ones contribute nothing; applications under combinable programs contribute their full claimed amounts; applications under non-combinable programs contribute, per `incentive_type`, only the largest claimed amount among that type's eligible applications — zero for a type with none; the raw total of the combinable sum plus those per-type maxima is then capped at forty percent of `incremental_construction_cost_cents`, the cap truncated down to a whole cent, and the incentive total is the smaller of the raw total and the cap."

        Design: Corner/complexity_layers/derived_field_recalc_and_waterfall_below_cap
        """
        ctx = setup_certified_project(with_models=True)
        analysis = create_analysis(
            ctx["project"]["id"], ctx["members"]["admin"]["id"],
            incremental_cost_cents=60000000)
        assert analysis["incentive_total_cents"] == 0, (
            "the analysis predates the approvals")
        assert analysis["analysis_version"] == 1

        _approve_program(ctx, program_name="State Green Grant",
                         incentive_type="GRANT", benefit_amount_cents=8000000,
                         is_combinable=True)
        _approve_program(ctx, program_name="Federal Tax Credit",
                         incentive_type="TAX_CREDIT", benefit_amount_cents=10000000,
                         is_combinable=False)
        _approve_program(ctx, program_name="State Tax Credit",
                         incentive_type="TAX_CREDIT", benefit_amount_cents=12000000,
                         is_combinable=False)

        recalculated = validate_success(
            api.recalculate_cost_premium_analysis(
                analysis["id"],
                make_project_administrator_headers(ctx["members"]["admin"]["id"]))
        )
        assert recalculated["incentive_total_cents"] == 20000000, (
            "8000000 combinable + max(10000000, 12000000) per-type; "
            "cap 24000000 not binding")
        assert recalculated["net_cost_premium_cents"] == 40000000
        assert recalculated["simple_payback_years"] == 66.7, (
            "round_half_up(40000000/600000, 1dp)")
        assert recalculated["analysis_version"] == 2
        assert_analysis_invariants(recalculated)
