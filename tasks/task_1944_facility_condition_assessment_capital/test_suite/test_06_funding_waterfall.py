"""Funding scenarios: the waterfall allocation, escalation variants,
per-item rounding, supersession, budget rules, and plan-version OCC."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_funding_scenario,
    create_deficiency,
    create_draft_plan,
    create_facility,
    create_funding_scenario_payload,
    create_scenario,
    get_capital_plan,
    get_facility,
    list_line_items,
    remediate_to_corrected,
    run_scenario,
    run_scenario_payload,
    setup_facility_with_system,
    setup_funded_plan,
    setup_system_with_deficiency,
    submit_plan,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import PLANNER


def get_funding_scenario(api, scenario_id):
    return validate_success(api.get_funding_scenario(scenario_id, PLANNER))


def _items_by_deficiency(api, plan_id):
    items = list_line_items(plan_id)
    return {item["deficiency_id"]: item for item in items}


class TestDualVariantCosting:
    def test_backlog_present_day_vs_line_item_escalated(self, api):
        """PRD §3.7: "Each line item's `escalated_cost_cents` compounds the
        deficiency's present-day `cost_estimate_cents` forward from the base
        year 2026 to the item's `planned_year` at the scenario's
        `escalation_rate`: the number of compounding years is the planned year
        minus 2026, and the escalated amount is the estimate multiplied by
        one-plus-the-rate raised to that power, rounded half-up to a whole cent
        exactly once, before any budget comparison."
        PRD §3.7: "For reporting outside planning — the facility backlog and
        deficiency listings — the same cost appears unescalated: the
        escalation rate is treated as zero, which is to say the
        `cost_estimate_cents` exactly as recorded."

        Design: Difficulty/dual_variant_calc/escalated_cost_present_vs_year_of_need
        """
        workspace = setup_funded_plan(
            deficiency_specs=[{"description": "Compressor bearing wear",
                               "cost_estimate_cents": 100000000,
                               "severity": 3, "urgency": 3,
                               "recommended_year": 2029}],
            plan_overrides={"title": "FY27-FY29 Plan", "start_year": 2027,
                            "horizon_years": 3},
            scenario_overrides={"name": "Baseline",
                                "annual_budget_cents": 200000000,
                                "escalation_rate": 0.03},
            system_overrides={"system_category": "HVAC", "name": "Chiller 1",
                              "install_year": 2010, "design_life_years": 25,
                              "replacement_cost_cents": 100000000,
                              "condition_rating": 4})
        facility = get_facility(workspace["facility"]["id"])
        assert facility["backlog_cost_cents"] == 100000000, (
            "backlog uses the present-day variant: escalation treated as 0")

        items = list_line_items(workspace["plan"]["id"])
        assert len(items) == 1
        item = items[0]
        # 100000000 * 1.03^3 = 109272700 (round_half_up, whole cents).
        assert item["escalated_cost_cents"] == 109272700
        assert item["planned_year"] == 2029
        assert item["funding_status"] == "FUNDED"
        assert item["escalated_cost_cents"] != facility["backlog_cost_cents"], (
            "the two cost variants diverge for identical input data")

    def test_escalated_cost_at_another_term_and_plan_total(self, api):
        """PRD §3.7: "the number of compounding years is the planned year
        minus 2026, and the escalated amount is the estimate multiplied by
        one-plus-the-rate raised to that power, rounded half-up to a whole
        cent exactly once, before any budget comparison."
        PRD §3.7: "The plan's `total_programmed_cents` — always the sum of
        `escalated_cost_cents` over the plan's `FUNDED` line items — is then
        recomputed, and the plan's `version` increments."

        Design: Difficulty/dual_variant_calc/escalated_cost_present_vs_year_of_need
        """
        workspace = setup_funded_plan(
            deficiency_specs=[{"description": "two years out",
                               "cost_estimate_cents": 100000000,
                               "severity": 3, "urgency": 3,
                               "recommended_year": 2028}],
            plan_overrides={"title": "P", "start_year": 2027,
                            "horizon_years": 3},
            scenario_overrides={"name": "Baseline",
                                "annual_budget_cents": 200000000,
                                "escalation_rate": 0.03})
        items = list_line_items(workspace["plan"]["id"])
        assert len(items) == 1
        # 100000000 * 1.03^2 = 106090000 exactly.
        assert items[0]["escalated_cost_cents"] == 106090000
        assert items[0]["planned_year"] == 2028
        plan = get_capital_plan(workspace["plan"]["id"])
        assert plan["total_programmed_cents"] == 106090000, (
            "plan total sums FUNDED escalated costs")
        facility = get_facility(workspace["facility"]["id"])
        assert facility["backlog_cost_cents"] == 100000000


class TestPerItemRounding:
    def test_round_per_item_then_compare_against_remainder(self, api):
        """PRD §3.7: "the escalated amount is the estimate multiplied by
        one-plus-the-rate raised to that power, rounded half-up to a whole
        cent exactly once, before any budget comparison. The per-year budget
        remainders are never re-rounded."
        PRD §3.7: "if that cost fits within the year's remaining budget, a
        **PlanLineItem** is created with `funding_status` `FUNDED`, the budget
        remainder is reduced by the cost, and the allocator moves on; if it
        does not fit, the line item is still created but with `funding_status`
        `UNFUNDED`, and the remainder is unchanged."
        PRD §3.7: "Candidates are ordered deterministically: highest
        `priority_score` first, with ties broken by earlier `created_at`"

        Design: Difficulty/combinatorial_formula/waterfall_per_item_rounding_then_compare
        """
        workspace = setup_funded_plan(
            deficiency_specs=[
                {"description": "Arc-flash remediation",
                 "cost_estimate_cents": 60000000, "severity": 5, "urgency": 4,
                 "is_code_violation": True, "recommended_year": 2027},
                {"description": "Panel labeling",
                 "cost_estimate_cents": 50000000, "severity": 3, "urgency": 3,
                 "recommended_year": 2027},
            ],
            plan_overrides={"title": "FY27 Plan", "start_year": 2027,
                            "horizon_years": 3},
            scenario_overrides={"name": "Tight",
                                "annual_budget_cents": 100000000,
                                "escalation_rate": 0.03},
            system_overrides={"system_category": "ELECTRICAL",
                              "name": "Main Switchgear", "install_year": 2012,
                              "design_life_years": 30,
                              "replacement_cost_cents": 500000000,
                              "condition_rating": 4})
        d1, d2 = workspace["deficiencies"]
        items = _items_by_deficiency(api, workspace["plan"]["id"])
        # D1: priority 0.6*5+0.4*4+10 = 14.60; cost round(60000000*1.03) =
        # 61800000 <= 100000000 -> FUNDED; remainder 38200000.
        assert items[d1["id"]]["escalated_cost_cents"] == 61800000
        assert items[d1["id"]]["funding_status"] == "FUNDED"
        # D2: priority 3.00; round(50000000*1.03) = 51500000 > 38200000 ->
        # UNFUNDED. The per-item cost is rounded once, then compared against
        # the un-rounded remainder.
        assert items[d2["id"]]["escalated_cost_cents"] == 51500000
        assert items[d2["id"]]["funding_status"] == "UNFUNDED"
        plan = get_capital_plan(workspace["plan"]["id"])
        assert plan["total_programmed_cents"] == 61800000, (
            "plan total sums FUNDED items only")

    def test_fractional_cent_escalation_rounded_once(self, api):
        """PRD §3.7: "rounded half-up to a whole cent exactly once, before any
        budget comparison. The per-year budget remainders are never
        re-rounded."
        PRD §3.7: "if that cost fits within the year's remaining budget, a
        **PlanLineItem** is created with `funding_status` `FUNDED`"

        Design: Difficulty/combinatorial_formula/waterfall_per_item_rounding_then_compare
        """
        workspace = setup_funded_plan(
            deficiency_specs=[
                {"description": "odd-cent job", "cost_estimate_cents": 10000001,
                 "severity": 5, "urgency": 4, "is_code_violation": True,
                 "recommended_year": 2027},
                {"description": "one-cent job", "cost_estimate_cents": 1,
                 "severity": 3, "urgency": 3, "recommended_year": 2027},
            ],
            plan_overrides={"title": "P", "start_year": 2027,
                            "horizon_years": 1},
            scenario_overrides={"name": "Exact",
                                "annual_budget_cents": 10700001,
                                "escalation_rate": 0.07})
        d1, d2 = workspace["deficiencies"]
        items = _items_by_deficiency(api, workspace["plan"]["id"])
        # round_half_up(10000001 * 1.07) = round_half_up(10700001.07) =
        # 10700001: exactly the annual budget -> FUNDED, remainder 0.
        assert items[d1["id"]]["escalated_cost_cents"] == 10700001
        assert items[d1["id"]]["funding_status"] == "FUNDED"
        # round_half_up(1 * 1.07) = round_half_up(1.07) = 1 > 0 -> UNFUNDED.
        assert items[d2["id"]]["escalated_cost_cents"] == 1
        assert items[d2["id"]]["funding_status"] == "UNFUNDED"
        assert get_capital_plan(
            workspace["plan"]["id"])["total_programmed_cents"] == 10700001


class TestBudgetBoundaries:
    def test_exact_budget_fit_is_funded(self, api):
        """PRD §3.7: "if that cost fits within the year's remaining budget, a
        **PlanLineItem** is created with `funding_status` `FUNDED`, the budget
        remainder is reduced by the cost, and the allocator moves on"
        PRD §3.7: "The plan's `total_programmed_cents` — always the sum of
        `escalated_cost_cents` over the plan's `FUNDED` line items"

        Design: Difficulty/boundary_precision_check/waterfall_exact_budget_fit_is_funded
        """
        workspace = setup_funded_plan(
            deficiency_specs=[
                {"description": "D1", "cost_estimate_cents": 30000000,
                 "severity": 3, "urgency": 3, "recommended_year": 2027},
                {"description": "D2", "cost_estimate_cents": 50000000,
                 "severity": 3, "urgency": 3, "recommended_year": 2027},
            ],
            plan_overrides={"title": "P", "start_year": 2027,
                            "horizon_years": 1},
            scenario_overrides={"name": "Exact",
                                "annual_budget_cents": 80000000,
                                "escalation_rate": 0.0},
            system_overrides={"system_category": "INTERIOR",
                              "name": "Shelving", "install_year": 2016,
                              "design_life_years": 20,
                              "replacement_cost_cents": 400000000,
                              "condition_rating": 4})
        d1, d2 = workspace["deficiencies"]
        items = _items_by_deficiency(api, workspace["plan"]["id"])
        assert items[d1["id"]]["funding_status"] == "FUNDED"
        assert items[d1["id"]]["escalated_cost_cents"] == 30000000
        # 50000000 <= 80000000 - 30000000 = 50000000: exact fit funds.
        assert items[d2["id"]]["funding_status"] == "FUNDED"
        assert items[d2["id"]]["escalated_cost_cents"] == 50000000
        assert get_capital_plan(
            workspace["plan"]["id"])["total_programmed_cents"] == 80000000, (
            "budget consumed to exactly zero")

    def test_one_cent_over_budget_is_unfunded(self, api):
        """PRD §3.7: "A single candidate whose escalated cost exceeds the
        entire annual budget is therefore simply `UNFUNDED` — it is not an
        error condition."
        PRD §3.7: "if it does not fit, the line item is still created but with
        `funding_status` `UNFUNDED`, and the remainder is unchanged."

        Design: Difficulty/boundary_precision_check/waterfall_exact_budget_fit_is_funded
        """
        workspace = setup_funded_plan(
            deficiency_specs=[
                {"description": "exact", "cost_estimate_cents": 50000000,
                 "severity": 4, "urgency": 4, "recommended_year": 2027},
                {"description": "over", "cost_estimate_cents": 50000001,
                 "severity": 3, "urgency": 3, "recommended_year": 2027},
            ],
            plan_overrides={"title": "P", "start_year": 2027,
                            "horizon_years": 1},
            scenario_overrides={"name": "S",
                                "annual_budget_cents": 50000000,
                                "escalation_rate": 0.0})
        d_exact, d_over = workspace["deficiencies"]
        items = _items_by_deficiency(api, workspace["plan"]["id"])
        assert items[d_exact["id"]]["funding_status"] == "FUNDED", (
            "50000000 <= 50000000: equality fits")
        assert items[d_over["id"]]["funding_status"] == "UNFUNDED", (
            "50000001 > 50000000 - 50000000 = 0 remaining: one cent over")
        assert items[d_over["id"]]["escalated_cost_cents"] == 50000001
        assert get_capital_plan(
            workspace["plan"]["id"])["total_programmed_cents"] == 50000000


class TestYearBuckets:
    def test_same_year_items_contend_for_shared_bucket(self, api):
        """PRD §3.7: "For each year, it starts with a full
        `annual_budget_cents` remaining and considers, in the sorted order,
        exactly those candidates whose `recommended_year` equals that plan
        year."
        PRD §3.7: "Candidates are ordered deterministically: highest
        `priority_score` first, with ties broken by earlier `created_at`"

        Design: Difficulty/resource_temporal_overlap/waterfall_year_bucket_capacity_overlap
        """
        workspace = setup_funded_plan(
            deficiency_specs=[
                {"description": "D1 beam corrosion",
                 "cost_estimate_cents": 70000000, "severity": 5, "urgency": 5,
                 "recommended_year": 2027},
                {"description": "D2 joint seals",
                 "cost_estimate_cents": 70000000, "severity": 4, "urgency": 4,
                 "recommended_year": 2027},
            ],
            plan_overrides={"title": "P", "start_year": 2027,
                            "horizon_years": 2},
            scenario_overrides={"name": "S",
                                "annual_budget_cents": 100000000,
                                "escalation_rate": 0.0},
            system_overrides={"system_category": "STRUCTURE", "name": "Frame",
                              "install_year": 1998, "design_life_years": 50,
                              "replacement_cost_cents": 900000000,
                              "condition_rating": 3})
        d1, d2 = workspace["deficiencies"]
        items = _items_by_deficiency(api, workspace["plan"]["id"])
        # Score 5.00 outranks 4.00, so D1 takes the 2027 bucket first.
        assert items[d1["id"]]["funding_status"] == "FUNDED"
        assert items[d1["id"]]["escalated_cost_cents"] == 70000000
        # 70000000 > 100000000 - 70000000 = 30000000 remaining in 2027.
        assert items[d2["id"]]["funding_status"] == "UNFUNDED"
        assert items[d2["id"]]["planned_year"] == 2027, (
            "items are programmed in their recommended year, not shifted")
        assert get_capital_plan(
            workspace["plan"]["id"])["total_programmed_cents"] == 70000000

    def test_different_years_do_not_contend(self, api):
        """PRD §3.7: "For each year, it starts with a full
        `annual_budget_cents` remaining and considers, in the sorted order,
        exactly those candidates whose `recommended_year` equals that plan
        year."

        Design: Difficulty/resource_temporal_overlap/waterfall_year_bucket_capacity_overlap
        """
        workspace = setup_funded_plan(
            deficiency_specs=[
                {"description": "year 2027", "cost_estimate_cents": 70000000,
                 "severity": 5, "urgency": 5, "recommended_year": 2027},
                {"description": "year 2028", "cost_estimate_cents": 70000000,
                 "severity": 4, "urgency": 4, "recommended_year": 2028},
            ],
            plan_overrides={"title": "P", "start_year": 2027,
                            "horizon_years": 2},
            scenario_overrides={"name": "S",
                                "annual_budget_cents": 100000000,
                                "escalation_rate": 0.0})
        d1, d2 = workspace["deficiencies"]
        items = _items_by_deficiency(api, workspace["plan"]["id"])
        # Each plan year restarts with a full budget: both fit.
        assert items[d1["id"]]["funding_status"] == "FUNDED"
        assert items[d1["id"]]["planned_year"] == 2027
        assert items[d2["id"]]["funding_status"] == "FUNDED"
        assert items[d2["id"]]["planned_year"] == 2028
        assert get_capital_plan(
            workspace["plan"]["id"])["total_programmed_cents"] == 140000000


class TestCandidatePool:
    def test_waterfall_input_set_excludes_out_of_horizon_and_corrected(
            self, api):
        """PRD §3.7: "The candidate pool is every deficiency of the plan's
        facility whose `remediation_status` is `OPEN` or `DEFERRED`, whose
        owning system is not `RETIRED`, and whose `recommended_year` falls
        inside the plan horizon — that is, no earlier than `start_year` and no
        later than `start_year` plus `horizon_years` minus 1."

        Design: Corner/calculations/waterfall_input_set_excludes_out_of_horizon_and_corrected
        """
        facility, system = setup_facility_with_system(
            {"system_category": "HVAC", "name": "S", "install_year": 2010,
             "design_life_years": 25, "replacement_cost_cents": 500000000,
             "condition_rating": 3})
        d_in = create_deficiency(system["id"], description="in",
                                 cost_estimate_cents=10000000, severity=3,
                                 urgency=3, recommended_year=2027)
        d_out = create_deficiency(system["id"], description="out",
                                  cost_estimate_cents=10000000, severity=3,
                                  urgency=3, recommended_year=2035)
        d_done = create_deficiency(system["id"], description="done",
                                   cost_estimate_cents=10000000, severity=3,
                                   urgency=3, recommended_year=2027)
        remediate_to_corrected(d_done["id"])

        plan = create_draft_plan(facility["id"], title="P", start_year=2027,
                                 horizon_years=3)
        scenario = create_scenario(plan["id"], name="S",
                                   annual_budget_cents=100000000,
                                   escalation_rate=0.0)
        run_scenario(scenario["id"])

        items = list_line_items(plan["id"])
        assert [item["deficiency_id"] for item in items] == [d_in["id"]], (
            "only the in-horizon OPEN finding enters the candidate pool")
        assert items[0]["funding_status"] == "FUNDED"
        assert get_capital_plan(
            plan["id"])["total_programmed_cents"] == 10000000

    def test_escalated_cost_base_year_boundary_no_escalation(self, api):
        """PRD §3.7: "the number of compounding years is the planned year
        minus 2026, and the escalated amount is the estimate multiplied by
        one-plus-the-rate raised to that power, rounded half-up to a whole
        cent exactly once, before any budget comparison."

        Design: Corner/calculations/escalated_cost_boundary_year_base_year_no_escalation
        """
        workspace = setup_funded_plan(
            deficiency_specs=[{"description": "d",
                               "cost_estimate_cents": 25000000,
                               "severity": 3, "urgency": 3,
                               "recommended_year": 2026}],
            plan_overrides={"title": "P", "start_year": 2026,
                            "horizon_years": 2},
            scenario_overrides={"name": "S",
                                "annual_budget_cents": 100000000,
                                "escalation_rate": 0.10},
            system_overrides={"system_category": "HVAC", "name": "S",
                              "install_year": 2010, "design_life_years": 25,
                              "replacement_cost_cents": 500000000,
                              "condition_rating": 3})
        items = list_line_items(workspace["plan"]["id"])
        assert len(items) == 1
        # planned_year 2026 - base year 2026 = 0 -> (1.10)^0 == 1.
        assert items[0]["escalated_cost_cents"] == 25000000
        assert items[0]["funding_status"] == "FUNDED"


class TestScenarioLifecycle:
    def test_run_supersedes_prior_run_and_removes_its_items(self, api):
        """PRD §3.7: "A run has one supersession cascade. Any other scenario
        of the same plan already in `RUN` status moves to `SUPERSEDED`, and
        all of its non-removed line items move to `REMOVED`. The plan's
        `total_programmed_cents` — always the sum of `escalated_cost_cents`
        over the plan's `FUNDED` line items — is then recomputed, and the
        plan's `version` increments."

        Design: Difficulty/transitive_cascade/scenario_run_supersedes_prior_run_removing_its_line_items
        """
        facility, system = setup_facility_with_system(
            {"system_category": "HVAC", "name": "RTU-1", "install_year": 2009,
             "design_life_years": 20, "replacement_cost_cents": 60000000,
             "condition_rating": 3})
        deficiency = create_deficiency(
            system["id"], description="Heat exchanger crack",
            cost_estimate_cents=40000000, severity=3, urgency=3,
            recommended_year=2027)
        plan = create_draft_plan(facility["id"], title="P", start_year=2027,
                                 horizon_years=1)
        scen_a = create_scenario(plan["id"], name="A",
                                 annual_budget_cents=50000000,
                                 escalation_rate=0.0)
        scen_b = create_scenario(plan["id"], name="B",
                                 annual_budget_cents=30000000,
                                 escalation_rate=0.0)

        run_scenario(scen_a["id"])
        items_a = list_line_items(plan["id"])
        assert len(items_a) == 1
        assert items_a[0]["funding_status"] == "FUNDED"
        assert get_capital_plan(
            plan["id"])["total_programmed_cents"] == 40000000

        run_scenario(scen_b["id"])  # reads the plan's fresh version
        scen_a_after = get_funding_scenario(api, scen_a["id"])
        assert scen_a_after["status"] == "SUPERSEDED", (
            "the later run supersedes the previously run sibling")

        items = list_line_items(plan["id"])
        by_scenario = {}
        for item in items:
            by_scenario.setdefault(item["funding_scenario_id"], item)
        assert by_scenario[scen_a["id"]]["funding_status"] == "REMOVED", (
            "the supersede itself moves scenario A's line item to REMOVED")
        assert by_scenario[scen_b["id"]]["funding_status"] == "UNFUNDED", (
            "40000000 > 30000000 annual budget under scenario B")
        assert by_scenario[scen_b["id"]]["deficiency_id"] == deficiency["id"]
        assert get_capital_plan(plan["id"])["total_programmed_cents"] == 0, (
            "plan total recomputed from the remaining FUNDED set")

    def test_rerun_or_run_on_moved_on_plan_rejected(self, api):
        """PRD §3.7: "It requires the scenario to still be `CONFIGURED` and
        the owning plan to still be `DRAFT` — running against a plan that has
        moved on is `ERR_INVALID_STATE`"

        Design: Difficulty/transitive_cascade/scenario_run_supersedes_prior_run_removing_its_line_items
        """
        workspace = setup_funded_plan(
            deficiency_specs=[{"description": "d",
                               "cost_estimate_cents": 40000000,
                               "severity": 3, "urgency": 3,
                               "recommended_year": 2027}],
            plan_overrides={"title": "P", "start_year": 2027,
                            "horizon_years": 1},
            scenario_overrides={"name": "A",
                                "annual_budget_cents": 50000000,
                                "escalation_rate": 0.0})
        scenario_id = workspace["scenario"]["id"]
        plan_id = workspace["plan"]["id"]
        # The scenario is already RUN (terminal): a second run is illegal.
        rerun = api.run_funding_scenario(
            scenario_id, run_scenario_payload(
                get_capital_plan(plan_id)["version"]), PLANNER)
        validate_error(rerun, ApiErrorId.ERR_INVALID_STATE)

        # A fresh scenario under a plan that has left DRAFT cannot run.
        scen_b = create_scenario(plan_id, name="B",
                                 annual_budget_cents=50000000,
                                 escalation_rate=0.0)
        submit_plan(plan_id)
        moved_on = api.run_funding_scenario(
            scen_b["id"], run_scenario_payload(
                get_capital_plan(plan_id)["version"]), PLANNER)
        validate_error(moved_on, ApiErrorId.ERR_INVALID_STATE)


class TestScenarioRules:
    @pytest.mark.parametrize("overrides", [
        {"annual_budget_cents": 0},          # non-positive budget
        {"annual_budget_cents": -5},
        {"escalation_rate": 0.26},           # above the 0.25 ceiling
        {"escalation_rate": -0.01},          # below the 0 floor
    ], ids=["zero-budget", "negative-budget", "rate-above", "rate-below"])
    def test_invalid_budget_or_rate_rejected(self, api, overrides):
        """PRD §3.7: "The budget must be a strictly positive integer and the
        escalation rate must lie between 0 and 0.25 inclusive; a non-positive
        budget or an out-of-range rate is rejected with `ERR_INVALID_BUDGET`."

        Design: Corner/validations/invalid_budget_zero_rejected
        """
        facility = create_facility()
        plan = create_draft_plan(facility["id"], title="P", start_year=2027,
                                 horizon_years=1)
        payload = create_funding_scenario_payload(plan["id"], name="Zero",
                                                  **overrides)
        resp = api.create_funding_scenario(payload, PLANNER)
        validate_error(resp, ApiErrorId.ERR_INVALID_BUDGET)

    def test_occ_stale_capital_plan_version_rejected(self, api):
        """PRD §2.6: "Second, running a funding scenario requires the request
        to carry `expected_capital_plan_version`, set to the owning plan's
        `version` as the client last observed it. A scenario run rewrites the
        plan's line items and bumps the plan's version, so a run issued from a
        stale plan view must be rejected with `ERR_STALE_VERSION` (HTTP 412)
        rather than allowed to silently double-allocate a program on top of a
        run it never saw."

        Design: Corner/cross_cutting_layers/occ_stale_capital_plan_version_rejected
        """
        _facility, _system, _deficiency = setup_system_with_deficiency(
            {"description": "d", "cost_estimate_cents": 5000000,
             "severity": 3, "urgency": 3, "recommended_year": 2027})
        facility = get_facility(_facility["id"])
        plan = create_draft_plan(facility["id"], title="P", start_year=2027,
                                 horizon_years=1)
        observed_version = plan["version"]
        scen1 = create_scenario(plan["id"], name="S1",
                                annual_budget_cents=10000000,
                                escalation_rate=0.0)
        scen2 = create_scenario(plan["id"], name="S2",
                                annual_budget_cents=10000000,
                                escalation_rate=0.0)

        first = api.run_funding_scenario(
            scen1["id"], run_scenario_payload(observed_version), PLANNER)
        run1 = validate_success(first, 200)
        assert_funding_scenario(run1)
        assert run1["status"] == "RUN"
        assert get_capital_plan(plan["id"])["version"] > observed_version, (
            "the run bumps the plan version")

        stale = api.run_funding_scenario(
            scen2["id"], run_scenario_payload(observed_version), PLANNER)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
