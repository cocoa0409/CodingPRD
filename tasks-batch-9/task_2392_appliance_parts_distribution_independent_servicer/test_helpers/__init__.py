"""Barrel export: framework generics plus the PRD-specific test infrastructure."""
# Framework generics (re-exported so tests have one import source)
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

# PRD-specific
from .api_client import ApiClient, api_client  # noqa: F401
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    CREDIT_MANAGER,
    CREDIT_MANAGER_TWO,
    CREDIT_MANAGER_USER_ONE,
    CREDIT_MANAGER_USER_TWO,
    PLATFORM_ADMIN,
    PLATFORM_ADMIN_USER_ONE,
    PRICING_ADMIN,
    PRICING_ADMIN_USER_ONE,
    TEST_USERS,
    WARRANTY_ADMIN,
    WARRANTY_ADMIN_USER_ONE,
    make_branch_counter_rep_headers,
    make_credit_manager_headers,
    make_platform_admin_headers,
    make_pricing_admin_headers,
    make_servicer_headers,
    make_warranty_admin_headers,
)
from .types import *  # noqa: F401,F403
