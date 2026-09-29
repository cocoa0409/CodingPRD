"""Test helpers for the Foodservice National Account Contract & Deviated
Pricing API.

Re-exports the framework's generic validators and assertions alongside this
domain's client, error catalogue, payload factories, entity assertions,
constants, role headers and composite setup builders, so a test module needs a
single import line.
"""

from prd_bench_local_runner.testing import (  # noqa: F401
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
    NON_EXISTENT_UUID,
)

from .types import *  # noqa: F401,F403
from .api_client import api_client, ApiClient  # noqa: F401
from .api_errors import ApiErrorId, HTTP_STATUS_CODES  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    ACCOUNTANT_ALT_USER_ID,
    ACCOUNTANT_USER_ID,
    ADMIN_USER_ID,
    ANALYST_ALT_USER_ID,
    ANALYST_USER_ID,
    AUDITOR_ALT_USER_ID,
    AUDITOR_USER_ID,
    NAM_ALT_USER_ID,
    NAM_USER_ID,
    NO_AUTH_HEADERS,
    TEST_USERS,
    make_contract_auditor_headers,
    make_headers_for_role,
    make_manufacturer_rep_headers,
    make_national_account_manager_headers,
    make_operator_buyer_headers,
    make_pricing_analyst_headers,
    make_rebate_accountant_headers,
    make_system_admin_headers,
)
from .fixtures import *  # noqa: F401,F403
