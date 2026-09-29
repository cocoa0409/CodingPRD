"""Shared test infrastructure for the faculty credentialing PRD suite."""

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

from .types import *  # noqa: F401,F403
from .api_client import api_client, ApiClient  # noqa: F401
from .api_errors import ApiErrorId, HTTP_STATUS_CODES, NOT_FOUND_ERROR_IDS  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    TEST_USERS,
    ADMIN_ID,
    REGISTRAR_ID,
    ANALYST_ID,
    ANALYST_2_ID,
    LIAISON_ID,
    LIAISON_2_ID,
    REVIEWER_ID,
    SHARED_USER_ID,
    make_program_dean_headers,
    make_instructor_headers,
    make_headers,
    anonymous_headers,
)
from .fixtures import *  # noqa: F401,F403
