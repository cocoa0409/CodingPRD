"""Test infrastructure for the rebuilt-salvage inspection and title-branding program.

Importing this package gives a test module everything it needs: the shared HTTP
client, response validators, identity headers, payload factories, entity
assertions, domain constants and the scenario builders that stand a program up
from an empty database.
"""

# --- framework re-exports --------------------------------------------------
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

# --- generated infrastructure ---------------------------------------------
from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (
    ADJUSTER_USER_ID,
    ADMIN_USER_ID,
    CLERK_USER_ID,
    FRAUD_INVESTIGATOR_USER_ID,
    HEARING_OFFICER_USER_ID,
    SECOND_ADMIN_USER_ID,
    SECOND_CLERK_USER_ID,
    SECOND_FRAUD_INVESTIGATOR_USER_ID,
    SECOND_HEARING_OFFICER_USER_ID,
    TEST_USERS,
    UNBOUND_INSPECTOR_USER_ID,
    UNBOUND_REBUILDER_USER_ID,
    headers_for_role,
    make_fraud_investigator_headers,
    make_hearing_officer_headers,
    make_insurer_adjuster_headers,
    make_inspector_headers,
    make_program_admin_headers,
    make_rebuilder_headers,
    make_state_title_clerk_headers,
)
from .types import *  # noqa: F401,F403
