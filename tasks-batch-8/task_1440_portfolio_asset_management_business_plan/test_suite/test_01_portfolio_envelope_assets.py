"""Portfolio setup, response envelope, asset creation rules, and pagination.

Covers corner-design instances in the entities / calculations / validations
sections that need no more than the base portfolio-manager-asset hierarchy.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    create_asset_payload,
    create_business_plan_payload,
    create_budget_lines_payload,
    create_portfolio_payload,
    create_property_manager_payload,
    create_scorecard_payload,
    create_valuation_payload,
    find_line,
    get_success_data,
    is_iso8601_timestamp,
    lines_rent12,
    make_property_manager_headers,
    setup_base_asset,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

DIRECTOR = TEST_USERS["director"]
AM = TEST_USERS["asset_manager"]
ANALYST = TEST_USERS["analyst"]
LENDER = TEST_USERS["lender"]


def test_portfolio_create_applies_defaults(api):
    """PRD §3.1: "A `PortfolioDirector` begins by creating a portfolio with a
    display `name`, an optional `base_currency` (an ISO currency code
    defaulting to USD), and an optional `fiscal_year_start_month`."
    PRD §3.1: "A new portfolio starts `ACTIVE` with `risk_posture` set to
    `NORMAL` and `total_value_cents` at zero."

    Design: Corner/entities/portfolio_create_applies_defaults
    """
    res = api.create_portfolio({"name": "P1"}, DIRECTOR)
    data = validate_success(res, 201)
    assert data["base_currency"] == "USD", "base_currency must default to USD"
    assert data["fiscal_year_start_month"] == 1, \
        "fiscal_year_start_month must default to 1"
    assert data["status"] == "ACTIVE"
    assert data["risk_posture"] == "NORMAL"
    assert data["total_value_cents"] == 0
    assert isinstance(data["version"], int)


def test_asset_get_not_found_returns_404(api):
    """PRD §2.9: "the first identifier that does not resolve yields
    `ERR_NOT_FOUND` (HTTP 404) before any later lookup or business rule is
    evaluated".

    Design: Corner/entities/asset_get_not_found_returns_404
    """
    res = api.get_asset(NON_EXISTENT_UUID, ANALYST)
    err = validate_error(res, ApiErrorId.ERR_NOT_FOUND)
    assert err["error_id"] == "ERR_NOT_FOUND"
    body = res.json()
    assert body["response_type"] == "error"
    assert "api_request_id" in body["meta"]


def test_asset_create_invalid_enum_rejected(api):
    """PRD §3.1: "an `asset_class` of `OFFICE`, `RETAIL`, `INDUSTRIAL`, or
    `MULTIFAMILY`".
    PRD §2.9: "Shape and uniqueness: malformed bodies, bad enumerations,
    non-positive amounts, bad period labels, inverted month ranges
    (`ERR_INVALID_REQUEST`)".

    Design: Corner/entities/asset_create_invalid_enum_rejected
    """
    portfolio = get_success_data(api.create_portfolio(
        create_portfolio_payload(), DIRECTOR))
    manager = get_success_data(api.create_property_manager(
        create_property_manager_payload(), DIRECTOR))
    res = api.create_asset(
        create_asset_payload(portfolio["id"], manager["id"], asset_class="RETAILX"),
        DIRECTOR)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)
    data, meta = validate_paginated(
        api.list_portfolio_assets(portfolio["id"], ANALYST))
    assert meta["total_count"] == 0, "no asset may persist after a rejected create"


def test_asset_create_future_acquisition_rejected(api):
    """PRD §3.1: "an `acquisition_date` that must not fall after the current
    clock date (a future date is rejected with `ERR_FUTURE_PERIOD`)".
    PRD §2.5: "Before any client call, the logical clock reads exactly
    2026-08-01T00:00:00Z, and it must never fall back to wall-clock time."

    Design: Corner/entities/asset_create_future_acquisition_rejected
    """
    portfolio = get_success_data(api.create_portfolio(
        create_portfolio_payload(), DIRECTOR))
    manager = get_success_data(api.create_property_manager(
        create_property_manager_payload(), DIRECTOR))
    res = api.create_asset(
        create_asset_payload(portfolio["id"], manager["id"],
                             acquisition_date="2026-08-02"),
        DIRECTOR)
    validate_error(res, ApiErrorId.ERR_FUTURE_PERIOD)


def test_budget_lines_pagination_fields(api):
    """PRD §2.3: "`limit` caps the number of items returned; it defaults to
    10, with a minimum of 1 and a maximum of 100. `offset` skips a number of
    items before returning results and defaults to 0."
    PRD §2.3: "The `meta` object of a list response carries four pagination
    fields: `limit`, `offset`, `total_count`, and `has_more`."
    PRD §4: "List budget lines of a plan in creation order".

    Design: Corner/entities/budget_lines_pagination_fields
    """
    ctx = setup_base_asset()
    plan = get_success_data(api.create_business_plan(
        create_business_plan_payload(ctx["asset"]["id"], 2027,
                                     ctx["asset"]["version"]), AM))
    created = get_success_data(api.create_budget_lines(
        create_budget_lines_payload(plan["id"], lines_rent12()), AM))
    assert len(created) == 21

    page1, meta1 = validate_paginated(api.list_business_plan_budget_lines(
        plan["id"], ANALYST, params={"limit": 10, "offset": 0}))
    assert meta1["total_count"] == 21
    assert meta1["has_more"] is True
    assert len(page1) == 10
    assert page1[0]["category"] == "RENT_REVENUE"
    assert page1[0]["month_index"] == 1

    page3, meta3 = validate_paginated(api.list_business_plan_budget_lines(
        plan["id"], ANALYST, params={"limit": 10, "offset": 20}))
    assert meta3["total_count"] == 21
    assert meta3["has_more"] is False
    assert len(page3) == 1
    assert page3[0]["category"] == "CAPITAL"

    default_page, default_meta = validate_paginated(
        api.list_business_plan_budget_lines(plan["id"], ANALYST))
    assert default_meta["limit"] == 10, "omitted limit must default to 10"
    assert default_meta["offset"] == 0, "omitted offset must default to 0"
    assert len(default_page) == 10


def test_response_envelope_object_shape(api):
    """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
    for the request that starts with `req_`."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."
    PRD §2.2: "The `api_request_timestamp` is a server-generated ISO 8601 UTC
    timestamp with three fractional digits."

    Design: Corner/entities/response_envelope_object_shape
    """
    portfolio = get_success_data(api.create_portfolio(
        create_portfolio_payload(), DIRECTOR))
    res = api.get_portfolio(portfolio["id"], LENDER)
    data = validate_success(res, 200)
    assert data["id"] == portfolio["id"]
    body = res.json()
    assert body["response_type"] == "object"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])


def test_read_after_write_immediate_consistency(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §2.8: "derived aggregates on parent resources (plan budget totals and
    capital buckets, asset value and annualized NOI, portfolio value and
    posture) are recomputed immediately rather than asynchronously."

    Design: Corner/entities/read_after_write_immediate_consistency
    """
    get_success_data(api.create_portfolio(create_portfolio_payload(), DIRECTOR))
    created = validate_success(
        api.create_property_manager(create_property_manager_payload(), DIRECTOR),
        201)
    assert created["status"] == "ACTIVE"
    reread = validate_success(
        api.get_property_manager(created["id"], ANALYST), 200)
    assert reread["status"] == "ACTIVE", "read-after-write must show no lag"
    assert reread["version"] == created["version"], \
        "no hidden mutation may advance the version between create and read"


def test_portfolio_report_weighted_occupancy(api):
    """PRD §3.9: "weighted_occupancy_pct, the square-footage-weighted mean
    occupancy — each asset contributes the occupancy of its most recent
    finalized scorecard ... times its `net_rentable_sqft`, divided by the
    total square footage of all counted assets, rounded half-up, where an
    asset with no finalized scorecard contributes zero to the numerator but
    still adds its square footage to the denominator".
    PRD §3.9: "`portfolio_noi_cents`, the sum of their
    `current_annualized_noi_cents`, again treating unset values as zero".

    Design: Corner/calculations/portfolio_report_weighted_occupancy
    """
    portfolio = get_success_data(api.create_portfolio(
        create_portfolio_payload(), DIRECTOR))
    manager = get_success_data(api.create_property_manager(
        create_property_manager_payload(), DIRECTOR))
    a1 = get_success_data(api.create_asset(
        create_asset_payload(portfolio["id"], manager["id"], name="A1",
                             net_rentable_sqft=100000), DIRECTOR))
    a2 = get_success_data(api.create_asset(
        create_asset_payload(portfolio["id"], manager["id"], name="A2",
                             address="2 Oak Ave", asset_class="RETAIL",
                             net_rentable_sqft=300000,
                             acquisition_price_cents=400000000), DIRECTOR))
    for asset in (a1, a2):
        val = get_success_data(api.create_valuation(
            create_valuation_payload(asset["id"], "2026-07-01",
                                     "EXTERNAL_APPRAISAL",
                                     appraised_value_cents=500000000), ANALYST))
        fresh = get_success_data(api.get_asset(asset["id"], ANALYST))
        get_success_data(api.confirm_valuation(
            val["id"], {"expected_asset_version": fresh["version"]}, DIRECTOR))
    pm_headers = make_property_manager_headers(manager["id"])
    for asset, occ in ((a1, 80), (a2, 60)):
        sc = get_success_data(api.create_performance_scorecard(
            create_scorecard_payload(asset["id"], "2026-Q2", occ, 90, 70, 0),
            pm_headers))
        get_success_data(api.review_performance_scorecard(sc["id"], AM))
        get_success_data(api.finalize_performance_scorecard(sc["id"], AM))

    report = validate_success(
        api.get_portfolio_performance_report(portfolio["id"], ANALYST), 200)
    assert report["asset_count"] == 2
    assert report["total_value_cents"] == 1000000000
    assert report["weighted_occupancy_pct"] == 65, (
        "(80*100000 + 60*300000) / 400000 = 65")
    assert report["portfolio_noi_cents"] == 0, \
        "assets without accepted actuals contribute 0 to portfolio NOI"
    assert report["implied_cap_rate_bps"] == 0


def test_archive_portfolio_with_assets_rejected(api):
    """PRD §3.1: "archiving transitions it from `ACTIVE` to `ARCHIVED`, and is
    permitted only when every asset of the portfolio has reached `SOLD` —
    while any asset remains in another status the archive is refused with
    `ERR_PORTFOLIO_NOT_EMPTY`."

    Design: Corner/validations/archive_portfolio_with_assets_rejected
    """
    ctx = setup_base_asset()
    res = api.archive_portfolio(ctx["portfolio"]["id"], DIRECTOR)
    validate_error(res, ApiErrorId.ERR_PORTFOLIO_NOT_EMPTY)
    after = validate_success(api.get_portfolio(ctx["portfolio"]["id"], ANALYST), 200)
    assert after["status"] == "ACTIVE", "rejected archive must leave the portfolio ACTIVE"
