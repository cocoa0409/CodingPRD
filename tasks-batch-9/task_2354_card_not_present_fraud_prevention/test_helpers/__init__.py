"""Test infrastructure for the Aegis CNP fraud-prevention API.

Importing this package registers the error-to-HTTP-status map with the
framework, so ``validate_error`` cross-checks status codes automatically.
"""

from prd_bench_local_runner.testing import (
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

from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (
    CHECKOUT_SERVICE_ID,
    PLATFORM_ADMIN_ID,
    POLICY_ENGINEER_APPROVER_ID,
    POLICY_ENGINEER_AUTHOR_ID,
    TEST_USERS,
    make_checkout_service_headers,
    make_headers,
    make_headers_with_empty_role,
    make_headers_without_role,
    make_headers_without_user_id,
    make_platform_admin_headers,
    make_policy_engineer_approver_headers,
    make_policy_engineer_author_headers,
    make_policy_engineer_headers,
    make_review_lead_headers,
    make_risk_analyst_headers,
)
from .types import *  # noqa: F401,F403
