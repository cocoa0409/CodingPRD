"""Test infrastructure for the grid-scale battery storage platform.

Importing this package registers the error-identifier to HTTP-status map that
the framework's error validators consult, so every `validate_error` call gets
its expected HTTP status for free.
"""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    GenericApiClient,
    assert_timestamp_format,
    build_user_headers,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import ApiClient, api_client
from test_helpers.api_errors import HTTP_STATUS_CODES, ApiErrorId
from test_helpers.test_users import (
    SECOND_ASSET_MANAGER,
    SECOND_PLATFORM_ADMIN,
    SECOND_SAFETY_OFFICER,
    TEST_USERS,
    make_asset_manager_headers,
    make_control_room_headers,
    make_headers,
    make_market_operator_headers,
    make_market_trader_headers,
    make_platform_admin_headers,
    make_safety_officer_headers,
    make_site_controller_headers,
)

__all__ = [
    "ApiClient",
    "ApiErrorId",
    "GenericApiClient",
    "HTTP_STATUS_CODES",
    "NON_EXISTENT_UUID",
    "SECOND_ASSET_MANAGER",
    "SECOND_PLATFORM_ADMIN",
    "SECOND_SAFETY_OFFICER",
    "TEST_USERS",
    "api_client",
    "assert_timestamp_format",
    "build_user_headers",
    "get_success_data",
    "is_iso8601_timestamp",
    "is_valid_uuid",
    "make_asset_manager_headers",
    "make_control_room_headers",
    "make_headers",
    "make_market_operator_headers",
    "make_market_trader_headers",
    "make_platform_admin_headers",
    "make_safety_officer_headers",
    "make_site_controller_headers",
    "validate_error",
    "validate_error_is_one_of",
    "validate_paginated",
    "validate_success",
]
