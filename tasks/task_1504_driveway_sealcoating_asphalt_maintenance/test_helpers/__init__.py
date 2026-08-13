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
from .assertions import (
    assert_assessment,
    assert_crew,
    assert_customer,
    assert_displacement_plan,
    assert_instant_equal,
    assert_invoice,
    assert_lot_ledger_conserved,
    assert_material,
    assert_material_lot,
    assert_property,
    assert_quote,
    assert_route_sheet,
    assert_sheet_capacity_conserved,
    assert_warranty_claim,
    assert_warranty_record,
    assert_weather_snapshot,
    assert_work_order,
)
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (
    TEST_USERS,
    make_customer_headers,
    make_office_admin_headers,
)
from .types import *  # noqa: F401,F403
