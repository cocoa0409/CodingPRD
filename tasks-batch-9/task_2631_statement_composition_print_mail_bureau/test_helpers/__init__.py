"""Test infrastructure for the statement composition, print and mail bureau API.

The framework helpers (``GenericApiClient`` and the generic validators) come
from ``prd_bench_local_runner.testing``; everything else in this package is
specific to this contract:

* :mod:`api_errors` — the error identifiers and their HTTP statuses;
* :mod:`types` — role and status enumerations plus response shapes;
* :mod:`constants` — the numeric rules, rates and limits the contract fixes;
* :mod:`test_users` — one caller per role, plus malformed-auth header sets;
* :mod:`api_client` — one typed method per endpoint;
* :mod:`factories` — request payload builders with valid defaults;
* :mod:`assertions` — shape, ledger and arithmetic assertions;
* :mod:`fixtures` — composite builders that walk entities to a target state.

Both the framework helpers and the frequently used local names are re-exported
here so a test module can pull most of what it needs from one place.
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

from . import api_client, assertions, constants, factories, fixtures, test_users, types
from .api_client import ApiClient
from .api_errors import ERROR_HTTP_STATUS, ApiErrorId
from .types import Role

__all__ = [
    # framework re-exports
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
    # submodules
    "api_client",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "test_users",
    "types",
    # frequently used local names
    "ApiClient",
    "ApiErrorId",
    "ERROR_HTTP_STATUS",
    "Role",
]
