"""Sampling populations, the stratified allocation and the seven-step fee."""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import (
    ERR_ASSESSMENT_BUDGET_EXCEEDED,
    ERR_EMPTY_SAMPLE_POPULATION,
    ERR_STALE_ENGAGEMENT_VERSION,
)
from test_helpers.assertions import (
    assert_coverage_ratio,
    assert_fee_breakdown,
    assert_money,
    assert_stratum_allocations,
    assert_total_count,
    find_row,
)
from test_helpers.factories import sampling_plan_payload
from test_helpers.fixtures import (
    Scenario,
    add_component,
    build_registry,
    declare_segment,
    draw_plan,
    engagement_version,
    open_engagement,
    plan_segmentation,
    read_engagement,
    record_verdict,
    register_assessor,
    validated_segment,
)
from test_helpers.test_users import make_lead_headers

RETAIL_STORE = "RETAIL_STORE"
DATA_CENTER = "DATA_CENTER"


def _divergent_inventory(api, budget: float = 200000.00) -> Scenario:
    """Build an engagement whose declared and effective populations disagree.

    Six hosts sit in a validated cardholder zone across two data centres and
    four point-of-sale terminals sit in a retail zone the client declared out of
    scope; that retail zone then fails its segmentation test.
    """
    scenario = build_registry(api)
    lead_id = scenario["lead_id"]
    engagement = open_engagement(
        api,
        lead_id,
        qa_reviewer_id=scenario["qa_id"],
        approved_budget_amount=budget,
    )
    scenario["engagement"] = engagement
    scenario["engagement_id"] = engagement["id"]
    engagement_id = engagement["id"]

    cde = validated_segment(
        api,
        engagement_id,
        lead_id,
        name="CDE-CORE",
        segment_class="CDE",
        test_method="PEN_TEST",
        planned_date="2026-08-05",
    )
    store = declare_segment(
        api, engagement_id, lead_id, "STORE-POS", segment_class="OUT_OF_SCOPE"
    )
    plan_segmentation(
        api,
        store["id"],
        lead_id,
        test_method="TRAFFIC_ANALYSIS",
        planned_date="2026-08-06",
    )

    components = {}
    for hostname in ("srv-01", "srv-02", "srv-03"):
        components[hostname] = add_component(
            api,
            engagement_id,
            lead_id,
            cde["id"],
            hostname,
            component_type="SERVER",
            function_class="SECURITY_SERVICE",
            facility_name="DC-EAST",
            facility_type=DATA_CENTER,
        )
    for hostname in ("app-01", "app-02"):
        components[hostname] = add_component(
            api,
            engagement_id,
            lead_id,
            cde["id"],
            hostname,
            component_type="APPLICATION",
            function_class="PAYMENT_APPLICATION",
            stores_chd=True,
            facility_name="DC-WEST",
            facility_type=DATA_CENTER,
        )
    components["db-01"] = add_component(
        api,
        engagement_id,
        lead_id,
        cde["id"],
        "db-01",
        component_type="DATABASE",
        function_class="DATA_STORE",
        stores_chd=True,
        facility_name="DC-WEST",
        facility_type=DATA_CENTER,
    )
    for hostname in ("pos-01", "pos-02", "pos-03", "pos-04"):
        components[hostname] = add_component(
            api,
            engagement_id,
            lead_id,
            store["id"],
            hostname,
            component_type="POS_TERMINAL",
            function_class="CONNECTED_SUPPORT",
            facility_name="RETAIL-12",
            facility_type=RETAIL_STORE,
        )

    # The retail boundary is disproven, which drags its terminals into scope.
    record_verdict(api, store["id"], lead_id, outcome="FAIL", note="Flat network.")

    scenario["cde_segment_id"] = cde["id"]
    scenario["store_segment_id"] = store["id"]
    scenario["components"] = components
    scenario["component_ids"] = {name: row["id"] for name, row in components.items()}
    return scenario


class TestSamplingPlanVariantDivergence:
    """The two plan variants read two different component populations."""

    def test_preliminary_plan_draws_the_declared_population_only(self, api):
        """A preliminary draw ignores the failed boundary entirely.

        PRD: A `PRELIMINARY` plan draws from the components of the engagement whose
        `declared_scope_class` is `CDE` or `CONNECTED` — the classes implied by the
        zones' own declared classes at the time each component was inventoried,
        ignoring every later segmentation verdict.

        Design: Difficulty/dual_variant_calc/sampling_plan_preliminary_vs_final_scope_divergence
        """
        scenario = _divergent_inventory(api)
        plan = draw_plan(
            api,
            scenario["engagement_id"],
            scenario["lead_id"],
            plan_variant="PRELIMINARY",
        )

        assert plan["plan_variant"] == "PRELIMINARY"
        assert plan["eligible_component_count"] == 6
        assert_stratum_allocations(
            plan,
            {
                "SERVER": 2,
                "NETWORK_DEVICE": 0,
                "POS_TERMINAL": 0,
                "APPLICATION": 2,
                "DATABASE": 1,
            },
        )
        assert plan["component_sample_size"] == 5
        assert_coverage_ratio(plan["coverage_ratio"], 0.8333)
        assert plan["facility_population_count"] == 2
        assert plan["facility_sample_size"] == 1
        assert plan["sampled_facility_names"] == ["DC-EAST"]
        assert plan["status"] == "ACTIVE"

        # The terminals are outside the declared population, so none is selected.
        pos_01 = validate_success(
            api.get_system_component(
                scenario["component_ids"]["pos-01"],
                make_lead_headers(scenario["lead_id"]),
            )
        )
        assert pos_01["declared_scope_class"] == "OUT_OF_SCOPE"
        assert pos_01["scope_class"] == "CDE"
        assert pos_01["in_sample"] is False
        assert pos_01["sampling_stratum"] is None

    def test_final_plan_draws_the_effective_population_and_supersedes(self, api):
        """The final draw absorbs the terminals the failed boundary pulled in.

        PRD: A `FINAL` plan draws from the components whose `scope_class` is `CDE`
        or `CONNECTED` — the effective classes after every segmentation cascade has
        been applied.

        Design: Difficulty/dual_variant_calc/sampling_plan_preliminary_vs_final_scope_divergence
        """
        scenario = _divergent_inventory(api)
        lead_id = scenario["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        preliminary = draw_plan(
            api, scenario["engagement_id"], lead_id, plan_variant="PRELIMINARY"
        )

        final = draw_plan(
            api, scenario["engagement_id"], lead_id, plan_variant="FINAL"
        )

        assert final["plan_variant"] == "FINAL"
        assert final["eligible_component_count"] == 10
        assert_stratum_allocations(
            final,
            {
                "SERVER": 2,
                "NETWORK_DEVICE": 0,
                "POS_TERMINAL": 2,
                "APPLICATION": 2,
                "DATABASE": 1,
            },
        )
        assert final["component_sample_size"] == 7
        assert_coverage_ratio(final["coverage_ratio"], 0.7000)
        assert final["facility_population_count"] == 3
        assert final["facility_sample_size"] == 2
        assert final["sampled_facility_names"] == ["DC-EAST", "DC-WEST"]
        assert final["status"] == "ACTIVE"

        # The earlier draw is retired, not deleted, and the engagement repoints.
        retired = validate_success(api.get_sampling_plan(preliminary["id"], lead_headers))
        assert retired["status"] == "SUPERSEDED"
        assert retired["superseded_at"] is not None
        engagement = read_engagement(api, scenario["engagement_id"], lead_id)
        assert engagement["active_sampling_plan_id"] == final["id"]
        assert engagement["active_plan_stale"] is False

        selected = sorted(
            row["hostname"]
            for row in validate_success(
                api.list_system_components(
                    lead_headers,
                    {"engagement_id": scenario["engagement_id"], "in_sample": True},
                )
            )
        )
        assert selected == [
            "app-01",
            "app-02",
            "db-01",
            "pos-01",
            "pos-02",
            "srv-01",
            "srv-02",
        ]
        pos_01 = validate_success(
            api.get_system_component(scenario["component_ids"]["pos-01"], lead_headers)
        )
        assert pos_01["in_sample"] is True
        assert pos_01["sampling_stratum"] == "POS_TERMINAL"

    def test_each_variant_prices_its_own_sample(self, api):
        """The two populations produce two different fees on the same inventory.

        PRD: Every plan re-prices the engagement, because the fee is a function of
        the sample.

        Design: Difficulty/dual_variant_calc/sampling_plan_preliminary_vs_final_scope_divergence
        """
        scenario = _divergent_inventory(api)
        lead_id = scenario["lead_id"]

        draw_plan(api, scenario["engagement_id"], lead_id, plan_variant="PRELIMINARY")
        # The base of 62500.00 surcharges to 67500.00 and discounts by 2025.00.
        priced_preliminary = read_engagement(api, scenario["engagement_id"], lead_id)
        assert_fee_breakdown(
            priced_preliminary,
            estimated_hours=250,
            assessment_fee_total=65475.00,
        )

        draw_plan(api, scenario["engagement_id"], lead_id, plan_variant="FINAL")
        # The base of 76000.00 surcharges to 82080.00 and discounts by 2462.40.
        priced_final = read_engagement(api, scenario["engagement_id"], lead_id)
        assert_fee_breakdown(
            priced_final,
            estimated_hours=304,
            assessment_fee_total=79617.60,
        )
        assert (
            priced_final["assessment_fee_total"]
            != priced_preliminary["assessment_fee_total"]
        )


def _one_host_per_facility(api, host_count: int = 12) -> Scenario:
    """Inventory one server per facility so the facility term dominates the fee."""
    scenario = build_registry(api)
    lead_id = scenario["lead_id"]
    engagement = open_engagement(api, lead_id, qa_reviewer_id=scenario["qa_id"])
    scenario["engagement_id"] = engagement["id"]
    segment = validated_segment(api, engagement["id"], lead_id, name="CDE-CORE")
    scenario["segment_id"] = segment["id"]
    for index in range(1, host_count + 1):
        add_component(
            api,
            engagement["id"],
            lead_id,
            segment["id"],
            "srv-%02d" % index,
            component_type="SERVER",
            function_class="SECURITY_SERVICE",
            facility_name="FAC-%02d" % index,
            facility_type=DATA_CENTER,
        )
    return scenario


class TestAssessmentFeeSevenSteps:
    """The fee walks its seven steps in one fixed order."""

    def test_level_one_worked_example_prices_at_the_published_figures(
        self, api, sampled_engagement
    ):
        """The published 226-hour example is reproduced step by step.

        PRD: A 226-hour `L1` engagement has a base of 56500.00, a surcharge of
        4520.00 and a subtotal of 61020.00, which lands in the three-percent tier
        for a discount of 1830.60 and an `assessment_fee_total` of 59189.40.

        Design: Difficulty/combinatorial_formula/assessment_fee_total_seven_step_ordering
        """
        plan = sampled_engagement["plan"]

        assert plan["component_sample_size"] == 3
        assert plan["facility_sample_size"] == 1
        priced = read_engagement(
            api, sampled_engagement["engagement_id"], sampled_engagement["lead_id"]
        )
        # The base of 56500.00 surcharges to 61020.00 and discounts by 1830.60.
        assert_fee_breakdown(
            priced,
            estimated_hours=226,
            assessment_fee_total=59189.40,
        )
        # Keying the tier on the base amount would have reported the subtotal.
        assert priced["assessment_fee_total"] != pytest.approx(61020.00, abs=0.01)

    def test_non_level_one_engagement_carries_no_surcharge(self, api):
        """A level-four merchant pays no onsite surcharge, so no tier is reached.

        PRD: Step three computes an onsite surcharge of eight percent of that base
        amount, rounded half up to 2 decimal places, but only when the engagement's
        `merchant_level` is `L1`; for `L2`, `L3` and `L4` the surcharge is 0.00.

        Design: Difficulty/combinatorial_formula/assessment_fee_total_seven_step_ordering
        """
        scenario = build_registry(api)
        engagement = open_engagement(
            api,
            scenario["lead_id"],
            qa_reviewer_id=scenario["qa_id"],
            merchant_level="L4",
        )
        segment = validated_segment(api, engagement["id"], scenario["lead_id"])
        for hostname, component_type in (
            ("app-01", "SERVER"),
            ("pay-01", "APPLICATION"),
            ("pay-02", "APPLICATION"),
        ):
            add_component(
                api,
                engagement["id"],
                scenario["lead_id"],
                segment["id"],
                hostname,
                component_type=component_type,
                function_class="PAYMENT_APPLICATION",
            )

        draw_plan(api, engagement["id"], scenario["lead_id"])

        # A base of 56500.00 with no surcharge stays below the 60000 tier, so the
        # discount is 0.00 and the total is the base itself.
        priced = read_engagement(api, engagement["id"], scenario["lead_id"])
        assert_fee_breakdown(
            priced,
            estimated_hours=226,
            assessment_fee_total=56500.00,
        )

    def test_discount_tier_is_keyed_on_the_post_surcharge_subtotal(self, api):
        """A base below the tier threshold still earns the tier once surcharged.

        PRD: The tier lookup reads the post-surcharge subtotal, not the
        pre-surcharge base amount; and the surcharge is applied before the
        discount, never after it.

        Design: Difficulty/combinatorial_formula/assessment_fee_total_seven_step_ordering
        """
        scenario = _one_host_per_facility(api, host_count=12)

        plan = draw_plan(api, scenario["engagement_id"], scenario["lead_id"])

        assert plan["eligible_component_count"] == 12
        assert plan["component_sample_size"] == 3
        assert plan["facility_population_count"] == 12
        assert plan["facility_sample_size"] == 5
        assert plan["sampled_facility_names"] == [
            "FAC-01",
            "FAC-02",
            "FAC-03",
            "FAC-04",
            "FAC-05",
        ]
        # The base of 86500.00 sits below the six-percent threshold; the
        # surcharged subtotal of 93420.00 clears it, discounting by 5605.20.
        priced = read_engagement(api, scenario["engagement_id"], scenario["lead_id"])
        assert_fee_breakdown(
            priced,
            estimated_hours=346,
            assessment_fee_total=87814.80,
        )
        # Keying the tier on the pre-surcharge base would have reported 83905.00.
        assert priced["assessment_fee_total"] != pytest.approx(83905.00, abs=0.01)


class TestSamplePopulationBoundary:
    """An empty population is refused; a population of one draws one."""

    def test_an_engagement_with_no_in_scope_component_cannot_be_sampled(self, api):
        """Both variants refuse to draw when nothing qualifies.

        PRD: Whichever variant is chosen, the size of its population is recorded on
        the plan as `eligible_component_count`, and a variant whose eligible
        population is empty — no component qualifying as either `CDE` or
        `CONNECTED` — is refused with `ERR_EMPTY_SAMPLE_POPULATION`.

        Design: Difficulty/boundary_precision_check/empty_eligible_population_zero_versus_one_boundary
        """
        scenario = build_registry(api)
        lead_id = scenario["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        engagement = open_engagement(
            api,
            lead_id,
            qa_reviewer_id=scenario["qa_id"],
            client_legal_name="Harbor Fuel Stops LLC",
        )
        store = validated_segment(
            api,
            engagement["id"],
            lead_id,
            name="STORE-ONLY",
            segment_class="OUT_OF_SCOPE",
            test_method="TRAFFIC_ANALYSIS",
            planned_date="2026-08-04",
        )
        add_component(
            api,
            engagement["id"],
            lead_id,
            store["id"],
            "pos-01",
            component_type="POS_TERMINAL",
            function_class="CONNECTED_SUPPORT",
            facility_name="RETAIL-40",
            facility_type=RETAIL_STORE,
        )
        version = engagement_version(api, engagement["id"], lead_id)

        for variant in ("FINAL", "PRELIMINARY"):
            response = api.create_sampling_plan(
                engagement["id"],
                sampling_plan_payload(version, plan_variant=variant),
                lead_headers,
            )
            validate_error(response, ERR_EMPTY_SAMPLE_POPULATION, 422)

        assert_total_count(
            api.list_sampling_plans(lead_headers, {"engagement_id": engagement["id"]}), 0
        )
        after = read_engagement(api, engagement["id"], lead_id)
        assert after["active_sampling_plan_id"] is None
        assert after["version"] == version

    def test_a_population_of_one_draws_exactly_one(self, api):
        """A single eligible host clears the boundary and is drawn on its own.

        PRD: The per-stratum minimum is applied before the population cap, so a
        stratum whose population is exactly 1 contributes 1, not 2.

        Design: Difficulty/boundary_precision_check/empty_eligible_population_zero_versus_one_boundary
        """
        scenario = build_registry(api)
        lead_id = scenario["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        engagement = open_engagement(
            api,
            lead_id,
            qa_reviewer_id=scenario["qa_id"],
            client_legal_name="Harbor Fuel Stops LLC",
        )
        store = validated_segment(
            api,
            engagement["id"],
            lead_id,
            name="STORE-ONLY",
            segment_class="OUT_OF_SCOPE",
            test_method="TRAFFIC_ANALYSIS",
            planned_date="2026-08-04",
        )
        pos = add_component(
            api,
            engagement["id"],
            lead_id,
            store["id"],
            "pos-01",
            component_type="POS_TERMINAL",
            function_class="CONNECTED_SUPPORT",
            facility_name="RETAIL-40",
            facility_type=RETAIL_STORE,
        )
        cde = validated_segment(
            api,
            engagement["id"],
            lead_id,
            name="CDE-CORE",
            test_method="CONFIG_REVIEW",
            planned_date="2026-08-06",
        )
        host = add_component(
            api,
            engagement["id"],
            lead_id,
            cde["id"],
            "app-01",
            component_type="SERVER",
            function_class="PAYMENT_APPLICATION",
            stores_chd=True,
        )

        plan = draw_plan(api, engagement["id"], lead_id)

        assert plan["eligible_component_count"] == 1
        assert plan["component_sample_size"] == 1
        assert_stratum_allocations(
            plan,
            {
                "SERVER": 1,
                "NETWORK_DEVICE": 0,
                "POS_TERMINAL": 0,
                "APPLICATION": 0,
                "DATABASE": 0,
            },
        )
        assert_coverage_ratio(plan["coverage_ratio"], 1.0000)
        assert plan["facility_population_count"] == 1
        assert plan["facility_sample_size"] == 1
        assert plan["sampled_facility_names"] == ["DC-EAST"]
        priced = read_engagement(api, engagement["id"], lead_id)
        assert_money(priced["assessment_fee_total"], 54540.00)
        assert priced["estimated_hours"] == 202

        drawn = validate_success(api.get_system_component(host["id"], lead_headers))
        assert drawn["in_sample"] is True
        assert drawn["sampling_stratum"] == "SERVER"
        untouched = validate_success(api.get_system_component(pos["id"], lead_headers))
        assert untouched["in_sample"] is False
        assert untouched["sampling_stratum"] is None

    @pytest.mark.parametrize(
        "facility_count,expected_sample",
        [(3, 2), (5, 2)],
    )
    def test_facility_sample_ladder_at_its_published_points(
        self, api, facility_count, expected_sample
    ):
        """The facility ladder is checked at the two published populations.

        PRD: A population of one facility yields a sample of one; a population of
        three yields two; a population of five yields two.

        Design: Difficulty/boundary_precision_check/empty_eligible_population_zero_versus_one_boundary
        """
        scenario = _one_host_per_facility(api, host_count=facility_count)

        plan = draw_plan(api, scenario["engagement_id"], scenario["lead_id"])

        assert plan["facility_population_count"] == facility_count
        assert plan["facility_sample_size"] == expected_sample
        assert plan["sampled_facility_names"] == [
            "FAC-%02d" % index for index in range(1, expected_sample + 1)
        ]


class TestStaleVersionOutranksTheBudgetCeiling:
    """A stale engagement version is answered before the fee ceiling is read."""

    def test_stale_version_wins_over_the_budget_refusal(self, api):
        """The very same request answers 412 when stale and 422 when current.

        PRD: On sampling-plan creation, a stale `expected_engagement_version`
        surfaces from rung 10 even when the plan the request would have produced
        would also have driven the fee above `approved_budget_amount` — the
        concurrency refusal wins over the fiscal refusal.

        Design: Difficulty/priority_pair_validation_conflict/stale_engagement_version_412_beats_budget_exceeded_422
        """
        scenario = _divergent_inventory(api, budget=70000.00)
        lead_id = scenario["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        engagement_id = scenario["engagement_id"]
        first_version = engagement_version(api, engagement_id, lead_id)

        preliminary = draw_plan(
            api,
            engagement_id,
            lead_id,
            plan_variant="PRELIMINARY",
            expected_engagement_version=first_version,
        )
        assert_money(
            read_engagement(api, engagement_id, lead_id)["assessment_fee_total"],
            65475.00,
        )

        # The plan this payload would draw prices at 79617.60, over the 70000.00
        # ceiling, yet the version it carries is already one behind.
        stale = api.create_sampling_plan(
            engagement_id,
            sampling_plan_payload(first_version, plan_variant="FINAL"),
            lead_headers,
        )
        validate_error(stale, ERR_STALE_ENGAGEMENT_VERSION, 412)

        current_version = engagement_version(api, engagement_id, lead_id)
        assert current_version != first_version
        over_budget = api.create_sampling_plan(
            engagement_id,
            sampling_plan_payload(current_version, plan_variant="FINAL"),
            lead_headers,
        )
        validate_error(over_budget, ERR_ASSESSMENT_BUDGET_EXCEEDED, 422)

        assert_total_count(
            api.list_sampling_plans(lead_headers, {"engagement_id": engagement_id}), 1
        )
        after = read_engagement(api, engagement_id, lead_id)
        assert after["active_sampling_plan_id"] == preliminary["id"]
        assert_money(after["assessment_fee_total"], 65475.00)
        assert after["version"] == current_version

    def test_the_stale_refusal_leaves_the_active_plan_in_place(self, api):
        """Nothing is superseded and no flag moves when the version check fails.

        PRD: If that value does not equal the engagement's current `version`, the
        creation is refused with `ERR_STALE_ENGAGEMENT_VERSION` (HTTP 412).

        Design: Difficulty/priority_pair_validation_conflict/stale_engagement_version_412_beats_budget_exceeded_422
        """
        scenario = _divergent_inventory(api, budget=70000.00)
        lead_id = scenario["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        engagement_id = scenario["engagement_id"]
        first_version = engagement_version(api, engagement_id, lead_id)
        preliminary = draw_plan(
            api,
            engagement_id,
            lead_id,
            plan_variant="PRELIMINARY",
            expected_engagement_version=first_version,
        )

        refused = api.create_sampling_plan(
            engagement_id,
            sampling_plan_payload(first_version, plan_variant="FINAL"),
            lead_headers,
        )
        validate_error(refused, ERR_STALE_ENGAGEMENT_VERSION, 412)

        held = validate_success(api.get_sampling_plan(preliminary["id"], lead_headers))
        assert held["status"] == "ACTIVE"
        assert held["superseded_at"] is None
        assert held["version"] == preliminary["version"]
        engagement = read_engagement(api, engagement_id, lead_id)
        assert engagement["active_plan_stale"] is False
        assert engagement["active_sampling_plan_id"] == preliminary["id"]
        terminals = validate_success(
            api.list_system_components(
                lead_headers,
                {"engagement_id": engagement_id, "component_type": "POS_TERMINAL"},
            )
        )
        assert [row["in_sample"] for row in terminals] == [False, False, False, False]
