"""Barrel export: framework generics + PRD-specific infrastructure."""

# Framework generics (re-exported so tests have one import source)
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
    ADMIN_USER_ID,
    CARE_1_USER_ID,
    CARE_2_USER_ID,
    CARE_3_USER_ID,
    CARE_4_USER_ID,
    COMPLIANCE_ALT_USER_ID,
    COMPLIANCE_USER_ID,
    MANAGER_ALT_USER_ID,
    MANAGER_USER_ID,
    NO_AUTH_HEADERS,
    SPECIALIST_ALT_USER_ID,
    SPECIALIST_USER_ID,
    TEST_USERS,
    make_bill_pay_specialist_headers,
    make_care_coordinator_headers,
    make_client_headers,
    make_compliance_officer_headers,
    make_family_recipient_headers,
    make_fiduciary_manager_headers,
    make_platform_admin_headers,
)
from .types import *  # noqa: F401,F403
