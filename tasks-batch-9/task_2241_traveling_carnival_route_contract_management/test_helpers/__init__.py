"""Test infrastructure for the traveling-carnival route and contract API.

Importing this package registers the PRD's error-id to HTTP-status map with the
framework validators, so ``validate_error`` can check the status implied by an
error id without the caller repeating it.
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
    COLLIDING_GENERAL_MANAGER_HEADERS,
    COLLIDING_SENDER_USER_ID,
    GENERAL_MANAGER_USER_ID,
    NEGOTIATOR_SENDER_USER_ID,
    SENDING_GENERAL_MANAGER_HEADERS,
    TEST_USERS,
    make_contract_negotiator_headers,
    make_crew_chief_headers,
    make_general_manager_headers,
    make_platform_admin_headers,
)
from .types import *  # noqa: F401,F403
