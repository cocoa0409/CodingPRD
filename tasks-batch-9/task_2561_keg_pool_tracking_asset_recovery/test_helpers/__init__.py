"""Barrel export: framework generics plus the keg pool domain helpers."""

# Framework generics, re-exported so tests have a single import source.
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

from .api_client import ApiClient, api_client  # noqa: F401
from .api_errors import (  # noqa: F401
    HTTP_STATUS_CODES,
    NOT_FOUND_CODES,
    ApiErrorId,
)
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    ANALYST_USER_ID,
    POOL_OPERATOR_USER_ID,
    SECOND_ANALYST_USER_ID,
    SECOND_POOL_OPERATOR_USER_ID,
    SECOND_TECHNICIAN_USER_ID,
    TECHNICIAN_USER_ID,
    TEST_USERS,
    THIRD_ANALYST_USER_ID,
    all_role_headers,
    make_analyst_headers,
    make_brewer_headers,
    make_distributor_headers,
    make_pool_operator_headers,
    make_technician_headers,
)
from .types import *  # noqa: F401,F403
