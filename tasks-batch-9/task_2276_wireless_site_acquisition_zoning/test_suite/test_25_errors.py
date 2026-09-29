"""The envelope of a refusal: which 404, which 401, and which pagination bound."""

from test_helpers import factories as F
from test_helpers import fixtures as S
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiError
from test_helpers.assertions import (
    assert_error_data_shape,
    assert_error_meta_shape,
    assert_pagination_meta,
    failed,
    page,
)
from test_helpers.test_users import NO_AUTH_HEADERS

UNKNOWN_ID = "00000000-0000-0000-0000-0000000000ff"

LIMIT_ONE_ABOVE_CEILING = 101
LIMIT_AT_CEILING = 100


def test_three_reads_of_one_missing_id_name_three_different_entities(
    api: ApiClient,
) -> None:
    """The 404 identifies the entity the path addressed, not a generic miss.

    PRD: "Identifiers in a URL path are resolved left to right, and the first identifier
    that does not resolve determines the 404 that comes back:
    `ERR_SEARCH_RING_NOT_FOUND`, `ERR_CANDIDATE_NOT_FOUND`, `ERR_LANDLORD_NOT_FOUND`,
    `ERR_JURISDICTION_NOT_FOUND`, `ERR_LEASE_NOT_FOUND`,
    `ERR_ZONING_APPLICATION_NOT_FOUND`, `ERR_STRUCTURAL_ANALYSIS_NOT_FOUND`,
    `ERR_MODIFICATION_DESIGN_NOT_FOUND`, `ERR_ENVIRONMENTAL_REVIEW_NOT_FOUND`,
    `ERR_PERMIT_NOT_FOUND`, `ERR_UTILITY_PROVIDER_NOT_FOUND`,
    `ERR_BACKHAUL_ORDER_NOT_FOUND` or `ERR_ON_AIR_PLAN_NOT_FOUND`."

    PRD: "The `meta` object for error responses contains only `api_request_id` and
    `api_request_timestamp`."

    PRD: "The `error_id` is a unique, machine-readable string that identifies the
    specific error."

    Design: Corner/errors/corner_unknown_path_ids_return_entity_specific_not_found
    """
    S.reset_clock(api)

    missing_ring = api.get_search_ring(UNKNOWN_ID, headers=S.director())
    failed(missing_ring, ApiError.SEARCH_RING_NOT_FOUND, expected_status=404)
    assert_error_data_shape(missing_ring)
    assert_error_meta_shape(missing_ring)

    missing_candidate = api.get_candidate(UNKNOWN_ID, headers=S.director())
    failed(missing_candidate, ApiError.CANDIDATE_NOT_FOUND, expected_status=404)
    assert_error_data_shape(missing_candidate)

    missing_plan = api.get_on_air_plan(UNKNOWN_ID, headers=S.director())
    failed(missing_plan, ApiError.ON_AIR_PLAN_NOT_FOUND, expected_status=404)
    assert_error_data_shape(missing_plan)


def test_a_create_without_identity_headers_is_unauthenticated_and_stores_nothing(
    api: ApiClient,
) -> None:
    """Authentication is the first tier, so the write never reaches the ring table.

    PRD: "Every request must carry two headers: `X-User-ID`, identifying the acting
    operator, and `X-User-Role`, declaring the capacity in which they act. If either
    header is missing or empty, or if `X-User-Role` is not one of the seven role names
    below, the request is rejected with `ERR_UNAUTHENTICATED` (401)."

    PRD: "1. Header authentication — `ERR_UNAUTHENTICATED`, on every endpoint."

    Design: Corner/errors/corner_missing_role_header_returns_unauthenticated
    """
    S.reset_clock(api)

    refused = api.create_search_ring(F.search_ring_payload(), headers=NO_AUTH_HEADERS)
    failed(refused, ApiError.UNAUTHENTICATED, expected_status=401)
    assert_error_data_shape(refused)

    rows, meta = page(api.list_search_rings(headers=S.director()))
    assert rows == [], "the unauthenticated create stored nothing"
    assert_pagination_meta(meta, total_count=0)


def test_a_limit_of_one_hundred_and_one_is_refused_while_one_hundred_is_accepted(
    api: ApiClient,
) -> None:
    """The ceiling is inclusive: 100 reads, 101 is a pagination-bounds refusal.

    PRD: "`limit` sets the maximum number of records returned; it defaults to 10, may
    not be less than 1, and may not exceed 100."

    PRD: "A `limit` outside the range 1 through 100, or a negative `offset`, is rejected
    with `ERR_INVALID_PAGINATION` (400)."

    PRD: "The `meta` object of a list response carries `limit`, `offset`, `total_count`
    and `has_more`."

    Design: Corner/errors/corner_invalid_pagination_limit_rejected
    """
    S.reset_clock(api)

    refused = api.list_search_rings(
        {"limit": LIMIT_ONE_ABOVE_CEILING, "offset": 0}, headers=S.director()
    )
    failed(refused, ApiError.INVALID_PAGINATION, expected_status=400)
    assert_error_data_shape(refused)

    rows, meta = page(
        api.list_search_rings({"limit": LIMIT_AT_CEILING, "offset": 0}, headers=S.director())
    )
    assert rows == [], "the empty database returns no rows"
    assert_pagination_meta(
        meta, total_count=0, limit=LIMIT_AT_CEILING, offset=0, has_more=False
    )
