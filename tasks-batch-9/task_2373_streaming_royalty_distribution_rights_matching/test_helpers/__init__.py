"""Test helper package for the streaming royalty distribution API.

Import everything from here; tests should not reach into submodules directly.
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
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    ADMIN_SETTLE_USER_ID,
    ADMIN_USER_ID,
    ANALYST_FUZZY_MATCHER_USER_ID,
    ANALYST_REVIEWER_USER_ID,
    ANALYST_USER_ID,
    HOLDER_PLACEHOLDER_USER_ID,
    REGULATOR_USER_ID,
    TEST_USERS,
    make_regulatory_officer_headers,
    make_rights_holder_user_headers,
    make_rights_ops_analyst_headers,
    make_royalty_admin_headers,
)
from .types import *  # noqa: F401,F403
