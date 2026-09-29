"""Test infrastructure for the False Alarm Reduction Permit Program suite.

Importing this package registers the error/HTTP-status map with the framework
validators, so ``validate_error(response, ERR_X)`` checks the mandated status
code without the caller repeating it.
"""
from prd_bench_local_runner.testing import (  # noqa: F401
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

from . import api_errors  # noqa: F401  (registers the status map on import)
from . import assertions, constants, factories, fixtures, test_users, types  # noqa: F401
from .api_client import ApiClient, api_client  # noqa: F401

__all__ = [
    "ApiClient",
    "api_client",
    "api_errors",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "test_users",
    "types",
    "GenericApiClient",
    "NON_EXISTENT_UUID",
    "build_user_headers",
    "get_success_data",
    "is_iso8601_timestamp",
    "is_valid_uuid",
    "validate_error",
    "validate_error_is_one_of",
    "validate_paginated",
    "validate_success",
    "assert_at_least_one_succeeds",
    "assert_cost_precision",
    "assert_exactly_one_succeeds",
    "assert_race_outcome",
    "assert_timestamp_format",
    "assert_version_incremented",
    "run_race",
]
