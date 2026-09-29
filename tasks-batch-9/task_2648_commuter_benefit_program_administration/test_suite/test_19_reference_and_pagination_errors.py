"""Authentication, path-reference integrity and pagination-bound rejections.

Three system-wide gates are exercised here, each one in isolation so that only a
single check can possibly fail:

* the header gate that runs before every other check in the service,
* the left-to-right path identifier resolution that answers with one distinct
  404 code per entity kind, and
* the declared 1..100 / >= 0 pagination window on a list endpoint.
"""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import (
    PROGRAM_ADMIN,
    ROLE_COMPLIANCE_REVIEWER,
    ROLE_ORDER_DESK,
    ROLE_PAYROLL_PROCESSOR,
    ROLE_PROGRAM_ADMIN,
    assert_pagination_meta,
    fixtures,
    make_headers,
)
from test_helpers.api_errors import (
    ERR_CARD_TRANSACTION_NOT_FOUND,
    ERR_ELECTION_WINDOW_NOT_FOUND,
    ERR_EMPLOYER_NOT_FOUND,
    ERR_BENEFIT_ACCOUNT_NOT_FOUND,
    ERR_INVALID_PAGINATION,
    ERR_MEDIA_ORDER_NOT_FOUND,
    ERR_ORDER_BATCH_NOT_FOUND,
    ERR_PAYROLL_FILE_NOT_FOUND,
    ERR_SUBSTANTIATION_CLAIM_NOT_FOUND,
    ERR_TRANSIT_MEDIA_NOT_FOUND,
    ERR_UNAUTHENTICATED,
)
from test_helpers.constants import MAX_PAGE_LIMIT, REGION_AUS

# A well-formed UUID that is deliberately not the id of any row in the service.
UNKNOWN_ID = "00000000-0000-4000-8000-00000000dead"


def test_01_read_without_role_header_is_unauthenticated(api):
    """PRD 2.1: "Every request to the service must carry two headers: `X-User-ID`, identifying the acting
    principal, and `X-User-Role`, declaring the capability set the caller is acting under."
    PRD 2.1: "If either header is absent, or if `X-User-Role` carries a value outside the five roles
    defined below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/missing_x_user_role_header_returns_unauthenticated
    """
    employer = fixtures.make_draft_employer(
        api,
        PROGRAM_ADMIN,
        legal_name="Auth Gate Co",
        region_code=REGION_AUS,
        transit_group_limit_cents=30000,
        parking_group_limit_cents=30000,
        program_cap_cents=5000000,
    )

    headerless = {"X-User-ID": "admin-probe", "Content-Type": "application/json"}
    response = api.raw("GET", f"/benefits/employers/{employer['id']}", None, headerless)

    # The employer id really exists, so a 404 would prove the header gate was skipped.
    validate_error(response, ERR_UNAUTHENTICATED)


def test_02_read_with_undeclared_role_is_unauthenticated(api):
    """PRD 2.1: "If either header is absent, or if `X-User-Role` carries a value outside the five roles
    defined below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD 2.1: "The five roles are `ProgramAdmin`, `Employee`, `OrderDesk`, `ComplianceReviewer` and
    `PayrollProcessor`."

    Design: Corner/errors/missing_x_user_role_header_returns_unauthenticated
    """
    employer = fixtures.make_draft_employer(
        api,
        PROGRAM_ADMIN,
        legal_name="Auth Gate Co",
        region_code=REGION_AUS,
        transit_group_limit_cents=30000,
        parking_group_limit_cents=30000,
        program_cap_cents=5000000,
    )

    undeclared = make_headers("SuperAdmin", "admin-probe")
    response = api.raw("GET", f"/benefits/employers/{employer['id']}", None, undeclared)

    # An undeclared role fails authentication, not authorization: the 403 of a role
    # acting outside its remit is reserved for the five declared roles.
    validate_error(response, ERR_UNAUTHENTICATED)


# One probe per single-resource read, each one called by a role the operation
# authorizes so that only the identifier resolution can fail.
NOT_FOUND_PROBES = [
    ("employer", f"/benefits/employers/{UNKNOWN_ID}", ROLE_PROGRAM_ADMIN,
     "admin-probe", ERR_EMPLOYER_NOT_FOUND),
    ("election_window", f"/benefits/election-windows/{UNKNOWN_ID}", ROLE_PROGRAM_ADMIN,
     "admin-probe", ERR_ELECTION_WINDOW_NOT_FOUND),
    ("benefit_account", f"/benefits/benefit-accounts/{UNKNOWN_ID}", ROLE_PROGRAM_ADMIN,
     "admin-probe", ERR_BENEFIT_ACCOUNT_NOT_FOUND),
    ("transit_media", f"/benefits/transit-media/{UNKNOWN_ID}", ROLE_ORDER_DESK,
     "desk-probe", ERR_TRANSIT_MEDIA_NOT_FOUND),
    ("order_batch", f"/benefits/order-batches/{UNKNOWN_ID}", ROLE_ORDER_DESK,
     "desk-probe", ERR_ORDER_BATCH_NOT_FOUND),
    ("media_order", f"/benefits/media-orders/{UNKNOWN_ID}", ROLE_ORDER_DESK,
     "desk-probe", ERR_MEDIA_ORDER_NOT_FOUND),
    ("card_transaction", f"/benefits/card-transactions/{UNKNOWN_ID}",
     ROLE_COMPLIANCE_REVIEWER, "rev-probe", ERR_CARD_TRANSACTION_NOT_FOUND),
    ("substantiation_claim", f"/benefits/substantiation-claims/{UNKNOWN_ID}",
     ROLE_COMPLIANCE_REVIEWER, "rev-probe", ERR_SUBSTANTIATION_CLAIM_NOT_FOUND),
    ("payroll_file", f"/benefits/payroll-files/{UNKNOWN_ID}", ROLE_PAYROLL_PROCESSOR,
     "pay-probe", ERR_PAYROLL_FILE_NOT_FOUND),
]


@pytest.mark.parametrize(
    "entity_label,path,role,user_id,expected_error_id",
    NOT_FOUND_PROBES,
    ids=[probe[0] for probe in NOT_FOUND_PROBES],
)
def test_03_unknown_path_id_returns_the_entity_specific_not_found_code(
    api, entity_label, path, role, user_id, expected_error_id
):
    """PRD 2.6: "Path parameters are resolved strictly left to right, and the first identifier that fails
    to resolve determines the error returned."
    PRD 2.6: "A failure yields HTTP 404 carrying the code for the entity that could not be found:
    `ERR_EMPLOYER_NOT_FOUND`, `ERR_EMPLOYEE_NOT_FOUND`, `ERR_ELECTION_WINDOW_NOT_FOUND`,
    `ERR_BENEFIT_CATEGORY_NOT_FOUND`, `ERR_BENEFIT_ACCOUNT_NOT_FOUND`, `ERR_ELECTION_NOT_FOUND`,
    `ERR_TRANSIT_MEDIA_NOT_FOUND`, `ERR_ORDER_BATCH_NOT_FOUND`, `ERR_MEDIA_ORDER_NOT_FOUND`,
    `ERR_CARD_TRANSACTION_NOT_FOUND`, `ERR_SUBSTANTIATION_CLAIM_NOT_FOUND` or
    `ERR_PAYROLL_FILE_NOT_FOUND`."

    Design: Corner/errors/unknown_path_ids_return_the_entity_specific_not_found_error
    """
    response = api.raw("GET", path, None, make_headers(role, user_id))

    # A single generic not-found code, or one entity's code reused everywhere, fails here.
    validate_error(response, expected_error_id)


def test_04_page_limit_below_one_is_rejected(api):
    """PRD 2.3: "`limit` defaults to 10 when omitted, must be an integer no smaller than 1, and must
    not exceed 100."
    PRD 2.3: "A `limit` below 1 or above 100, or a negative `offset`, is rejected with
    `ERR_INVALID_PAGINATION` (HTTP 422)."

    Design: Corner/errors/out_of_range_limit_and_negative_offset_are_rejected
    """
    fixtures.make_draft_employer(api, PROGRAM_ADMIN, legal_name="Page Guard Co")

    response = api.list_employers(PROGRAM_ADMIN, {"limit": 0})

    # A silent clamp to the default page size would answer 200 here.
    validate_error(response, ERR_INVALID_PAGINATION)


def test_05_page_limit_above_one_hundred_is_rejected(api):
    """PRD 2.3: "`limit` defaults to 10 when omitted, must be an integer no smaller than 1, and must
    not exceed 100."
    PRD 2.3: "A `limit` below 1 or above 100, or a negative `offset`, is rejected with
    `ERR_INVALID_PAGINATION` (HTTP 422)."

    Design: Corner/errors/out_of_range_limit_and_negative_offset_are_rejected
    """
    fixtures.make_draft_employer(api, PROGRAM_ADMIN, legal_name="Page Guard Co")

    response = api.list_employers(PROGRAM_ADMIN, {"limit": MAX_PAGE_LIMIT + 1})

    validate_error(response, ERR_INVALID_PAGINATION)


def test_06_negative_page_offset_is_rejected(api):
    """PRD 2.3: "`offset` defaults to 0 when omitted and must be an integer no smaller than 0."
    PRD 2.3: "A `limit` below 1 or above 100, or a negative `offset`, is rejected with
    `ERR_INVALID_PAGINATION` (HTTP 422)."

    Design: Corner/errors/out_of_range_limit_and_negative_offset_are_rejected
    """
    fixtures.make_draft_employer(api, PROGRAM_ADMIN, legal_name="Page Guard Co")

    response = api.list_employers(PROGRAM_ADMIN, {"offset": -1})

    validate_error(response, ERR_INVALID_PAGINATION)


def test_07_largest_legal_page_window_is_accepted(api):
    """PRD 2.3: "`limit` defaults to 10 when omitted, must be an integer no smaller than 1, and must
    not exceed 100."
    PRD 2.3: "`limit` and `offset` echo the effective values used, `total_count` reports the number of
    rows matching the filters before the page window is applied, and `has_more` is true exactly when
    rows remain beyond the current page."

    Design: Corner/errors/out_of_range_limit_and_negative_offset_are_rejected
    """
    fixtures.make_draft_employer(api, PROGRAM_ADMIN, legal_name="Page Guard Co")

    response = api.list_employers(PROGRAM_ADMIN, {"limit": MAX_PAGE_LIMIT, "offset": 0})

    data, meta = validate_paginated(response)
    assert_pagination_meta(meta, MAX_PAGE_LIMIT, 0, 1, False)
    assert [row["legal_name"] for row in data] == ["Page Guard Co"], (
        f"the one registered employer must be the only row returned, got {data}"
    )
