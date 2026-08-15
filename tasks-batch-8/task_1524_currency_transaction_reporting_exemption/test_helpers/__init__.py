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
from .test_users import (  # noqa: F401
    TEST_USERS,
    OPERATOR_ADMIN,
    OPERATOR_MANAGER,
    OPERATOR_TELLER,
    OPERATOR_ANALYST_X,
    OPERATOR_OFFICER_A,
    OPERATOR_OFFICER_B,
    OPERATOR_OFFICER_C,
    OPERATOR_OFFICER_Y,
    OPERATOR_OFFICER_Z,
    OPERATOR_EXAMINER,
    make_admin_headers,
    make_manager_headers,
    make_teller_headers,
    make_analyst_headers,
    make_officer_headers,
    make_examiner_headers,
)
from .fixtures import *  # noqa: F401,F403
