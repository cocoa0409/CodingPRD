"""Test infrastructure for the League Merch Licensing API.

Re-exports the shared framework helpers alongside the domain-specific client,
factories, assertions, constants, role headers and composite fixtures.
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
    TEST_USERS,
    make_club_representative_headers,
    make_finance_controller_headers,
    make_headers_with_empty_user_id,
    make_headers_with_role,
    make_headers_without_role,
    make_headers_without_user_id,
    make_league_licensing_manager_headers,
    make_licensee_headers,
    make_mark_compliance_officer_headers,
    make_player_agent_headers,
    make_royalty_auditor_headers,
)
from .types import *  # noqa: F401,F403
