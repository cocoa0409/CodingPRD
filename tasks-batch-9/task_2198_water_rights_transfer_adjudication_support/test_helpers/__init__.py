"""Test helpers for the water rights transfer and adjudication support service.

A single import surface for the test suite: the framework's validators plus the
domain-specific client, factories, assertions, constants and setup fixtures.
"""
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

from . import fixtures
from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .test_users import (
    ADJUDICATOR_USER_ID,
    ANALYST_USER_ID,
    ANALYST_USER_ID_ALT,
    DECIDER_USER_ID,
    DECIDER_USER_ID_ALT,
    HEADERS_BY_ROLE,
    HEARING_USER_ID,
    HEARING_USER_ID_ALT,
    TEST_USERS,
    UNOWNED_CLAIMANT_USER_ID,
    make_analyst_headers,
    make_basin_adjudicator_headers,
    make_claimant_headers,
    make_decision_authority_headers,
    make_headers,
    make_hearing_officer_headers,
)
from .types import *  # noqa: F401,F403
