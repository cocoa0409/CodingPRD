"""Test helpers for the Sailing Regatta & Handicap Rating Administration API.

Importing this package registers the PRD section 5 error-code to HTTP-status map
with the framework validators, so `validate_error` cross-checks both halves of
every rejection.

Re-exports the generic framework surface alongside the PRD-specific helpers so a
test module needs a single import line.
"""

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

from . import assertions, constants, factories, fixtures, types  # noqa: F401
from .api_client import ApiClient, api_client  # noqa: F401
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    CLUB_ADMIN_USER_ID,
    TEST_USERS,
    make_club_admin_headers,
    make_competitor_headers,
    make_headers_without_role,
    make_headers_without_user_id,
    make_jury_chair_headers,
    make_measurer_headers,
    make_race_officer_headers,
    make_regatta_chair_headers,
)
from .types import *  # noqa: F401,F403
