"""Test infrastructure for the Membership Campground RV Club Program API.

Re-exports the shared framework utilities alongside the domain-specific client,
error catalog, entity assertions, payload factories, constants and composite
fixtures, so every test file needs a single import.
"""

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

from .types import *  # noqa: F401,F403
from .api_client import ApiClient, api_client  # noqa: F401
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    CLUB_ADMIN_PRIMARY_ID,
    CLUB_ADMIN_SECONDARY_ID,
    COMPLIANCE_OFFICER_ID,
    COMPLIANCE_OFFICER_SECONDARY_ID,
    TEST_USERS,
    TRANSIENT_GUEST_ID,
    TRANSIENT_GUEST_SECONDARY_ID,
    headers_with_unknown_role,
    headers_without_role,
    headers_without_user_id,
    make_club_admin_headers,
    make_compliance_officer_headers,
    make_member_headers,
    make_park_manager_headers,
    make_transient_guest_headers,
)
from .fixtures import *  # noqa: F401,F403
