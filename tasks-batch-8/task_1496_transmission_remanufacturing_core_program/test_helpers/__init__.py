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
from .test_users import TEST_USERS  # noqa: F401
from .test_users import (  # noqa: F401
    make_calibrator_headers,
    make_core_inspector_headers,
    make_core_intake_clerk_headers,
    make_dyno_operator_headers,
    make_installer_headers,
    make_inventory_planner_headers,
    make_program_admin_headers,
    make_reman_planner_headers,
    make_reman_technician_headers,
    make_warranty_adjuster_headers,
)
from .fixtures import *  # noqa: F401,F403
