"""Test infrastructure for the Joint Development Agreement API.

Importing this package re-exports everything a test file needs: the framework
validators, the endpoint client, the error catalogue, domain assertions,
payload factories, constants, caller identities and composite setup helpers.
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

from .types import *  # noqa: F401,F403
from .api_client import ApiClient, api_client
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .test_users import (
    ALL_ROLES,
    DEFAULT_USER_IDS,
    NO_AUTH_HEADERS,
    ROLE_BOARD_SECRETARY,
    ROLE_DEVELOPER,
    ROLE_GRANTS_COMPLIANCE_OFFICER,
    ROLE_REAL_ESTATE_OFFICER,
    ROLE_SYSTEM_ADMIN,
    ROLE_TRANSIT_OPERATIONS_MANAGER,
    ROLE_VALUATION_OFFICER,
    SECOND_BOARD_SECRETARY_ID,
    SECOND_REAL_ESTATE_OFFICER_ID,
    TEST_USERS,
    make_board_secretary_headers,
    make_developer_headers,
    make_grants_compliance_officer_headers,
    make_real_estate_officer_headers,
    make_role_headers,
    make_system_admin_headers,
    make_transit_operations_manager_headers,
    make_valuation_officer_headers,
)
from .fixtures import *  # noqa: F401,F403
