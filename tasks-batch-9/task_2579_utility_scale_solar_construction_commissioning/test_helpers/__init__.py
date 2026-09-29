"""Test helper package for the Utility-Scale Solar Construction & Commissioning API.

Re-exports the framework primitives alongside the domain client, error
catalogue, constants, factories, assertions and composite builders, so a test
module imports everything it needs from one place.
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

from . import assertions, constants, factories, fixtures, test_users, types
from .api_client import ApiClient, api_client
from .api_errors import ERROR_HTTP_STATUS
from .assertions import (
    assert_block_counters,
    assert_cents,
    assert_commissioning_result,
    assert_common_fields,
    assert_compliance_run,
    assert_contains_id,
    assert_created_fresh,
    assert_delivery_receipt,
    assert_excludes_id,
    assert_grading_area_state,
    assert_hour_conservation,
    assert_ids_equal,
    assert_instant_equals,
    assert_page_meta,
    assert_pallet_conservation,
    assert_pile_disposition,
    assert_project_state,
    assert_ratio,
    assert_same_entity,
    assert_string_test_failure,
    assert_versionless_interval,
    assert_version_is,
    assert_waterfall,
    assert_waterfall_zeroed,
    assert_week_totals,
    assert_zone_occupancy,
)
from .constants import (
    ALL_ROLES,
    BASE_PROJECT,
    DEFAULT_CLOCK,
    DEFAULT_LIMIT,
    MAX_LIMIT,
    ROLE_CIVIL_SUPERINTENDENT,
    ROLE_COMMISSIONING_ENGINEER,
    ROLE_EPC_PROJECT_MANAGER,
    ROLE_INSTALLATION_FOREMAN,
    ROLE_LABOR_COMPLIANCE_OFFICER,
    ROLE_OWNER_ENGINEER,
    ROLE_PROCUREMENT_COORDINATOR,
    ROLE_UTILITY_COORDINATOR,
)
from .test_users import (
    CIVIL_SUPERINTENDENT,
    COMMISSIONING_ENGINEER,
    EPC_PROJECT_MANAGER,
    HEADERS_BY_ROLE,
    INSTALLATION_FOREMAN,
    LABOR_COMPLIANCE_OFFICER,
    OWNER_ENGINEER,
    PROCUREMENT_COORDINATOR,
    TEST_USERS,
    UTILITY_COORDINATOR,
)

__all__ = [
    "ApiClient",
    "api_client",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "test_users",
    "types",
    "ERROR_HTTP_STATUS",
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
]
