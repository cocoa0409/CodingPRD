"""Test infrastructure for the telephone number administration and pooling API.

Everything a test needs is re-exported here, so test modules import from
`test_helpers` alone:

    from test_helpers import (
        api_client,
        ADMIN_HEADERS,
        validate_success,
        validate_error,
        ApiErrorId,
        setup_pending_allocation_request,
    )
"""

# Framework generics -- provided by the installed runner, never generated here.
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
from .constants import (
    CLOCK_PLUS_30,
    CLOCK_PLUS_180,
    CLOCK_PLUS_181,
    COMMENT_WEIGHTS,
    DEFAULT_CLOCK,
    DONATION_RATES,
    INTERVALS,
    TEST_DEFAULTS,
    THRESHOLDS,
    UNKNOWN_ID,
)
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (
    ADMIN_HEADERS,
    ADMIN_USER_ID,
    APPROVER_HEADERS,
    APPROVER_USER_ID,
    COMMENTER_HEADERS,
    COMMENTER_USER_ID,
    NO_AUTH_HEADERS,
    PORTING_HEADERS,
    PORTING_USER_ID,
    SECOND_ADMIN_HEADERS,
    SECOND_ADMIN_USER_ID,
    SECOND_APPROVER_HEADERS,
    SECOND_APPROVER_USER_ID,
    TEST_USERS,
    make_carrier_representative_headers,
    make_numbering_administrator_headers,
    make_porting_operations_headers,
    make_public_commenter_headers,
    make_regulatory_approver_headers,
)
from .types import *  # noqa: F401,F403
