"""Barrel export: framework generics + Integrated Facilities Management specifics."""

# Framework generics (re-exported for convenience)
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

# PRD-specific
from .api_client import ApiClient, api_client  # noqa: F401
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    FC_APPROVER_ID,
    FC_PROPOSER_ID,
    FC_THIRD_ID,
    NO_AUTH_HEADERS,
    TEST_USERS,
    make_facility_manager_headers,
    make_finance_controller_headers,
    make_tenant_rep_headers,
    make_vendor_tech_headers,
)
from .types import *  # noqa: F401,F403
