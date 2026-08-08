"""Barrel export: framework generics plus the PRD-specific test infrastructure."""

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
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    ADMIN,
    ADMIN_ONE_ID,
    ADMIN_TWO,
    ADMIN_TWO_ID,
    ANON,
    ANONYMOUS_ID,
    INSPECTOR,
    INSPECTOR_ONE_ID,
    INSPECTOR_TWO,
    INSPECTOR_TWO_ID,
    PLAN_REVIEWER,
    PLAN_REVIEWER_ONE_ID,
    PLAN_REVIEWER_TWO,
    PLAN_REVIEWER_TWO_ID,
    TEST_USERS,
    make_admin_headers,
    make_headers,
    make_inspector_headers,
    make_operator_headers,
    make_plan_reviewer_headers,
)
from .types import *  # noqa: F401,F403
