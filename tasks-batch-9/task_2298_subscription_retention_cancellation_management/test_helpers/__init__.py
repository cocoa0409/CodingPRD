"""Test helper package for the subscription retention and cancellation API.

Import everything a test needs from here:

    from test_helpers import (
        api_client, ApiErrorId, TEST_USERS, make_subscriber_headers,
        validate_success, validate_error, validate_paginated,
        setup_active_subscription, assert_subscription,
    )
"""

from prd_bench_local_runner.testing import (
    GenericApiClient,
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
    TEST_USERS,
    headers_for_role,
    make_billing_operator_headers,
    make_compliance_officer_headers,
    make_platform_admin_headers,
    make_retention_specialist_headers,
    make_subscriber_headers,
)
from .types import *  # noqa: F401,F403
