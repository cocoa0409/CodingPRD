"""Test infrastructure for the marketing-mix modelling and incrementality API.

Re-exports the shared framework utilities alongside the domain client, the error
catalogue, the payload factories, the shape assertions and the layered fixtures,
so a test module needs a single import line.

Importing this package also registers the error_id to HTTP status mapping with
the shared validators, so `validate_error` cross-checks the status code.
"""

# --- Shared framework -------------------------------------------------------
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

# --- Domain-specific --------------------------------------------------------
from . import assertions, constants, factories, fixtures, test_users, types
from .api_client import PREFIX, ApiClient
from .api_errors import ERROR_HTTP_STATUS, NOT_FOUND_BY_COLLECTION, ApiErrorId

__all__ = [
    # framework
    "NON_EXISTENT_UUID",
    "GenericApiClient",
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
