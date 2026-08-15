"""Barrel export: framework generics + PRD-specific helpers."""
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
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import *
from .constants import *
from .factories import *
from .fixtures import *
from .test_users import ANONYMOUS_HEADERS, TEST_USERS
from .test_users import (
    make_board_secretary_headers,
    make_committee_member_headers,
    make_community_member_headers,
    make_curriculum_director_headers,
    make_district_admin_headers,
    make_instructional_specialist_headers,
    make_procurement_officer_headers,
    make_teacher_headers,
    make_warehouse_manager_headers,
)
from .types import *
