"""Barrel export: framework generics plus the Research Billing domain layer."""

# Framework generics, re-exported so tests have one import source.
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

# Domain layer.
from .api_client import ApiClient, api_client  # noqa: F401
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    ANALYST_ONE,
    ANALYST_TWO,
    COORDINATOR_ONE,
    COORDINATOR_SEVEN,
    LIAISON_ONE,
    LIAISON_TWO,
    MANAGER_ONE,
    MANAGER_TWO,
    NO_AUTH_HEADERS,
    REVIEWER_ONE,
    REVIEWER_TWO,
    ROLE_ANALYST,
    ROLE_COORDINATOR,
    ROLE_LIAISON,
    ROLE_MANAGER,
    ROLE_REVIEWER,
    TEST_USERS,
    UNDECLARED_ROLE_HEADERS,
    make_analyst_headers,
    make_coordinator_headers,
    make_liaison_headers,
    make_manager_headers,
    make_reviewer_headers,
)
from .types import *  # noqa: F401,F403
