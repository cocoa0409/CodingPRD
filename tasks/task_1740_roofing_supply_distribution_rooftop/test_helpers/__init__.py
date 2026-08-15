"""Barrel export: framework generics + PRD-specific code."""
# Framework generics (re-exported for convenience)
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

# PRD-specific
from .api_client import ApiClient, api_client
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import *
from .constants import *
from .factories import *
from .fixtures import *
from .test_users import (
    TEST_USERS,
    make_branch_manager_headers,
    make_claims_adjuster_headers,
    make_contractor_headers,
    make_credit_analyst_headers,
    make_dispatcher_headers,
    make_platform_admin_headers,
    make_sales_rep_headers,
    make_warehouse_clerk_headers,
)
from .types import *
