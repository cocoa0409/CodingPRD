"""Test helpers for the warehouse line-of-credit API.

Re-exports the shared framework generics alongside this task's domain-specific
client, factories, fixtures, assertions and constants so that test modules can
import everything from one place.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    GenericApiClient,
    assert_at_least_one_succeeds,
    assert_cost_precision,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    assert_timestamp_format,
    assert_version_incremented,
    build_user_headers,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    run_race,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

from . import assertions, constants, factories, fixtures, types
from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, NOT_FOUND_CODE_BY_SEGMENT, ApiErrorId
from .test_users import (
    COLLATERAL_ANALYST,
    CONTENT_TYPE_ONLY,
    CREDIT_OFFICER,
    SECOND_COLLATERAL_ANALYST,
    SECOND_CREDIT_OFFICER,
    SECOND_WIRE_OPERATOR,
    TEST_USERS,
    WIRE_OPERATOR,
    headers_for_role,
    make_borrower_headers,
    make_collateral_analyst_headers,
    make_credit_officer_headers,
    make_custodian_headers,
    make_investor_headers,
    make_wire_operator_headers,
)

__all__ = [
    # framework generics
    "GenericApiClient",
    "validate_success",
    "validate_error",
    "validate_error_is_one_of",
    "validate_paginated",
    "get_success_data",
    "is_valid_uuid",
    "is_iso8601_timestamp",
    "assert_cost_precision",
    "assert_version_incremented",
    "assert_timestamp_format",
    "assert_race_outcome",
    "assert_exactly_one_succeeds",
    "assert_at_least_one_succeeds",
    "run_race",
    "build_user_headers",
    "NON_EXISTENT_UUID",
    # task modules
    "types",
    "constants",
    "factories",
    "assertions",
    "fixtures",
    # client
    "ApiClient",
    "api_client",
    # errors
    "ApiErrorId",
    "HTTP_STATUS_CODES",
    "NOT_FOUND_CODE_BY_SEGMENT",
    # identities
    "TEST_USERS",
    "CREDIT_OFFICER",
    "SECOND_CREDIT_OFFICER",
    "COLLATERAL_ANALYST",
    "SECOND_COLLATERAL_ANALYST",
    "WIRE_OPERATOR",
    "SECOND_WIRE_OPERATOR",
    "CONTENT_TYPE_ONLY",
    "make_borrower_headers",
    "make_custodian_headers",
    "make_investor_headers",
    "make_credit_officer_headers",
    "make_collateral_analyst_headers",
    "make_wire_operator_headers",
    "headers_for_role",
]
