"""Test infrastructure for the correctional food service operations API.

Re-exports the shared framework utilities alongside the domain-specific client,
error catalogue, factories, assertions and composite fixtures so that test
modules need a single import.
"""

# --- Shared framework --------------------------------------------------------
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

# --- Domain-specific ---------------------------------------------------------
from . import assertions, constants, factories, fixtures, test_users, types
from .api_client import PREFIX, ApiClient
from .api_errors import ERROR_HTTP_STATUS, NOT_FOUND_BY_COLLECTION, ApiErrorId

__all__ = [
    # framework
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
    # domain
    "ApiClient",
    "ApiErrorId",
    "ERROR_HTTP_STATUS",
    "NOT_FOUND_BY_COLLECTION",
    "PREFIX",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "test_users",
    "types",
]
