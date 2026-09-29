"""Barrel export: framework generics + PRD-specific code."""

# Framework generics (re-exported for convenience)
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
from .api_errors import (  # noqa: F401
    HTTP_STATUS_CODES,
    PATH_NOT_FOUND_ERRORS,
    ApiErrorId,
)
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    ALL_ROLE_NAMES,
    CONTROLLER_APPROVER_ID,
    CONTROLLER_DRAFTER_ID,
    CONTROLLER_RESOLVER_ID,
    CONTROLLER_SETTLER_ID,
    PLATFORM_ADMIN_ID,
    PROGRAM_ADMIN_ID,
    TEST_USERS,
    make_controller_headers,
    make_employee_headers,
    make_platform_admin_headers,
    make_program_admin_headers,
    make_restaurant_headers,
)
from .types import *  # noqa: F401,F403
