"""Barrel export: framework generics + PRD-specific code."""
# Framework generics (re-exported for convenience)
from prd_bench_local_runner.testing import (
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
from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (
    ASSESSOR_ID,
    FLEET_ADMIN_ID,
    LEASING_AGENT_ID,
    SECOND_ASSESSOR_ID,
    SECOND_FLEET_ADMIN_ID,
    TEST_USERS,
    make_branch_ops_headers,
    make_customer_headers,
    make_damage_assessor_headers,
    make_fleet_admin_headers,
    make_headers,
    make_leasing_agent_headers,
)
from .types import *  # noqa: F401,F403
