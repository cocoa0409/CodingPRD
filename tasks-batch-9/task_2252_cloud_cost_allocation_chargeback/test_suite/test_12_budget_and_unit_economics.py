"""Budgets and drivers: forecast accuracy, the pinned tier and the provisioning gate."""

from test_helpers import (
    ANALYST_HEADERS,
    CONTROLLER_HEADERS,
    OWNER_3,
    OWNER_6,
    ApiErrorId,
    assert_budget_evaluation,
    assert_cents,
    assert_pct,
    factories,
    fixtures,
    find_by,
    make_business_unit_owner_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import (
    AUGUST_END,
    AUGUST_FIFTH_UTC,
    AUGUST_START,
    SEPTEMBER_END,
    SEPTEMBER_START,
)

REVISION_TRAIL = (24000, 17000, 28000)


def _twin_budgets(api):
    """Two budgets over abutting months, identical but for their accuracy basis.

    Analytics BU bills 21000 cents in August and another 21000 in September, so
    each budget evaluates against the same 21000-cent actual, the same 25610-cent
    envelope and the same three-entry forecast trail.  The August budget scores on
    `MAPE_BASIS`, the September one on `PERIOD_END_BASIS`.
    """
    fixtures.set_clock(api, AUGUST_FIFTH_UTC)
    unit = fixtures.create_chargeback_unit(api, "Analytics BU", "CC-300", headcount=12)
    policy = fixtures.create_active_policy(api, "core-tags")
    resource = fixtures.provision_resource(
        api,
        policy["id"],
        unit["id"],
        OWNER_3,
        resource_kind="COMPUTE",
        requested_tags={"team": "analytics", "environment": "prod", "application": "warehouse"},
        monthly_run_rate_cents=21000,
    )
    for period_start, period_end in ((AUGUST_START, AUGUST_END), (SEPTEMBER_START, SEPTEMBER_END)):
        fixtures.create_cost_record(
            api,
            21000,
            resource_kind="COMPUTE",
            billing_period_start=period_start,
            billing_period_end=period_end,
            cloud_resource_id=resource["id"],
        )

    budgets = {}
    for basis, (period_start, period_end) in (
        ("MAPE_BASIS", (AUGUST_START, AUGUST_END)),
        ("PERIOD_END_BASIS", (SEPTEMBER_START, SEPTEMBER_END)),
    ):
        budget = fixtures.create_budget(
            api,
            unit["id"],
            amount_cents=25610,
            forecast_cents=26000,
            period_start=period_start,
            period_end=period_end,
            accuracy_basis=basis,
        )
        for forecast_cents in REVISION_TRAIL:
            budget = validate_success(
                api.revise_budget(
                    budget["id"],
                    {
                        "expected_budget_version": budget["version"],
                        "forecast_cents": forecast_cents,
                    },
                    CONTROLLER_HEADERS,
                )
            )
        assert budget["forecast_history"] == [26000, 24000, 17000]
        assert budget["revision_count"] == 3
        assert_cents(budget["forecast_cents"], 28000, "forecast_cents")
        budgets[basis] = validate_success(api.activate_budget(budget["id"], CONTROLLER_HEADERS))

    return {"unit": unit, "budgets": budgets}


def test_the_mape_basis_scores_the_revision_trail_and_ignores_the_standing_forecast(api):
    """Averaging 5000, 3000 and 4000 cents of error against 21000 gives 80.95.

    PRD §3.9: "Under `MAPE_BASIS` — the default, which scores the whole revision
    trail — take each historical forecast in `forecast_history`, compute the
    absolute difference between it and `actual_spend_cents` divided by
    `actual_spend_cents`, average those values across every entry in the trail,
    multiply the mean by 100, subtract the result from 100, and round half up to
    two decimal places; the current standing `forecast_cents` is deliberately
    excluded from this trail."

    Design: Difficulty/dual_variant_calc/budget_forecast_accuracy_mape_vs_period_end_divergence
    """
    built = _twin_budgets(api)
    budget_id = built["budgets"]["MAPE_BASIS"]["id"]

    evaluated = validate_success(api.evaluate_budget(budget_id, CONTROLLER_HEADERS))
    assert_budget_evaluation(
        evaluated,
        actual_spend_cents=21000,
        variance_cents=-4610,
        variance_pct=-18.00,
        warning_flag=False,
        status="ACTIVE",
        forecast_accuracy_pct=80.95,
        accuracy_basis_applied="MAPE_BASIS",
    )
    assert evaluated["forecast_history"] == [26000, 24000, 17000]
    assert_cents(evaluated["forecast_cents"], 28000, "forecast_cents")

    period_end_budget = validate_success(
        api.evaluate_budget(built["budgets"]["PERIOD_END_BASIS"]["id"], CONTROLLER_HEADERS)
    )
    assert_pct(period_end_budget["forecast_accuracy_pct"], 66.67, "forecast_accuracy_pct")
    assert period_end_budget["forecast_accuracy_pct"] != evaluated["forecast_accuracy_pct"]


def test_the_period_end_basis_scores_only_the_standing_forecast(api):
    """The same trail and the same 21000-cent actual score 66.67 on this basis.

    PRD §3.9: "Under `PERIOD_END_BASIS` — which scores only the latest standing
    forecast — take the absolute difference between `forecast_cents` and
    `actual_spend_cents`, divide by `actual_spend_cents`, multiply by 100,
    subtract from 100, and round half up to two decimal places;
    `forecast_history` is deliberately ignored."

    Design: Difficulty/dual_variant_calc/budget_forecast_accuracy_mape_vs_period_end_divergence
    """
    built = _twin_budgets(api)
    budget_id = built["budgets"]["PERIOD_END_BASIS"]["id"]

    evaluated = validate_success(api.evaluate_budget(budget_id, CONTROLLER_HEADERS))
    assert_budget_evaluation(
        evaluated,
        actual_spend_cents=21000,
        variance_cents=-4610,
        variance_pct=-18.00,
        warning_flag=False,
        status="ACTIVE",
        forecast_accuracy_pct=66.67,
        accuracy_basis_applied="PERIOD_END_BASIS",
    )
    assert evaluated["forecast_history"] == [26000, 24000, 17000]
    assert_cents(evaluated["forecast_cents"], 28000, "forecast_cents")

    _, meta = validate_paginated(
        api.list_budgets(CONTROLLER_HEADERS, {"business_unit_id": built["unit"]["id"]})
    )
    assert meta["total_count"] == 2


def _published_platform_run(api):
    """A published chargeback run whose Platform BU lines total 18645 cents."""
    built = fixtures.discounted_compute_model(api, untagged_cents=5001)
    built.update(
        fixtures.headcount_pool_chargeback_run(
            api,
            [built["platform"]["id"], built["data"]["id"]],
            [built["untagged"]["id"]],
            variant="FINAL",
        )
    )
    built["run"] = fixtures.publish(api, built["run"]["id"])
    assert built["run"]["status"] == "PUBLISHED"
    return built


def test_the_efficiency_tier_is_pinned_before_the_overhead_is_added(api):
    """A provisional 49.85 pins EFFICIENT even though the final figure is 51.35.

    PRD §3.9: "The tier is **not** recomputed from that final figure, even when
    the final figure lands in a different tier band."

    Design: Difficulty/combinatorial_formula/unit_economics_tier_pinned_from_provisional_cost_per_unit
    """
    built = _published_platform_run(api)

    driver = validate_success(
        api.create_unit_economics_driver(
            factories.unit_economics_driver_payload(
                built["platform"]["id"], built["run"]["id"], driver_name="ORDERS", driver_volume=374
            ),
            ANALYST_HEADERS,
        ),
        201,
    )
    assert driver["efficiency_tier"] is None
    assert driver["driver_name"] == "ORDERS"
    assert driver["driver_volume"] == 374
    assert driver["allocation_run_id"] == built["run"]["id"]

    computed = validate_success(
        api.compute_unit_economics_driver(driver["id"], ANALYST_HEADERS)
    )
    assert_cents(computed["base_allocated_cents"], 18645, "base_allocated_cents")
    assert_pct(computed["provisional_cost_per_unit_cents"], 49.85, "provisional_cost_per_unit_cents")
    assert computed["efficiency_tier"] == "EFFICIENT"
    assert_cents(computed["platform_overhead_cents"], 559, "platform_overhead_cents")
    assert_pct(computed["final_cost_per_unit_cents"], 51.35, "final_cost_per_unit_cents")
    assert computed["final_cost_per_unit_cents"] > 50.00
    assert computed["version"] == driver["version"] + 1


def test_the_driver_base_is_every_line_of_the_run_for_that_business_unit(api):
    """Platform BU's direct 14644 and shared 4001 cents make the 18645-cent base.

    PRD §3.9: "First, `base_allocated_cents` is the sum of `allocated_cents`
    across every allocation line of the referenced run whose `business_unit_id`
    is the driver's business unit, taken across all values of `line_kind`
    including `MANUAL_ADJUSTMENT`."

    Design: Difficulty/combinatorial_formula/unit_economics_tier_pinned_from_provisional_cost_per_unit
    """
    built = _published_platform_run(api)
    platform_id = built["platform"]["id"]

    lines, meta = validate_paginated(
        api.list_allocation_lines(
            ANALYST_HEADERS,
            {"allocation_run_id": built["run"]["id"], "business_unit_id": platform_id},
        )
    )
    assert meta["total_count"] == 2
    assert_cents(find_by(lines, line_kind="DIRECT")["allocated_cents"], 14644, "direct line")
    assert_cents(find_by(lines, line_kind="SHARED")["allocated_cents"], 4001, "shared line")

    driver = validate_success(
        api.create_unit_economics_driver(
            factories.unit_economics_driver_payload(
                platform_id, built["run"]["id"], driver_name="ORDERS", driver_volume=374
            ),
            CONTROLLER_HEADERS,
        ),
        201,
    )
    computed = validate_success(
        api.compute_unit_economics_driver(driver["id"], CONTROLLER_HEADERS)
    )
    assert_cents(
        computed["base_allocated_cents"],
        sum(line["allocated_cents"] for line in lines),
        "base_allocated_cents",
    )
    assert_cents(computed["base_allocated_cents"], 18645, "base_allocated_cents")
    assert computed["driver_name"] == "ORDERS"
    assert computed["driver_volume"] == 374
    assert computed["efficiency_tier"] == "EFFICIENT"
    assert_cents(computed["platform_overhead_cents"], 559, "platform_overhead_cents")
    assert_pct(computed["final_cost_per_unit_cents"], 51.35, "final_cost_per_unit_cents")


def _breached_growth_unit(api):
    """Growth BU 20 percent over an August budget, with no explanation recorded."""
    fixtures.set_clock(api, AUGUST_FIFTH_UTC)
    unit = fixtures.create_chargeback_unit(api, "Growth BU", "CC-700", headcount=6)
    policy = fixtures.create_active_policy(api, "core-tags")
    resource = fixtures.provision_resource(
        api,
        policy["id"],
        unit["id"],
        OWNER_6,
        resource_kind="COMPUTE",
        requested_tags={"team": "growth", "environment": "prod", "application": "crm"},
        monthly_run_rate_cents=12000,
    )
    fixtures.create_cost_record(
        api,
        12000,
        resource_kind="COMPUTE",
        billing_period_start=AUGUST_START,
        billing_period_end=AUGUST_END,
        cloud_resource_id=resource["id"],
    )
    budget = fixtures.create_active_budget(
        api,
        unit["id"],
        amount_cents=10000,
        forecast_cents=11000,
        period_start=AUGUST_START,
        period_end=AUGUST_END,
        accuracy_basis="PERIOD_END_BASIS",
    )
    budget = validate_success(api.evaluate_budget(budget["id"], CONTROLLER_HEADERS))
    assert_budget_evaluation(
        budget,
        actual_spend_cents=12000,
        variance_cents=2000,
        variance_pct=20.00,
        warning_flag=False,
        status="BREACHED",
        forecast_accuracy_pct=91.67,
        accuracy_basis_applied="PERIOD_END_BASIS",
    )
    return {"unit": unit, "policy": policy, "budget": budget}


def test_a_breached_budget_blocks_the_next_approval_until_the_variance_is_explained(api):
    """The same approval call is refused, then accepted, with only a narrative between.

    PRD §3.3: "and, if the owning business unit has a budget in `BREACHED` status
    whose period covers the current logical clock, that budget's
    `variance_explanation_text` is non-null, or the request fails with
    `ERR_VARIANCE_EXPLANATION_REQUIRED` at HTTP 422."

    Design: Difficulty/cross_entity_state_dependency/provisioning_approval_gated_by_breached_budget_without_explanation
    """
    built = _breached_growth_unit(api)
    unit_id = built["unit"]["id"]

    request = fixtures.create_provisioning_request(
        api,
        built["policy"]["id"],
        unit_id,
        OWNER_6,
        resource_kind="COMPUTE",
        requested_tags={"team": "growth", "environment": "prod", "application": "crm"},
        monthly_run_rate_cents=9000,
    )
    assert request["status"] == "SUBMITTED"

    blocked = api.approve_provisioning_request(request["id"], ANALYST_HEADERS)
    validate_error(blocked, ApiErrorId.VARIANCE_EXPLANATION_REQUIRED.value, 422)

    still_submitted = validate_success(
        api.get_provisioning_request(request["id"], ANALYST_HEADERS)
    )
    assert still_submitted["status"] == "SUBMITTED"
    assert still_submitted["version"] == request["version"]

    explanation = "One-off migration double-run in August; steady state returns in September."
    explained = validate_success(
        api.explain_budget_variance(
            built["budget"]["id"],
            {"variance_explanation_text": explanation},
            make_business_unit_owner_headers(unit_id),
        )
    )
    assert explained["variance_explanation_text"] == explanation
    assert explained["status"] == "BREACHED"

    approved = validate_success(
        api.approve_provisioning_request(request["id"], ANALYST_HEADERS)
    )
    assert approved["status"] == "APPROVED"


def test_the_approval_gate_only_binds_the_unit_whose_budget_is_breached(api):
    """A second unit with no breached budget approves while Growth BU is still blocked.

    PRD §3.9: "it stores `actual_spend_cents`, `variance_cents`, `variance_pct`,
    `forecast_accuracy_pct`, `accuracy_basis_applied` and `warning_flag`, and it
    gates approval of any further provisioning request for that business unit
    until `variance_explanation_text` has been recorded."

    Design: Difficulty/cross_entity_state_dependency/provisioning_approval_gated_by_breached_budget_without_explanation
    """
    built = _breached_growth_unit(api)
    policy_id = built["policy"]["id"]

    gated = fixtures.create_provisioning_request(
        api,
        policy_id,
        built["unit"]["id"],
        OWNER_6,
        resource_kind="COMPUTE",
        requested_tags={"team": "growth", "environment": "prod", "application": "crm"},
        monthly_run_rate_cents=9000,
    )
    validate_error(
        api.approve_provisioning_request(gated["id"], ANALYST_HEADERS),
        ApiErrorId.VARIANCE_EXPLANATION_REQUIRED.value,
        422,
    )

    other_unit = fixtures.create_chargeback_unit(api, "Support BU", "CC-701", headcount=4)
    ungated = fixtures.create_provisioning_request(
        api,
        policy_id,
        other_unit["id"],
        OWNER_6,
        resource_kind="COMPUTE",
        requested_tags={"team": "support", "environment": "prod", "application": "desk"},
        monthly_run_rate_cents=9000,
    )
    approved = validate_success(
        api.approve_provisioning_request(ungated["id"], ANALYST_HEADERS)
    )
    assert approved["status"] == "APPROVED"

    provisioned = validate_success(
        api.provision_provisioning_request(ungated["id"], ANALYST_HEADERS)
    )
    assert provisioned["status"] == "PROVISIONED"

    still_blocked = validate_success(api.get_provisioning_request(gated["id"], ANALYST_HEADERS))
    assert still_blocked["status"] == "SUBMITTED"

    breached = validate_success(api.get_budget(built["budget"]["id"], CONTROLLER_HEADERS))
    assert breached["status"] == "BREACHED"
    assert breached["variance_explanation_text"] is None
