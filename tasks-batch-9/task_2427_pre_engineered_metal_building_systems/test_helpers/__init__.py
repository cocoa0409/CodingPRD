"""Barrel export: framework generics plus the code specific to this API."""

# Framework generics (re-exported so tests have a single import source).
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

# API-specific code.
from .api_client import ApiClient, api_client  # noqa: F401
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    ALL_ROLE_NAMES,
    ENGINEER_TWO_USER_ID,
    ENGINEER_USER_ID,
    ENGINEERING_MANAGER_TWO_USER_ID,
    ENGINEERING_MANAGER_USER_ID,
    SEALING_ENGINEER_USER_ID,
    TEST_USERS,
    make_builder_headers,
    make_engineer_headers,
    make_engineering_manager_headers,
    make_logistics_coordinator_headers,
    make_platform_admin_headers,
    make_production_planner_headers,
    make_sales_engineer_headers,
    make_sealing_engineer_headers,
)
from .types import *  # noqa: F401,F403
