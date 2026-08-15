"""Barrel export: framework generics + PRD-specific helpers."""
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
from .constants import *  # noqa: F401,F403
from .test_users import (
    TEST_USERS,
    TIER_APPROVER_HEADERS,
    make_role_headers,
    USER_SYS_ADMIN,
    USER_SPECIALIST_1,
    USER_SPECIALIST_2,
    USER_VENDOR_MANAGER_1,
    USER_VENDOR_MANAGER_2,
    USER_COMPLIANCE,
    USER_AP_CLERK,
    USER_SUPERVISOR_1,
    USER_SUPERVISOR_2,
    USER_AP_MANAGER,
    USER_CONTROLLER,
    USER_TREASURY_ANALYST,
    USER_TREASURY_MANAGER_1,
    USER_TREASURY_MANAGER_2,
    USER_BANK_PROCESSOR,
    USER_AUDITOR,
    USER_FLOATER,
)
from .fixtures import *  # noqa: F401,F403
