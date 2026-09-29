"""Test helpers for the Public Funds Collateral API.

Re-exports the framework generics alongside this suite's domain-specific client,
factories, assertions, constants, identities and composite setup helpers, so a test
module needs a single import site.
"""

from prd_bench_local_runner.testing import (  # noqa: F401
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

from . import assertions, constants, factories, fixtures  # noqa: F401
from .api_client import ApiClient, api_client  # noqa: F401
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    ALL_ROLE_NAMES,
    BATCH_USER_ID,
    COMPLIANCE_USER_ID,
    OFFICER_USER_ID,
    OPERATOR_USER_ID,
    PRICING_FEED_USER_ID,
    REGULATOR_USER_ID,
    SECOND_COMPLIANCE_USER_ID,
    SECOND_OFFICER_USER_ID,
    TEST_USERS,
    make_bank_collateral_officer_headers,
    make_bank_compliance_officer_headers,
    make_custodian_headers,
    make_public_unit_treasurer_headers,
    make_state_regulator_headers,
    make_system_operator_headers,
)
from .types import *  # noqa: F401,F403
