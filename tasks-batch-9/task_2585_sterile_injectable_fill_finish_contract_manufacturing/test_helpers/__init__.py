"""Test infrastructure for the Sterile Injectable Fill-Finish CMO API.

Importing this package registers the error catalogue of PRD section 5 with the
framework validator, so `validate_error` cross-checks each asserted `error_id`
against the HTTP status the specification pins for it.
"""
from __future__ import annotations

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
from prd_bench_local_runner.testing.validators import set_error_http_status_map

from . import api_client as api_client_module  # noqa: F401
from . import assertions, constants, factories, fixtures, test_users, types  # noqa: F401
from .api_client import ApiClient, api_client  # noqa: F401
from .api_errors import ERROR_HTTP_STATUS, NOT_FOUND_CODES, ApiErrorId  # noqa: F401

set_error_http_status_map(ERROR_HTTP_STATUS)

__all__ = [
    "ApiClient",
    "ApiErrorId",
    "ERROR_HTTP_STATUS",
    "NOT_FOUND_CODES",
    "NON_EXISTENT_UUID",
    "api_client",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "test_users",
    "types",
    "build_user_headers",
    "get_success_data",
    "is_iso8601_timestamp",
    "is_valid_uuid",
    "validate_error",
    "validate_error_is_one_of",
    "validate_paginated",
    "validate_success",
]
