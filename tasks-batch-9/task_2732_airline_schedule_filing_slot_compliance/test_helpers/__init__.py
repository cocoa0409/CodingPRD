"""Test helper package — the single import surface for the test suite.

Everything a test needs is re-exported here: the framework's generic response
validators, the endpoint client, the error catalogue, the domain assertions,
the payload factories, the shared literals and the composite setup helpers.
Tests import from `test_helpers` and never from a submodule directly.
"""

# ── Framework generics ───────────────────────────────────────────────────
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

# ── Local modules ────────────────────────────────────────────────────────
from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, NOT_FOUND_ERROR_IDS, ApiErrorId
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (
    COMPLIANCE_OFFICER_USER_ID,
    FILING_AGENT_USER_ID,
    SECOND_FILING_AGENT_USER_ID,
    SECOND_SLOT_COORDINATOR_USER_ID,
    SLOT_COORDINATOR_USER_ID,
    SYSTEM_ADMIN_USER_ID,
    TEST_USERS,
    make_compliance_officer_headers,
    make_filing_agent_headers,
    make_headers,
    make_network_planner_headers,
    make_partner_carrier_headers,
    make_slot_coordinator_headers,
    make_system_admin_headers,
)
from .types import *  # noqa: F401,F403
