"""Barrel export: framework generics + PRD-specific test infrastructure."""
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
from .assertions import (
    assert_boat_model,
    assert_boat_show_event,
    assert_build_slot,
    assert_dealer,
    assert_dealer_order,
    assert_floor_plan_advance,
    assert_hull,
    assert_option_package,
    assert_order_option_line,
    assert_production_run,
    assert_recall_campaign,
    assert_recall_notice,
    assert_warranty_claim,
    assert_warranty_registration,
)
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (
    TEST_USERS,
    make_compliance_officer_headers,
    make_dealer_principal_headers,
    make_production_planner_headers,
)
from .types import *  # noqa: F401,F403
