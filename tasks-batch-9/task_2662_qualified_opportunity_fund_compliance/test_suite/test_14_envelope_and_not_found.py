"""Envelope-level guards, pagination bounds and the not-found vocabulary."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import (
    create_business_test_payload,
    create_fund_asset_payload,
    create_deferral_election_payload,
    create_wcsh_plan_payload,
    spend_schedule,
)
from test_helpers.fixtures import list_fund_assets, make_fund, read_fund
from test_helpers.test_users import (
    ADMIN_HEADERS,
    MANAGER_HEADERS,
    MEASURER_HEADERS,
    make_headers,
)

UNKNOWN_ID = "00000000-0000-4000-8000-000000000099"
UNKNOWN_ASSET_TEST_ID = "00000000-0000-4000-8000-000000000999"
UNKNOWN_BUSINESS_ID = "00000000-0000-4000-8000-0000000000aa"


def test_the_three_envelope_guards_fire_before_any_domain_logic(api):
    """
    "Auth headers present and non-blank — `ERR_MISSING_AUTH_HEADER` (401)."
    "`X-User-Role` is one of the four recognized roles — `ERR_UNKNOWN_ROLE` (401)."
    "A `limit` outside 1 through 100, a non-integer `limit` or `offset`, or a negative
    `offset` is rejected with `ERR_INVALID_PAGINATION` (HTTP 400)."

    Design: Corner/errors/auth_and_pagination_envelope_errors_rejected
    """
    validate_error(
        api.list_funds(None), ApiErrorId.MISSING_AUTH_HEADER.value, 401
    )
    validate_error(
        api.list_funds(make_headers("aud-1", "Auditor")),
        ApiErrorId.UNKNOWN_ROLE.value,
        401,
    )
    for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
        validate_error(
            api.list_eligible_gains(MEASURER_HEADERS, params),
            ApiErrorId.INVALID_PAGINATION.value,
            400,
        )

    rows, meta = validate_paginated(
        api.list_eligible_gains(MEASURER_HEADERS, {"limit": 100, "offset": 0})
    )
    assert rows == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False


def test_nine_unknown_path_ids_answer_with_nine_distinct_error_ids(api):
    """
    "Path identifiers are resolved strictly left to right, and the first identifier
    that does not resolve determines the error. The error is the one belonging to the
    entity that owns the path segment: `ERR_FUND_NOT_FOUND`, `ERR_INVESTOR_NOT_FOUND`,
    `ERR_ELIGIBLE_GAIN_NOT_FOUND`, `ERR_DEFERRAL_ELECTION_NOT_FOUND`,
    `ERR_FUND_ASSET_NOT_FOUND`, `ERR_QOZ_BUSINESS_NOT_FOUND`,
    `ERR_BUSINESS_TEST_NOT_FOUND`, `ERR_ASSET_TEST_NOT_FOUND`,
    `ERR_IMPROVEMENT_PROJECT_NOT_FOUND`, `ERR_WCSH_PLAN_NOT_FOUND` or
    `ERR_PENALTY_ASSESSMENT_NOT_FOUND` — each HTTP 404."

    Design: Corner/errors/every_path_id_returns_its_own_entity_not_found_error
    """
    probes = (
        (api.get_fund, ApiErrorId.FUND_NOT_FOUND),
        (api.get_investor, ApiErrorId.INVESTOR_NOT_FOUND),
        (api.get_eligible_gain, ApiErrorId.ELIGIBLE_GAIN_NOT_FOUND),
        (api.get_deferral_election, ApiErrorId.DEFERRAL_ELECTION_NOT_FOUND),
        (api.get_fund_asset, ApiErrorId.FUND_ASSET_NOT_FOUND),
        (api.get_business_test, ApiErrorId.BUSINESS_TEST_NOT_FOUND),
        (api.get_improvement_project, ApiErrorId.IMPROVEMENT_PROJECT_NOT_FOUND),
        (api.get_wcsh_plan, ApiErrorId.WCSH_PLAN_NOT_FOUND),
        (api.get_penalty_assessment, ApiErrorId.PENALTY_ASSESSMENT_NOT_FOUND),
    )
    observed = []
    for getter, expected in probes:
        response = getter(UNKNOWN_ID, MEASURER_HEADERS)
        validate_error(response, expected.value, 404)
        assert response.json()["response_type"] == "error"
        observed.append(expected.value)

    assert len(set(observed)) == 9


def test_a_dangling_body_foreign_key_is_the_one_generic_reference_error(api):
    """
    "Foreign keys arriving in a request **body** are a separate check with a single
    error. When `investor_id`, `eligible_gain_id`, `fund_id`, `qoz_business_id`,
    `fund_asset_id`, or any element of a supplied disposition sequence fails to resolve
    to an existing row, the response is `ERR_REFERENCED_ENTITY_NOT_FOUND` (HTTP 404)."

    Design: Corner/errors/body_foreign_key_reference_not_found_rejected
    """
    fund = make_fund(api, name="Dangling FK Fund", entity_type="PARTNERSHIP")

    asset_response = api.create_fund_asset(
        create_fund_asset_payload(
            UNKNOWN_ID,
            asset_class="CASH",
            acquisition_date="2026-02-01T00:00:00Z",
            unadjusted_cost_basis=100000.00,
            afs_fair_value=100000.00,
        ),
        MANAGER_HEADERS,
    )
    election_response = api.create_deferral_election(
        create_deferral_election_payload(
            UNKNOWN_ID, fund["id"], fund["version"], elected_amount=50000.00
        ),
        ADMIN_HEADERS,
    )
    plan_response = api.create_wcsh_plan(
        create_wcsh_plan_payload(
            UNKNOWN_ID,
            window_start="2026-01-01T00:00:00Z",
            covered_amount=100000.00,
            written_plan_reference="WP-2662-DANGLE",
            schedule_month_count=1,
            spend_schedule=spend_schedule(100000.00),
        ),
        ADMIN_HEADERS,
    )

    for response in (asset_response, election_response, plan_response):
        validate_error(response, ApiErrorId.REFERENCED_ENTITY_NOT_FOUND.value, 404)
    after = read_fund(api, fund["id"])
    assert after["version"] == fund["version"]
    assert list_fund_assets(api, fund["id"]) == []


def test_fetching_an_unknown_asset_test_answers_the_error_envelope(api):
    """
    "`ERR_ASSET_TEST_NOT_FOUND`". "The `error_id` is a unique, machine-readable string
    that identifies the specific error." "The `message` provides a human-readable
    explanation of what went wrong."

    Design: Corner/entities/asset_test_fetch_unknown_id_not_found
    """
    response = api.get_asset_test(UNKNOWN_ASSET_TEST_ID, MEASURER_HEADERS)

    error = validate_error(response, ApiErrorId.ASSET_TEST_NOT_FOUND.value, 404)

    body = response.json()
    assert body["response_type"] == "error"
    assert set(body["meta"]) == {"api_request_id", "api_request_timestamp"}
    assert isinstance(error["message"], str)
    assert error["message"].strip()


def test_opening_a_business_test_under_an_unknown_parent_is_a_path_failure(api):
    """
    "Path resolution happens before any state, ownership or business check on the
    resource, so a call against a nonexistent fund reports the missing fund rather than
    a permission or state problem."

    Design: Corner/entities/business_test_creation_under_unknown_parent_not_found
    """
    response = api.create_business_test(
        UNKNOWN_BUSINESS_ID,
        create_business_test_payload(testing_date="2026-06-30T00:00:00Z"),
        MEASURER_HEADERS,
    )

    validate_error(response, ApiErrorId.QOZ_BUSINESS_NOT_FOUND.value, 404)
    assert response.json()["response_type"] == "error"
    validate_error(
        api.list_business_tests(UNKNOWN_BUSINESS_ID, ADMIN_HEADERS, {"limit": 100}),
        ApiErrorId.QOZ_BUSINESS_NOT_FOUND.value,
        404,
    )
