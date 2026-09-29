"""Test helper package for the themed attraction development API.

Re-exports the shared harness utilities alongside this domain's own client,
error catalogue, assertions, factories, constants, identities and setup chains,
so a test module needs one import site.
"""
from prd_bench_local_runner.testing import (  # noqa: F401
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

from .api_client import ApiClient, api_client  # noqa: F401
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .constants import DEFAULT_LOGICAL_CLOCK_UTC, TEST_DEFAULTS, THRESHOLDS  # noqa: F401
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    CONTRACTOR_PM_USER_ID,
    CREATIVE_DIRECTOR_USER_ID,
    NO_IDENTITY_HEADERS,
    OWNER_REP_USER_ID,
    PROGRAM_ADMIN_USER_ID,
    RIDE_ENGINEER_USER_ID,
    SECOND_OWNER_REP_USER_ID,
    SHOW_PROGRAMMER_USER_ID,
    TEST_USERS,
    THIRD_PARTY_REVIEWER_USER_ID,
    make_contractor_pm_headers,
    make_creative_director_headers,
    make_owner_rep_headers,
    make_program_admin_headers,
    make_ride_engineer_headers,
    make_show_programmer_headers,
    make_third_party_reviewer_headers,
)
from .types import *  # noqa: F401,F403
