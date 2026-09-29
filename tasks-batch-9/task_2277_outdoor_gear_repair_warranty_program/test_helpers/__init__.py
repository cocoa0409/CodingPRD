"""Test helpers for the Outdoor Gear Repair & Warranty Program API.

Single import surface for the suite: framework validators are re-exported
alongside the domain client, error catalogue, factories, assertions and
fixtures so every test file imports from `test_helpers` only.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    GenericApiClient,
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

from . import factories
from .api_client import GearServiceApiClient
from .api_errors import *  # noqa: F401,F403  (error id constants)
from .api_errors import HTTP_STATUS_CODES, NOT_FOUND_ERRORS, UNIQUENESS_ERRORS
from .assertions import (
    PCT_TOLERANCE,
    assert_center_posture,
    assert_claim_decision,
    assert_common_fields,
    assert_estimate_breakdown,
    assert_immutable_common_fields,
    assert_money_cents,
    assert_multiplier,
    assert_no_row_created,
    assert_part_lot_counts,
    assert_pct,
    assert_row_ids,
    assert_sorted_by_created_at,
    assert_timestamp_millis,
)
from .constants import *  # noqa: F401,F403  (domain constants and enums)
from .fixtures import (  # noqa: F401  (pytest picks these up via conftest)
    Scenario,
    World,
    admin_headers,
    agent_headers,
    api,
    assessed_claim,
    bench_completed_order,
    catalogue,
    claim_after_two_info_rounds,
    decided_claim,
    irreparable_order,
    open_order,
    order_with_sent_estimate,
    paid_repair_order,
    parts_headers,
    qc_passed_order,
    released_order,
    scenario,
    submitted_claim,
)
from .test_users import (
    ALL_ROLES,
    PARTS_COORDINATOR_HEADERS,
    PARTS_COORDINATOR_ID,
    PROGRAM_ADMIN_HEADERS,
    PROGRAM_ADMIN_ID,
    ROLE_CUSTOMER,
    ROLE_PARTS_COORDINATOR,
    ROLE_PROGRAM_ADMIN,
    ROLE_REPAIR_TECHNICIAN,
    ROLE_SERVICE_AGENT,
    SERVICE_AGENT_HEADERS,
    SERVICE_AGENT_ID,
    TEST_USERS,
    headers_with_blank_role,
    headers_without_role,
    headers_without_user_id,
    make_customer_headers,
    make_headers,
    make_technician_headers,
)
