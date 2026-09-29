"""Test infrastructure for the Municipal Annexation And Boundary Adjustment API.

Tests import everything they need from this package. The framework validators,
race helpers and header builder are re-exported alongside the domain-specific
client, factories, fixtures and assertions.
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

from . import api_errors, assertions, constants, factories, fixtures, types
from .api_client import AnnexationApiClient
from .api_errors import ERROR_HTTP_STATUS, register_error_status_map
from .test_users import (
    BOUNDARY_COMMISSIONER_ALT_USER_ID,
    BOUNDARY_COMMISSIONER_USER_ID,
    COUNTY_ASSESSOR_USER_ID,
    FISCAL_ANALYST_ALT_USER_ID,
    FISCAL_ANALYST_USER_ID,
    STATE_LAW_ADMIN_USER_ID,
    TEST_USERS,
    boundary_commissioner_headers,
    county_assessor_headers,
    fiscal_analyst_headers,
    make_city_clerk_headers,
    make_headers,
    make_municipal_planner_headers,
    make_property_owner_headers,
    state_law_admin_headers,
)
from .types import UserRole

__all__ = [
    # framework re-exports
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
    "api_errors",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "types",
    # client and errors
    "AnnexationApiClient",
    "ERROR_HTTP_STATUS",
    "register_error_status_map",
    # actors
    "TEST_USERS",
    "UserRole",
    "STATE_LAW_ADMIN_USER_ID",
    "FISCAL_ANALYST_USER_ID",
    "FISCAL_ANALYST_ALT_USER_ID",
    "BOUNDARY_COMMISSIONER_USER_ID",
    "BOUNDARY_COMMISSIONER_ALT_USER_ID",
    "COUNTY_ASSESSOR_USER_ID",
    "state_law_admin_headers",
    "fiscal_analyst_headers",
    "boundary_commissioner_headers",
    "county_assessor_headers",
    "make_municipal_planner_headers",
    "make_city_clerk_headers",
    "make_property_owner_headers",
    "make_headers",
]
