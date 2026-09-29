"""Barrel export: framework generics plus this API's own test infrastructure."""

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

from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (
    ALL_ROLES,
    BRAND_REVIEWER_USER_ID,
    COORDINATOR_USER_ID,
    LEGAL_REVIEWER_USER_ID,
    PLATFORM_ADMIN_USER_ID,
    QUALITY_REVIEWER_USER_ID,
    REGULATORY_REVIEWER_USER_ID,
    ROLE_HEADER_KEYS,
    TEST_USERS,
    headers_for_discipline,
    make_headers,
    make_printer_rep_headers,
)
from .types import *  # noqa: F401,F403
