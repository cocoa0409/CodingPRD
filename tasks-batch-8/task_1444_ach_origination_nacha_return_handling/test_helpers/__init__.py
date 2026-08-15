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
from .types import *  # noqa: F401,F403
from .api_client import ApiClient, api_client  # noqa: F401
from .api_errors import ApiErrorId, HTTP_STATUS_CODES  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .constants import CLOCK_START_ISO, TEST_DEFAULTS, THRESHOLDS  # noqa: F401
from .test_users import (  # noqa: F401
    FINANCE_USER_ID,
    OPERATIONS_USER_ID,
    RISK_OFFICER_USER_ID,
    TEST_USERS,
    UNDERWRITER_USER_ID,
    make_finance_headers,
    make_operations_headers,
    make_originator_headers,
    make_risk_officer_headers,
    make_underwriter_headers,
)
from .fixtures import *  # noqa: F401,F403
