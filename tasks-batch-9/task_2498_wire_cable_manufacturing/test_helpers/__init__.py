"""Test helpers for the wire and cable manufacturing API.

Framework primitives are re-exported from ``prd_bench_local_runner.testing`` so
test modules import everything from one place.
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
    ADMIN,
    ADMIN_RELEASER_USER_ID,
    ADMIN_TESTER_USER_ID,
    BILLING,
    BUYER,
    CERT_OFFICER,
    CLERK,
    ENGINEER,
    NO_AUTH_HEADERS,
    QE_DISPOSITIONER,
    QE_DISPOSITIONER_USER_ID,
    QE_RELEASER,
    QE_RELEASER_USER_ID,
    QE_TESTER,
    QE_TESTER_USER_ID,
    TEST_USERS,
    make_customer_headers,
    make_headers,
    make_plant_admin_headers,
    make_quality_engineer_headers,
)
from .types import *  # noqa: F401,F403
