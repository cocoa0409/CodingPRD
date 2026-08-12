"""Barrel export: framework generics + PRD-specific test infrastructure."""
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
from .types import *  # noqa: F401,F403
from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .test_users import (
    ADMIN_ID,
    ANALYST_ID,
    AUDIT_LEAD_ID,
    FINANCE_1_ID,
    FINANCE_2_ID,
    OFFICER_1_ID,
    OFFICER_2_ID,
    SPONSOR_1_ID,
    SPONSOR_2_ID,
    SPONSOR_9_ID,
    TEST_USERS,
    admin_headers,
    analyst_headers,
    audit_headers,
    finance_headers,
    officer_headers,
    sponsor_headers,
)
from .fixtures import *  # noqa: F401,F403
