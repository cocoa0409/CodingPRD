"""Test support for the Regional Climate Adaptation & Resilience Planning API."""

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

from .api_client import BASE, ApiClient, api_client
from .api_errors import (
    HTTP_STATUS_CODES,
    NOT_FOUND_CODE_BY_PATH_ID,
    ApiErrorId,
)
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (
    ALL_ROLE_NAMES,
    BCA_REVIEWER_USER_ID,
    EQUITY_OFFICER_USER_ID,
    HAZARD_ANALYST_USER_ID,
    REGIONAL_ADMINISTRATOR_USER_ID,
    SECOND_BCA_REVIEWER_USER_ID,
    TEST_USERS,
    UNKNOWN_ROLE_NAME,
    UNKNOWN_ROLE_USER_ID,
    all_role_headers,
    make_bca_reviewer_headers,
    make_equity_officer_headers,
    make_hazard_analyst_headers,
    make_jurisdiction_delegate_headers,
    make_project_sponsor_headers,
    make_regional_administrator_headers,
    make_role_headers,
    make_unknown_role_headers,
)
from .types import *  # noqa: F401,F403
