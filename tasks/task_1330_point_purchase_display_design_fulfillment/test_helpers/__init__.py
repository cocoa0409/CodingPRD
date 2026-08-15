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
from .types import *  # noqa: F401,F403
from .api_client import ApiClient, api_client
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    CLAIMS_ADJUSTER,
    COMPLIANCE_OFFICER,
    DESIGNER,
    FIELD_SERVICE_MANAGER,
    LOGISTICS_COORDINATOR,
    PLATFORM_ADMIN,
    PRODUCTION_PLANNER,
    PROGRAM_MANAGER,
    TEST_USERS,
    WAREHOUSE_OPERATOR,
    make_claims_adjuster_headers,
    make_compliance_officer_headers,
    make_designer_headers,
    make_field_service_manager_headers,
    make_logistics_coordinator_headers,
    make_platform_admin_headers,
    make_production_planner_headers,
    make_program_manager_headers,
    make_warehouse_operator_headers,
)
from .fixtures import *  # noqa: F401,F403
