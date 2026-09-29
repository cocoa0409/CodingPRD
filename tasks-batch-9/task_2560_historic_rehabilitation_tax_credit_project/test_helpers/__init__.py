"""Shared test infrastructure for the historic rehabilitation credit service.

Importing this package registers the error-id to HTTP-status map, so tests can
call ``validate_error`` with an error id alone and have the status cross-checked.
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
from .api_client import ApiClient
from .api_errors import (
    ERROR_PRECEDENCE_BANDS,
    HTTP_STATUS_CODES,
    NOT_FOUND_ERROR_IDS,
    ApiErrorId,
)
from .test_users import (
    ALL_ROLES,
    MONITOR,
    PLATFORM_ADMIN,
    TEST_USERS,
    make_compliance_monitor_headers,
    make_developer_headers,
    make_headers,
    make_headers_with_empty_user_id,
    make_headers_without_user_id,
    make_investor_admin_headers,
    make_nps_reviewer_headers,
    make_platform_admin_headers,
    make_shpo_reviewer_headers,
)

__all__ = [
    "ApiClient",
    "ApiErrorId",
    "ERROR_PRECEDENCE_BANDS",
    "HTTP_STATUS_CODES",
    "NOT_FOUND_ERROR_IDS",
    "NON_EXISTENT_UUID",
    "GenericApiClient",
    "ALL_ROLES",
    "MONITOR",
    "PLATFORM_ADMIN",
    "TEST_USERS",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "types",
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
    "make_compliance_monitor_headers",
    "make_developer_headers",
    "make_headers",
    "make_headers_with_empty_user_id",
    "make_headers_without_user_id",
    "make_investor_admin_headers",
    "make_nps_reviewer_headers",
    "make_platform_admin_headers",
    "make_shpo_reviewer_headers",
    "run_race",
    "validate_error",
    "validate_error_is_one_of",
    "validate_paginated",
    "validate_success",
]
