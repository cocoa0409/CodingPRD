"""Test infrastructure for the mammography accreditation and breast density
notification service.

Re-exports the framework primitives alongside the PRD-specific client,
factories, assertions, constants and composite fixtures so a test file needs a
single import.
"""

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
    NO_HEADERS,
    TEST_USERS,
    UNKNOWN_ROLE_HEADERS,
    make_coordinator_headers,
    make_inspector_headers,
    make_physician_headers,
    make_physicist_headers,
    make_qa_headers,
    make_reviewer_headers,
    make_technologist_headers,
)
from .types import *  # noqa: F401,F403
