"""Barrel export: framework generics plus the domain-specific test code."""

# Framework generics (re-exported so tests have one import source).
from prd_bench_local_runner.testing import (  # noqa: F401
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
from .api_errors import ApiErrorId, HTTP_STATUS_CODES  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .constants import (  # noqa: F401
    THRESHOLDS,
    TEST_DEFAULTS,
    DEFAULT_CLOCK_UTC,
    UNUSED_UUID,
)
from .test_users import (  # noqa: F401
    TEST_USERS,
    make_platform_admin_headers,
    make_sales_rep_headers,
    make_credit_manager_headers,
    make_branch_ops_headers,
    make_driver_headers,
    make_customer_headers,
)
from .fixtures import *  # noqa: F401,F403
