"""Test helpers for the Convention Center Booking & Event Services API."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    GenericApiClient,
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
    ANALYST_ONE,
    ANALYST_TWO,
    EVENT_SERVICES_MANAGER_ID,
    FACILITIES_PLANNER_ID,
    NO_HEADERS,
    SALES_MANAGER_ID,
    SETTLEMENT_ANALYST_ID,
    SETTLEMENT_ANALYST_TWO_ID,
    TEST_USERS,
    VENUE_ADMIN_ID,
    make_analyst_headers,
    make_headers,
    make_licensee_headers,
)
from .types import *  # noqa: F401,F403
