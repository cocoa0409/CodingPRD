"""Barrel export: framework generics + PRD-specific helpers."""
# Framework generics (re-exported for convenience)
from prd_bench_local_runner.testing import (
    validate_success, validate_error, validate_paginated,
    validate_error_is_one_of, get_success_data,
    is_valid_uuid, is_iso8601_timestamp,
    assert_cost_precision, assert_version_incremented, assert_timestamp_format,
    assert_race_outcome, assert_exactly_one_succeeds, assert_at_least_one_succeeds,
    run_race, build_user_headers, NON_EXISTENT_UUID,
)

# PRD-specific
from .types import *
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import *
from .factories import *
from .constants import *
from .test_users import (
    TEST_USERS,
    make_program_director_headers, make_traffic_director_headers,
    make_sales_rep_headers, make_sales_manager_headers,
    make_billing_admin_headers, make_headers,
)
from .fixtures import *

# Shared per-role header shortcuts (canonical opaque identities).
PD = TEST_USERS["program_director_headers"]
TD = TEST_USERS["traffic_director_headers"]
REP = TEST_USERS["sales_rep_headers"]
MGR = TEST_USERS["sales_manager_headers"]
BA = TEST_USERS["billing_admin_headers"]
