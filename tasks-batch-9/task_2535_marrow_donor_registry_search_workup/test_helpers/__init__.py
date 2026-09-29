"""Test infrastructure for the Marrow Donor Registry Search & Workup API.

A test file imports everything it needs from this one package:

    from test_helpers import (
        api_client, ApiErrorId, TEST_USERS,
        validate_success, validate_error, validate_paginated,
        fixtures, factories, assertions, constants,
    )
"""
# ---- framework generics ----------------------------------------------------
from prd_bench_local_runner.testing import (  # noqa: F401
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

# ---- this task's own infrastructure ---------------------------------------
from . import assertions  # noqa: F401
from . import constants  # noqa: F401
from . import factories  # noqa: F401
from . import fixtures  # noqa: F401
from . import types  # noqa: F401
from .api_client import ApiClient, api_client  # noqa: F401
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .test_users import (  # noqa: F401
    COORDINATOR_USER_ID,
    OPERATIONS_USER_ID,
    OTHER_COORDINATOR_USER_ID,
    PHYSICIAN_USER_ID,
    ROLE_NAMES,
    SECOND_PHYSICIAN_USER_ID,
    TEST_USERS,
    make_center_ops_headers,
    make_coordinator_headers,
    make_liaison_headers,
    make_operations_headers,
    make_physician_headers,
)
