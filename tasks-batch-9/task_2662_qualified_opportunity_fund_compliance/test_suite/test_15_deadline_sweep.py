"""The operator deadline sweep across the gain, improvement and safe-harbor clocks."""

from test_helpers.assertions import assert_fund_aggregates, assert_money, assert_percent
from test_helpers.fixtures import (
    make_active_wcsh_plan,
    make_eligible_gain,
    make_fund_asset,
    make_improvement_project,
    make_investor,
    make_qoz_business,
    make_self_certified_fund,
    read_eligible_gain,
    read_fund,
    read_fund_asset,
    read_improvement_project,
    read_qoz_business,
    read_wcsh_plan,
    run_deadline_sweep,
    set_clock,
)


def test_one_sweep_applies_three_clocks_and_skips_what_is_still_live(api):
    """
    "the `investment_deadline` is the `window_basis_date` advanced by exactly 180
    calendar days."
    "every eligible gain whose `status` is `ELIGIBLE` or `PARTIALLY_INVESTED` and whose
    `investment_deadline` the logical clock has moved **strictly past** is expired with
    `expired_at` stamped from the clock"
    "every improvement project that is still `OPEN` whose `window_end` the logical clock
    has reached or passed, and whose `improvement_ratio_pct` is still below 100.0000,
    moves `OPEN → LAPSED`"
    "every working-capital plan that is still `ACTIVE` whose `window_end` the logical
    clock has reached or passed and whose `unspent_amount` is strictly greater than 0.00
    moves `ACTIVE → BLOWN`"
    "The counts are of rows actually transitioned"

    Design: Corner/endpoints/deadline_sweep_expires_gains_lapses_projects_and_blows_plans
    """
    investor = make_investor(
        api,
        legal_name="Sweeney Sweep",
        taxpayer_type="INDIVIDUAL",
        compliance_attestation_status="ATTESTED",
    )
    doomed_gain = make_eligible_gain(
        api,
        investor["id"],
        eligible_amount=100000.00,
        realization_date="2026-07-01T00:00:00Z",
    )
    assert doomed_gain["investment_deadline"].startswith("2026-12-28T00:00:00")

    fund = make_self_certified_fund(
        api, name="Sweep Fund", entity_type="CORPORATION"
    )
    asset = make_fund_asset(
        api,
        fund["id"],
        asset_class="QOZ_BUSINESS_PROPERTY",
        acquisition_date="2026-01-05T00:00:00Z",
        unadjusted_cost_basis=500000.00,
        afs_fair_value=500000.00,
        original_use_in_zone=False,
    )
    project = make_improvement_project(
        api,
        asset["id"],
        window_start="2026-01-01T00:00:00Z",
        aggregation_method="ASSET_BY_ASSET",
    )
    assert project["status"] == "OPEN"
    assert project["window_end"].startswith("2028-07-01T00:00:00")

    business = make_qoz_business(
        api,
        fund["id"],
        legal_name="Sweep Operating LLC",
        zone_tract_code="12345678910",
        declared_nqfp_amount=300000.00,
        total_asset_value=1000000.00,
        total_tangible_property_basis=700000.00,
    )
    plan = make_active_wcsh_plan(
        api,
        business["id"],
        window_start="2026-01-01T00:00:00Z",
        covered_amount=300000.00,
        written_plan_reference="WP-2662-SWEEP-1",
    )
    assert plan["status"] == "ACTIVE"
    assert plan["window_end"].startswith("2028-08-01T00:00:00")
    assert_money(read_qoz_business(api, business["id"])["nqfp_amount"], 0.00, "nqfp_amount")

    set_clock(api, "2028-12-15T00:00:00Z")
    live_gain = make_eligible_gain(
        api,
        investor["id"],
        eligible_amount=50000.00,
        realization_date="2028-12-01T00:00:00Z",
    )
    assert live_gain["investment_deadline"].startswith("2029-05-30T00:00:00")

    set_clock(api, "2029-01-01T00:00:00Z")
    swept = run_deadline_sweep(api)

    assert swept["expired_gain_count"] == 1
    assert swept["lapsed_project_count"] == 1
    assert swept["blown_plan_count"] == 1
    assert swept["swept_at"].startswith("2029-01-01T00:00:00")

    expired = read_eligible_gain(api, doomed_gain["id"])
    assert expired["status"] == "EXPIRED"
    assert expired["expired_at"].startswith("2029-01-01T00:00:00")
    assert_money(expired["unelected_amount"], 100000.00, "unelected_amount")

    untouched = read_eligible_gain(api, live_gain["id"])
    assert untouched["status"] == "ELIGIBLE"
    assert not untouched["expired_at"]

    lapsed = read_improvement_project(api, project["id"])
    assert lapsed["status"] == "LAPSED"
    assert lapsed["evaluated_at"].startswith("2029-01-01T00:00:00")
    assert_percent(lapsed["improvement_ratio_pct"], 0.0000, "improvement_ratio_pct")

    asset_after = read_fund_asset(api, asset["id"])
    assert asset_after["status"] == "HELD"
    assert asset_after["qualification"] == "NONQUALIFIED"
    assert_fund_aggregates(
        read_fund(api, fund["id"]),
        aggregate_asset_basis=500000.00,
        aggregate_qualified_basis=0.00,
    )

    blown = read_wcsh_plan(api, plan["id"])
    assert blown["status"] == "BLOWN"
    assert_money(blown["unspent_amount"], 300000.00, "unspent_amount")

    business_after = read_qoz_business(api, business["id"])
    assert_money(
        business_after["wcsh_protected_amount"], 0.00, "wcsh_protected_amount"
    )
    assert_money(
        business_after["blown_unspent_amount"], 300000.00, "blown_unspent_amount"
    )
    assert_money(business_after["nqfp_amount"], 600000.00, "nqfp_amount")
