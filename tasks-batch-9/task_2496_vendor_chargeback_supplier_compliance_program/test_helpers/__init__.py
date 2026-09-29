"""Barrel export: framework generics plus the PRD-specific test infrastructure."""
# Framework generics, re-exported so tests have one import source.
from prd_bench_local_runner.testing import (  # noqa: F401
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

from .api_client import PREFIX, ApiClient, api_client  # noqa: F401
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    ACCOUNTANT_USER_ID,
    BUYER_USER_ID,
    INSPECTOR_USER_ID,
    OFFICER_USER_ID,
    SECOND_INSPECTOR_USER_ID,
    SECOND_OFFICER_USER_ID,
    TEST_USERS,
    make_accountant_headers,
    make_buyer_headers,
    make_inspector_headers,
    make_officer_headers,
    make_vendor_headers,
)
from .types import *  # noqa: F401,F403
