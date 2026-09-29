"""Test helpers for the Mattress Recycling Program API suite.

Importing this package registers the error-id to HTTP-status map, so
`validate_error` cross-checks the status code of every asserted error.
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
    ADMIN_1_USER_ID,
    ADMIN_2_USER_ID,
    ADMIN_3_USER_ID,
    AUDITOR_1_USER_ID,
    AUDITOR_2_USER_ID,
    NO_AUTH_HEADERS,
    TEST_USERS,
    make_admin_headers,
    make_auditor_headers,
    make_hauler_headers,
    make_recycler_headers,
    make_registrant_headers,
    make_site_operator_headers,
    make_unrecognised_role_headers,
)
from .types import *  # noqa: F401,F403
