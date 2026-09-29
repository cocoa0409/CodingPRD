"""Half-open testing-period geometry and the fund-certification gate on measurement."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_asset_test_measurement, assert_fund_state
from test_helpers.factories import create_asset_test_payload
from test_helpers.fixtures import (
    list_fund_asset_tests,
    make_asset_test,
    make_fund,
    make_self_certified_fund,
    measure_asset_test,
    read_fund,
    self_certify_fund,
)
from test_helpers.test_users import MANAGER_HEADERS, MEASURER_HEADERS


def test_adjacent_testing_periods_share_the_boundary_instant(api):
    """
    "Adjacency is legal here — a new period whose `period_start` equals an existing
    period's `period_end` is accepted, because back-to-back semiannual periods share
    that instant."

    Design: Difficulty/resource_temporal_overlap/asset_test_period_half_open_adjacency_allowed
    """
    fund = make_self_certified_fund(api)
    first = make_asset_test(
        api,
        fund["id"],
        measurement_date="2026-06-30T00:00:00Z",
        period_start="2026-01-01T00:00:00Z",
        period_end="2026-07-01T00:00:00Z",
    )

    response = api.create_asset_test(
        fund["id"],
        create_asset_test_payload(
            measurement_date="2026-12-31T00:00:00Z",
            period_start="2026-07-01T00:00:00Z",
            period_end="2027-01-01T00:00:00Z",
        ),
        MANAGER_HEADERS,
    )
    second = validate_success(response, 201)

    assert second["status"] == "DRAFT"
    assert second["period_start"].startswith("2026-07-01T00:00:00")
    assert second["period_end"].startswith("2027-01-01T00:00:00")
    tests = list_fund_asset_tests(api, fund["id"])
    assert {test["id"] for test in tests} == {first["id"], second["id"]}


def test_interior_intersection_and_zero_width_periods_are_rejected(api):
    """
    "A genuine intersection, or a period whose start is not strictly before its end,
    is rejected with `ERR_TESTING_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/asset_test_period_half_open_adjacency_allowed
    """
    fund = make_self_certified_fund(api)
    make_asset_test(
        api,
        fund["id"],
        measurement_date="2026-06-30T00:00:00Z",
        period_start="2026-01-01T00:00:00Z",
        period_end="2026-07-01T00:00:00Z",
    )
    make_asset_test(
        api,
        fund["id"],
        measurement_date="2026-12-31T00:00:00Z",
        period_start="2026-07-01T00:00:00Z",
        period_end="2027-01-01T00:00:00Z",
    )

    interior = api.create_asset_test(
        fund["id"],
        create_asset_test_payload(
            measurement_date="2026-07-31T00:00:00Z",
            period_start="2026-06-01T00:00:00Z",
            period_end="2026-08-01T00:00:00Z",
        ),
        MANAGER_HEADERS,
    )
    validate_error(interior, ApiErrorId.TESTING_PERIOD_OVERLAP.value, 409)

    zero_width = api.create_asset_test(
        fund["id"],
        create_asset_test_payload(
            measurement_date="2027-01-01T00:00:00Z",
            period_start="2027-01-01T00:00:00Z",
            period_end="2027-01-01T00:00:00Z",
        ),
        MANAGER_HEADERS,
    )
    validate_error(zero_width, ApiErrorId.TESTING_PERIOD_OVERLAP.value, 409)

    assert len(list_fund_asset_tests(api, fund["id"])) == 2


def test_measuring_is_refused_while_the_owning_fund_is_still_draft(api):
    """
    "Measuring a test moves it `DRAFT → MEASURED`, requires the owning fund to be
    `SELF_CERTIFIED`, records the caller's handle as `measured_by_user_id`, and sets
    the fund's `last_test_measurement_date` to this test's `measurement_date`."

    Design: Difficulty/cross_entity_state_dependency/asset_test_measure_requires_self_certified_fund
    """
    fund = make_fund(api, asset_test_valuation_method="UNADJUSTED_COST_BASIS")
    assert_fund_state(fund, certification_status="DRAFT")
    test = make_asset_test(
        api,
        fund["id"],
        measurement_date="2026-06-30T00:00:00Z",
        period_start="2026-01-01T00:00:00Z",
        period_end="2026-07-01T00:00:00Z",
    )
    assert test["status"] == "DRAFT"

    response = api.measure_asset_test(test["id"], None, MEASURER_HEADERS)
    validate_error(response, ApiErrorId.FUND_NOT_CERTIFIED.value, 409)

    after = validate_success(api.get_asset_test(test["id"], MEASURER_HEADERS))
    assert after["status"] == "DRAFT"
    assert not after.get("measured_by_user_id")


def test_measuring_an_empty_ledger_yields_a_zero_ratio_without_dividing(api):
    """
    "`ratio_pct` is the numerator divided by the denominator, multiplied by 100 and
    rounded half up to four decimal places — and exactly 0.0000 when
    `total_denominator` is 0.00, which is the case a fund with no included assets
    must not divide its way into."

    Design: Difficulty/cross_entity_state_dependency/asset_test_measure_requires_self_certified_fund
    """
    fund = make_fund(api, asset_test_valuation_method="UNADJUSTED_COST_BASIS")
    test = make_asset_test(
        api,
        fund["id"],
        measurement_date="2026-06-30T00:00:00Z",
        period_start="2026-01-01T00:00:00Z",
        period_end="2026-07-01T00:00:00Z",
    )
    api.measure_asset_test(test["id"], None, MEASURER_HEADERS)
    self_certify_fund(api, fund["id"])

    measured = measure_asset_test(api, test["id"], MEASURER_HEADERS)

    assert measured["status"] == "MEASURED"
    assert_asset_test_measurement(
        measured,
        included_asset_count=0,
        total_denominator=0.00,
        qualified_numerator=0.00,
        ratio_pct=0.0000,
        result="FAIL",
        shortfall_amount=0.00,
        failed_month_count=6,
    )
    fund_after = read_fund(api, fund["id"])
    assert fund_after["last_test_measurement_date"].startswith("2026-06-30T00:00:00")
    assert_fund_state(fund_after, compliance_posture="UNTESTED")
