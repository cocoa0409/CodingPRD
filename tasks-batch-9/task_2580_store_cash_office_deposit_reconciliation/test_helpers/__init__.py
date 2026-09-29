"""Barrel export: framework generics plus this API's specific helpers."""

# Framework generics, re-exported so tests have one import source.
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
from .api_errors import HTTP_STATUS_CODES, NOT_FOUND_ERROR_IDS, ApiErrorId
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (
    ALL_ROLE_NAMES,
    CARRIER_1,
    CARRIER_2,
    CLERK_1,
    CLERK_2,
    CLERK_3,
    CLERK_4,
    LP_1,
    MANAGER_1,
    MANAGER_2,
    TEST_USERS,
    TREASURY_1,
    headers_for_role,
    make_carrier_headers,
    make_cashier_headers,
    make_clerk_headers,
    make_investigator_headers,
    make_manager_headers,
    make_treasury_headers,
)
from .types import *  # noqa: F401,F403
