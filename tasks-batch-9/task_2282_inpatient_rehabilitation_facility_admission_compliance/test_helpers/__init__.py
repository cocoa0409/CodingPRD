"""Barrel export: framework generics + IRF-specific test infrastructure."""

# Framework generics (re-exported for convenience)
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

# IRF-specific
from .api_client import ApiClient, api_client  # noqa: F401
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    HEADERS_WITHOUT_ROLE,
    HEADERS_WITHOUT_USER_ID,
    OFFICER_ONE_USER_ID,
    OFFICER_TWO_USER_ID,
    TEST_USERS,
    make_coder_headers,
    make_nurse_headers,
    make_officer_headers,
    make_physician_headers,
    make_therapy_lead_headers,
)
from .types import *  # noqa: F401,F403
