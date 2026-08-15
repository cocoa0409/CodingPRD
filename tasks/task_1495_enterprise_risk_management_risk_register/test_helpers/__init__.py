"""Barrel export: framework generics + PRD-specific code."""

# Framework generics (re-exported for convenience)
from prd_bench_local_runner.testing import (
    validate_success,
    validate_error,
    validate_paginated,
    validate_error_is_one_of,
    get_success_data,
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
    assert_version_incremented,
    assert_timestamp_format,
    assert_race_outcome,
    assert_exactly_one_succeeds,
    assert_at_least_one_succeeds,
    run_race,
    build_user_headers,
    NON_EXISTENT_UUID,
)

# PRD-specific
from .types import *  # noqa: F401,F403
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .constants import THRESHOLDS, TEST_DEFAULTS
from .test_users import (
    TEST_USERS,
    USER_RISK_OWNER,
    USER_RISK_OWNER_2,
    USER_RISK_MANAGER,
    USER_RISK_MANAGER_2,
    USER_CONTROL_OWNER,
    USER_BOARD_REPORTER,
    USER_INTERNAL_AUDITOR,
    USER_DUAL,
    make_risk_owner_headers,
    make_risk_manager_headers,
    make_control_owner_headers,
    make_board_reporter_headers,
    make_internal_auditor_headers,
)
from .fixtures import *  # noqa: F401,F403
