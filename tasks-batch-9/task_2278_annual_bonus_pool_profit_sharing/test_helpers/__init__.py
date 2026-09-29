"""Barrel export: framework generics plus this API's own test infrastructure."""

# Framework generics, re-exported for convenience.
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
    ALL_ROLE_NAMES,
    CC_ADJUDICATOR,
    CC_CERTIFIER,
    CC_LOCKER,
    CC_REVERSER,
    CC_SCORECARD,
    FINANCE_USER,
    HRBP_USER,
    HRBP_USER_ALT,
    PLAN_ADMIN_USER,
    PLAN_ADMIN_USER_ALT,
    TEST_USERS,
    make_committee_headers,
    make_employee_headers,
    make_finance_headers,
    make_hr_headers,
    make_manager_headers,
    make_plan_admin_headers,
)
from .types import *  # noqa: F401,F403
