"""Funding plans: the contribution solve's three floor variants, same-type
replacement, selection exclusivity, and the optimistic-concurrency token."""
from test_helpers import (
    ApiErrorId,
    F1_COMPONENTS,
    assert_funding_plan,
    create_funding_plan_payload,
    create_plan,
    recommend_plan,
    select_plan,
    setup_draft_study,
    study_version,
    validate_error,
    validate_paginated,
    validate_success,
)


def _setup_f1_draft(api, reserve_specialist_headers, name="Harbor Oaks HOA"):
    """Association (cash 500000, calendar year) + FY2026 FULL study with the
    standard two-component inventory, still DRAFT."""
    ctx = setup_draft_study(state_code="CA", cash=500000,
                            association_name=name, components=F1_COMPONENTS)
    return ctx


class TestContributionSolveVariants:
    def test_funding_plan_variants_diverge_literals(
            self, api, reserve_specialist_headers):
        """PRD §3.4: "The plan's `annual_contribution_cents` is the smallest
        non-negative integer number of cents for which the projected balance
        stays at or above the plan type's floor in every year-end position
        from the first projected year through the thirtieth." and "The floor
        is what distinguishes the three plan types": a BASELINE plan "sets the
        floor at zero in every year: the projected balance may never turn
        negative"; a THRESHOLD plan's floor is "one half of the largest
        single-year scheduled outflow anywhere in the thirty-year horizon,
        rounded half-up to integer cents"; a FULL plan "requires the projected
        balance in each year to cover that year's projected fully funded
        balance."

        Design: Difficulty/dual_variant_calc/funding_plan_variants_diverge
        """
        ctx = _setup_f1_draft(api, reserve_specialist_headers)
        study_id = ctx["study"]["id"]

        baseline = create_plan(study_id, "BASELINE")
        threshold = create_plan(study_id, "THRESHOLD")
        full = create_plan(study_id, "FULL")
        for plan in (baseline, threshold, full):
            assert_funding_plan(plan)

        assert baseline["annual_contribution_cents"] == 28825, (
            f"BASELINE solve: expected 28825, got "
            f"{baseline['annual_contribution_cents']}")
        assert threshold["annual_contribution_cents"] == 31820, (
            f"THRESHOLD solve: expected 31820, got "
            f"{threshold['annual_contribution_cents']}")
        assert threshold["threshold_floor_cents"] == 123964, (
            f"round_half_up(0.5 * 247927) = 123964; got "
            f"{threshold['threshold_floor_cents']}")
        assert full["annual_contribution_cents"] == 33077, (
            f"FULL solve: expected 33077, got "
            f"{full['annual_contribution_cents']}")

        rows, meta = validate_paginated(
            api.list_funding_plans(study_id, reserve_specialist_headers))
        assert meta["total_count"] == 3
        assert [r["id"] for r in rows] == [baseline["id"], threshold["id"],
                                           full["id"]]

    def test_funding_plan_variants_diverge_pairwise(
            self, api, reserve_specialist_headers):
        """PRD §3.4: "The floor is what distinguishes the three plan types"
        and "`threshold_floor_cents` is populated only on `THRESHOLD` plans
        and is null on `BASELINE` and `FULL` plans." and "The projection opens
        with `starting_cash_cents`, a snapshot of the association's
        `reserve_cash_balance_cents` taken at computation time."

        Design: Difficulty/dual_variant_calc/funding_plan_variants_diverge
        """
        ctx = _setup_f1_draft(api, reserve_specialist_headers,
                              name="Diverge HOA")
        study_id = ctx["study"]["id"]

        baseline = create_plan(study_id, "BASELINE")
        threshold = create_plan(study_id, "THRESHOLD")
        full = create_plan(study_id, "FULL")

        contributions = {baseline["annual_contribution_cents"],
                         threshold["annual_contribution_cents"],
                         full["annual_contribution_cents"]}
        assert len(contributions) == 3, (
            "identical inputs must still yield three different solved "
            f"contributions because only the floor changes; got "
            f"{contributions}")

        assert baseline["threshold_floor_cents"] is None
        assert full["threshold_floor_cents"] is None
        assert threshold["threshold_floor_cents"] is not None

        for plan in (baseline, threshold, full):
            assert plan["starting_cash_cents"] == 500000, (
                "starting_cash_cents snapshots the association cash at "
                f"computation; expected 500000, got "
                f"{plan['starting_cash_cents']}")


class TestThresholdFloorSolve:
    def test_threshold_floor_multi_input_solve(
            self, api, reserve_specialist_headers):
        """PRD §3.4: "A `THRESHOLD` plan sets the floor in every year to the
        plan's `threshold_floor_cents`, defined as one half of the largest
        single-year scheduled outflow anywhere in the thirty-year horizon,
        rounded half-up to integer cents" and "each successive year-end
        balance is the prior balance plus the contribution minus that year's
        scheduled outflow, the difference then grown by one year of interest
        at the study's `interest_rate`, with the result rounded half-up to
        integer cents — rounding is applied exactly once per year-step."

        Design: Difficulty/combinatorial_formula/threshold_floor_multi_input_solve
        """
        ctx = _setup_f1_draft(api, reserve_specialist_headers,
                              name="Threshold HOA")
        plan = create_plan(ctx["study"]["id"], "THRESHOLD")
        assert plan["threshold_floor_cents"] == 123964, (
            f"half the peak outflow 247927 rounded half-up; got "
            f"{plan['threshold_floor_cents']}")
        assert plan["annual_contribution_cents"] == 31820, (
            "the minimal constant contribution holding every year-end "
            f"balance >= 123964; got {plan['annual_contribution_cents']}")

    def test_threshold_floor_collapses_without_replacements(
            self, api, reserve_specialist_headers):
        """PRD §3.4: "when no replacement is scheduled at all, the largest
        outflow is zero and the floor collapses to zero." and "The plan's
        `annual_contribution_cents` is the smallest non-negative integer
        number of cents for which the projected balance stays at or above the
        plan type's floor in every year-end position from the first projected
        year through the thirtieth."

        Design: Difficulty/combinatorial_formula/threshold_floor_multi_input_solve
        """
        ctx = setup_draft_study(
            state_code="CA", cash=500000, association_name="No Peak HOA",
            components=[{
                "name": "Membrane", "category": "ROOFING",
                "useful_life_years": 40, "remaining_useful_life_years": 35,
                "current_replacement_cost_cents": 100000,
                "is_included_in_funding": True,
            }])
        plan = create_plan(ctx["study"]["id"], "THRESHOLD")
        assert plan["threshold_floor_cents"] == 0, (
            "first replacement lands in year 35, beyond the horizon: "
            f"expected floor 0, got {plan['threshold_floor_cents']}")
        assert plan["annual_contribution_cents"] == 0, (
            "with every outflow zero and a zero floor, the minimal feasible "
            f"contribution is 0; got {plan['annual_contribution_cents']}")


class TestPlanReplacementAndSelection:
    def test_plan_create_supersedes_existing_draft_plan(
            self, api, reserve_specialist_headers):
        """PRD §3.4: "At most one working draft of each type exists: creating
        a plan of a type that already has a `DRAFT` plan retires that older
        plan to `RETIRED`" and "The plan is solved once, at creation, and the
        result is frozen onto it."

        Design: Corner/state_machines/plan_create_supersedes_existing_draft_plan
        """
        ctx = _setup_f1_draft(api, reserve_specialist_headers,
                              name="Supersede Plan HOA")
        study_id = ctx["study"]["id"]
        roof = ctx["components"][0]

        old_plan = create_plan(study_id, "BASELINE")
        assert old_plan["annual_contribution_cents"] == 28825

        validate_success(api.patch_component(
            roof["id"], {"current_replacement_cost_cents": 120000},
            reserve_specialist_headers))

        new_plan = create_plan(study_id, "BASELINE")
        assert new_plan["annual_contribution_cents"] == 34897, (
            "recomputed against the patched cost 120000: expected 34897, got "
            f"{new_plan['annual_contribution_cents']}")

        rows, _ = validate_paginated(
            api.list_funding_plans(study_id, reserve_specialist_headers))
        old_row = next(r for r in rows if r["id"] == old_plan["id"])
        assert old_row["status"] == "RETIRED", (
            f"the superseded DRAFT plan retires; got {old_row['status']}")

    def test_plan_select_from_retired_rejected(self, api,
                                               reserve_specialist_headers,
                                               board_member_headers):
        """PRD §3.5: "Selection moves a `DRAFT` or `RECOMMENDED` plan to
        `SELECTED` and is valid only while the study is `SUBMITTED`; any other
        study state yields `ERR_INVALID_STATE`."

        Design: Corner/state_machines/plan_select_from_retired_rejected
        """
        ctx = _setup_f1_draft(api, reserve_specialist_headers,
                              name="Retired Plan HOA")
        study_id = ctx["study"]["id"]
        old_plan = create_plan(study_id, "BASELINE")
        create_plan(study_id, "BASELINE")  # retires old_plan

        res = api.select_plan(old_plan["id"], board_member_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_plan_create_same_type_recommended_rejected(
            self, api, reserve_specialist_headers):
        """PRD §3.4: "creating one whose type already has a `RECOMMENDED` or
        `SELECTED` plan is rejected with `ERR_PLAN_TYPE_LOCKED`."

        Design: Corner/validations/plan_create_same_type_recommended_rejected
        """
        ctx = setup_draft_study(state_code="CA", cash=500000,
                                association_name="Locked HOA",
                                components=[{
                                    "name": "Roof", "category": "ROOFING",
                                    "useful_life_years": 5,
                                    "remaining_useful_life_years": 2,
                                    "current_replacement_cost_cents": 100000,
                                    "is_included_in_funding": True,
                                }])
        study_id = ctx["study"]["id"]
        plan = create_plan(study_id, "BASELINE")
        recommend_plan(plan["id"])

        payload = create_funding_plan_payload("BASELINE",
                                              study_version(study_id))
        res = api.create_funding_plan(study_id, payload,
                                      reserve_specialist_headers)
        validate_error(res, ApiErrorId.ERR_PLAN_TYPE_LOCKED)

    def test_plan_select_while_other_selected_rejected(
            self, api, reserve_specialist_headers, board_member_headers):
        """PRD §3.5: "At most one plan per study may hold the selection:
        attempting to select a plan while another is already `SELECTED` is
        rejected with `ERR_PLAN_ALREADY_SELECTED`."

        Design: Corner/validations/plan_select_while_other_selected_rejected
        """
        ctx = setup_draft_study(state_code="CA", cash=500000,
                                with_visit=True,
                                association_name="Two Plan HOA",
                                components=[{
                                    "name": "Roof", "category": "ROOFING",
                                    "useful_life_years": 5,
                                    "remaining_useful_life_years": 2,
                                    "current_replacement_cost_cents": 100000,
                                    "is_included_in_funding": True,
                                }])
        study_id = ctx["study"]["id"]
        p1 = create_plan(study_id, "BASELINE")
        p2 = create_plan(study_id, "THRESHOLD")
        validate_success(api.submit_study(study_id,
                                          reserve_specialist_headers))
        select_plan(p1["id"])

        res = api.select_plan(p2["id"], board_member_headers)
        validate_error(res, ApiErrorId.ERR_PLAN_ALREADY_SELECTED)


class TestPlanCreateOptimisticConcurrency:
    def test_plan_create_stale_study_version_returns_412(
            self, api, reserve_specialist_headers):
        """PRD §2.9: "Its request body must carry `expected_study_version` —
        a non-optional field holding the `version` of the parent study as the
        client last observed it. If the supplied value does not equal the
        study's current `version` on the server, the creation is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/plan_create_stale_study_version_returns_412
        """
        ctx = setup_draft_study(state_code="CA", cash=500000,
                                association_name="OCC HOA",
                                components=F1_COMPONENTS)
        study_id = ctx["study"]["id"]
        observed_version = study_version(study_id)

        first = validate_success(api.create_funding_plan(
            study_id,
            create_funding_plan_payload("BASELINE", observed_version),
            reserve_specialist_headers), 201)
        assert_funding_plan(first)

        res = api.create_funding_plan(
            study_id,
            create_funding_plan_payload("THRESHOLD", observed_version),
            reserve_specialist_headers)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)
