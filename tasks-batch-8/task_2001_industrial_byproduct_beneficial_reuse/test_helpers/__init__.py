"""Barrel export: framework generics + PRD-specific helpers."""
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
from .types import *
from .api_client import ApiClient, api_client
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import *
from .factories import *
from .constants import *
from .test_users import (
    BROKER_OPS_USER_ID,
    CO_APPR_USER_ID,
    CO_FILE_USER_ID,
    PLATFORM_ADMIN_USER_ID,
    TEST_USERS,
    make_broker_ops_headers,
    make_compliance_officer_headers,
    make_generator_headers,
    make_offtaker_headers,
    make_platform_admin_headers,
)
from .fixtures import *
