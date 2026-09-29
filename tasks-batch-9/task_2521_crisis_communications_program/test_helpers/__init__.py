"""Test infrastructure for the Crisis Communications Program API.

Barrel module: tests import everything they need from ``test_helpers``.
"""

# Framework generics
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

# Domain infrastructure
from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, NOT_FOUND_BY_RESOURCE, ApiErrorId
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (
    PROGRAM_ADMIN_USER_ID,
    TEAM_ROLE_TO_USER_ROLE,
    TEST_USERS,
    make_comms_lead_headers,
    make_exec_sponsor_headers,
    make_headers,
    make_incident_lead_headers,
    make_legal_counsel_headers,
    make_program_admin_headers,
    make_social_listener_headers,
    make_spokesperson_headers,
)
from .types import *  # noqa: F401,F403
