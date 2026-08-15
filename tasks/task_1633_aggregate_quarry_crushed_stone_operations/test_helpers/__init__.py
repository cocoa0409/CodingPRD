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
from .types import *
from .api_client import ApiClient, api_client
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import *
from .factories import *
from .constants import *
from .test_users import (
    TEST_USERS,
    make_blast_foreman_headers,
    make_finance_clerk_headers,
    make_plant_operator_headers,
    make_qc_technician_headers,
    make_quarry_admin_headers,
    make_safety_officer_headers,
    make_sales_agent_headers,
    make_scale_house_operator_headers,
    make_site_manager_headers,
)
from .fixtures import *
