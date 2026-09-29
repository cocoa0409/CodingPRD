"""Barrel export: framework generics plus the PRD-specific test infrastructure."""
from prd_bench_local_runner.testing import (  # noqa: F401
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

from . import factories  # noqa: F401
from .api_client import ApiClient, api_client  # noqa: F401
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    ALL_ROLES,
    EMPTY_IDENTITY_HEADERS,
    NO_IDENTITY_HEADERS,
    ROLE_BMS_GATEWAY,
    ROLE_ENERGY_ANALYST,
    ROLE_ENERGY_MANAGER,
    ROLE_FOOD_SAFETY_OFFICER,
    ROLE_MAINTENANCE_TECH,
    ROLE_PLATFORM_ADMIN,
    ROLE_STORE_MANAGER,
    TEST_USERS,
    make_bms_gateway_headers,
    make_energy_analyst_headers,
    make_energy_manager_headers,
    make_food_safety_officer_headers,
    make_headers_for_role,
    make_maintenance_tech_headers,
    make_platform_admin_headers,
    make_store_manager_headers,
)
from .types import *  # noqa: F401,F403
