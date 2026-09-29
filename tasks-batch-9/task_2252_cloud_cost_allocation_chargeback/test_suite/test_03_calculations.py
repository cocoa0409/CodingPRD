"""Derived figures: variance, tag compliance, pool distribution and coverage."""

from test_helpers import (
    ANALYST_HEADERS,
    CONTROLLER_HEADERS,
    OWNER_4,
    assert_allocation_line,
    assert_budget_evaluation,
    assert_cents,
    assert_commitment_figures,
    assert_pct,
    assert_shares_sum_to_pool,
    assert_tag_compliance,
    factories,
    find_by,
    fixtures,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import AUGUST_END, AUGUST_START, JULY_END, JULY_START


def test_a_seven_percent_overspend_raises_the_warning_flag_without_breaching(api):
    """Variance lands inside the warning band, so the budget stays `ACTIVE`.

    PRD §3.9: "`warning_flag` is true when `variance_pct` is at or above 5.00
    but strictly below 10.00, and false otherwise."

    Design: Corner/calculations/budget_variance_and_warning_flag_at_seven_percent_overspend
    """
    fixtures.set_clock(api)
    unit = fixtures.create_business_unit(api)
    policy = fixtures.create_active_policy(api)
    resource = fixtures.provision_resource(
        api, policy["id"], unit["id"], OWNER_4, monthly_run_rate_cents=10700
    )
    fixtures.create_cost_record(
        api, 10700, resource_kind="COMPUTE", cloud_resource_id=resource["id"]
    )

    budget = fixtures.create_active_budget(
        api,
        unit["id"],
        amount_cents=10000,
        forecast_cents=10000,
        accuracy_basis="PERIOD_END_BASIS",
    )

    evaluated = validate_success(api.evaluate_budget(budget["id"], ANALYST_HEADERS))

    assert_budget_evaluation(
        evaluated,
        actual_spend_cents=10700,
        variance_cents=700,
        variance_pct=7.00,
        warning_flag=True,
        status="ACTIVE",
        forecast_accuracy_pct=93.46,
        accuracy_basis_applied="PERIOD_END_BASIS",
    )


def test_compliance_is_normalised_against_the_declared_mandatory_subset(api):
    """Two mandated dimensions score out of 65, not out of 100.

    PRD §3.3: "Note that the weights are normalised against the *declared*
    mandatory set, so a policy that mandates only `team` and `application`
    yields 100.00 when both are present, even though those two weights sum to
    65 out of the full 100."

    Design: Corner/calculations/tag_compliance_weights_are_summed_over_the_mandatory_subset_only
    """
    fixtures.set_clock(api)
    unit = fixtures.create_business_unit(api)
    policy = fixtures.create_active_policy(
        api,
        name="Subset Policy",
        mandatory_dimensions=["team", "application"],
        enforcement_mode="BLOCKING",
    )

    request = validate_success(
        api.create_provisioning_request(
            factories.provisioning_request_payload(
                policy["id"],
                unit["id"],
                OWNER_4,
                requested_tags={"application": "api", "environment": "dev"},
            ),
            ANALYST_HEADERS,
        ),
        201,
    )
    assert_tag_compliance(
        request,
        missing_dimensions=["team"],
        compliance_score=38.46,
        projected_tag_state="PARTIAL",
        status="TAG_REJECTED",
    )

    retagged = validate_success(
        api.retag_provisioning_request(
            request["id"],
            {"requested_tags": {"team": "ops", "application": "api"}},
            ANALYST_HEADERS,
        )
    )
    assert_tag_compliance(
        retagged,
        missing_dimensions=[],
        compliance_score=100.00,
        projected_tag_state="TAGGED",
        status="SUBMITTED",
    )
    assert retagged["retag_count"] == 1


def test_the_leftover_cent_goes_to_the_largest_fractional_share(api):
    """A 5001-cent pool splits 40:10 with the odd cent following the remainder rule.

    PRD §3.5: "The leftover is the pooled amount less the sum of the floored
    allocations, and it is handed out one cent at a time under a pinned
    remainder rule: participants are ordered by the fractional part of their
    exact share descending, with ties broken by the participant business unit's
    `created_at` ascending, and UUID values must not participate in that
    ordering."

    Design: Corner/calculations/shared_pool_remainder_cent_goes_to_the_largest_fractional_part
    """
    fixtures.set_clock(api)
    platform = fixtures.create_business_unit(api, "Platform", "CC-100", headcount=40)
    data = fixtures.create_business_unit(api, "Data", "CC-200", headcount=10)
    record = fixtures.create_untagged_record(api, 5001)

    run = fixtures.create_run(api, mode="SHOWBACK")
    pool = fixtures.create_pool(
        api,
        run["id"],
        [platform["id"], data["id"]],
        name="Untagged Storage",
        methodology="PROPORTIONAL",
        proportional_basis="HEADCOUNT",
    )
    absorbed = fixtures.absorb(api, pool["id"], [record["id"]])
    assert_cents(absorbed["pooled_cost_cents"], 5001, "pooled_cost_cents")
    assert absorbed["absorbed_record_count"] == 1

    computed = fixtures.compute(api, run["id"], "FINAL")
    assert computed["status"] == "COMPUTED_FINAL"
    assert_cents(computed["total_allocated_cents"], 5001, "total_allocated_cents")
    assert computed["line_count"] == 2

    lines, meta = validate_paginated(
        api.list_allocation_lines(ANALYST_HEADERS, {"shared_cost_pool_id": pool["id"]})
    )
    assert meta["total_count"] == 2
    assert all(line["line_kind"] == "SHARED" for line in lines)
    assert all(line["method_applied"] == "PROPORTIONAL" for line in lines)
    assert_shares_sum_to_pool(lines, 5001)

    platform_line = find_by(lines, business_unit_id=platform["id"])
    assert_allocation_line(
        platform_line,
        line_kind="SHARED",
        method_applied="PROPORTIONAL",
        allocated_cents=4001,
        basis_value=40.00,
        rounding_remainder_cents=1,
    )

    data_line = find_by(lines, business_unit_id=data["id"])
    assert_allocation_line(
        data_line,
        line_kind="SHARED",
        method_applied="PROPORTIONAL",
        allocated_cents=1000,
        basis_value=10.00,
        rounding_remainder_cents=0,
    )


def test_the_coverage_waterfall_skips_the_wrong_kind_and_the_out_of_term_record(api):
    """Only the in-term record of the covered kind is discounted.

    PRD §3.4: "Candidate records are those whose `allocation_state` is
    `UNALLOCATED`, whose `applied_commitment_id` is still null, whose
    `resource_kind` is among the coverable kinds, whose `billing_period_start`
    is at or after `term_start`, and whose `billing_period_end` is at or before
    `term_end`."

    Design: Corner/calculations/commitment_waterfall_ignores_wrong_kind_and_out_of_term_records
    """
    fixtures.set_clock(api)
    unit = fixtures.create_business_unit(api)
    policy = fixtures.create_active_policy(api)
    resource = fixtures.provision_resource(
        api, policy["id"], unit["id"], OWNER_4, monthly_run_rate_cents=10000
    )

    in_term_compute = fixtures.create_cost_record(
        api, 10000, resource_kind="COMPUTE", cloud_resource_id=resource["id"]
    )
    wrong_kind = fixtures.create_cost_record(
        api, 10000, resource_kind="STORAGE", cloud_resource_id=resource["id"]
    )
    out_of_term = fixtures.create_cost_record(
        api,
        10000,
        resource_kind="COMPUTE",
        billing_period_start=AUGUST_START,
        billing_period_end=AUGUST_END,
        cloud_resource_id=resource["id"],
    )

    commitment = fixtures.create_commitment(
        api,
        commitment_type="RESERVED_INSTANCE",
        region="us-east-1",
        covered_resource_kind="COMPUTE",
        term_start=JULY_START,
        term_end=JULY_END,
        hourly_commit_cents=50,
    )
    activated = validate_success(
        api.activate_commitment(commitment["id"], CONTROLLER_HEADERS)
    )

    assert_commitment_figures(
        activated,
        committed_capacity_cents=36000,
        covered_spend_cents=10000,
        total_discount_cents=4000,
        waste_cents=26000,
        coverage_pct=100.00,
        utilization_pct=27.78,
    )

    covered = validate_success(api.get_cost_record(in_term_compute["id"], ANALYST_HEADERS))
    assert covered["applied_commitment_id"] == commitment["id"]
    assert_cents(covered["effective_cost_cents"], 6000, "effective_cost_cents")

    for skipped_id in (wrong_kind["id"], out_of_term["id"]):
        skipped = validate_success(api.get_cost_record(skipped_id, ANALYST_HEADERS))
        assert skipped["applied_commitment_id"] is None
        assert_cents(skipped["effective_cost_cents"], 10000, "effective_cost_cents")
    assert_pct(activated["coverage_pct"], 100.00, "coverage_pct")
