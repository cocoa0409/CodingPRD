"""Test helpers for the equestrian show management & point recording API."""

from prd_bench_local_runner.testing import (
    GenericApiClient,
    NON_EXISTENT_UUID,
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
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .test_users import (
    NO_AUTH_HEADERS,
    OPAQUE_USER_IDS,
    TEST_USERS,
    make_exhibitor_headers,
    make_headers,
    make_judge_headers,
    make_steward_headers,
)

__all__ = [
    # framework generics
    "GenericApiClient",
    "NON_EXISTENT_UUID",
    "assert_at_least_one_succeeds",
    "assert_cost_precision",
    "assert_exactly_one_succeeds",
    "assert_race_outcome",
    "assert_timestamp_format",
    "assert_version_incremented",
    "build_user_headers",
    "get_success_data",
    "is_iso8601_timestamp",
    "is_valid_uuid",
    "run_race",
    "validate_error",
    "validate_error_is_one_of",
    "validate_paginated",
    "validate_success",
    # domain modules
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "types",
    # domain objects
    "ApiClient",
    "api_client",
    "ApiErrorId",
    "HTTP_STATUS_CODES",
    "TEST_USERS",
    "NO_AUTH_HEADERS",
    "OPAQUE_USER_IDS",
    "make_exhibitor_headers",
    "make_judge_headers",
    "make_steward_headers",
    "make_headers",
]
