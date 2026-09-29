"""Test helper package for the FHLB Advances Collateral Pledging API.

Re-exports the framework generics alongside this domain's types, client,
factories, constants, assertions and composite state builders, so a test module
needs a single import line.
"""

# Framework generics.
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

# Domain vocabulary and infrastructure.
from .types import *  # noqa: F401,F403
from .api_client import api_client, ApiClient  # noqa: F401
from .api_errors import ApiErrorId, HTTP_STATUS_CODES  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    AUDITOR_USER_ID,
    COMMUNITY_MANAGER_USER_ID,
    CREDIT_OFFICER_ONE_USER_ID,
    CREDIT_OFFICER_TWO_USER_ID,
    CUSTODIAN_USER_ID,
    SHARED_HUMAN_USER_ID,
    SYSTEM_ADMIN_USER_ID,
    TEST_USERS,
    UNSCOPED_TREASURY_USER_ID,
    auditor_headers,
    community_manager_headers,
    credit_officer_headers,
    custodian_headers,
    make_headers,
    make_treasury_officer_headers,
    system_admin_headers,
)
from .fixtures import *  # noqa: F401,F403
