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
from .assertions import (
    assert_customer,
    assert_depot_bay,
    assert_engineering_escalation,
    assert_failure_code,
    assert_loaner_reservation,
    assert_loaner_unit,
    assert_notification_event,
    assert_part,
    assert_product_model,
    assert_quote,
    assert_repair_line,
    assert_rma,
    assert_unit,
)
from .factories import *
from .constants import *
from .test_users import (
    TEST_USERS,
    make_customer_headers,
    make_depot_manager_headers,
    make_depot_technician_headers,
    make_engineering_lead_headers,
    make_intake_agent_headers,
    make_warranty_admin_headers,
)
from .fixtures import *
