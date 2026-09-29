"""Test helper package for the Age-Restricted Delivery Verification API.

Re-exports the framework primitives alongside the domain-specific client,
error catalogue, constants, factories, assertions and composite builders so a
test module imports everything it needs from one place.
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

from . import factories, fixtures
from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import (
    assert_attempt_state,
    assert_case_state,
    assert_cents,
    assert_common_fields,
    assert_confidence_equal,
    assert_courier_gates,
    assert_created_at_ascending,
    assert_fresh_attempt_defaults,
    assert_instant_equal,
    assert_line_snapshot,
    assert_money_conserved,
    assert_new_case_defaults,
    assert_new_order_defaults,
    assert_order_states,
    assert_page_meta,
    assert_partner_gate,
    assert_plan_state,
    assert_restriction_types,
    assert_score_equal,
    assert_units_equal,
    assert_versionless_row,
    ids_of,
)
from .constants import *  # noqa: F401,F403
from .test_users import (
    ADMIN_HEADERS,
    ADMIN_USER_ID,
    AUDITOR_HEADERS,
    AUDITOR_USER_ID,
    OFFICER_A_HEADERS,
    OFFICER_A_USER_ID,
    OFFICER_B_HEADERS,
    OFFICER_B_USER_ID,
    OFFICER_HEADERS,
    TEST_USERS,
    headers_with_empty_role,
    headers_with_empty_user_id,
    headers_without_auth,
    make_admin_headers,
    make_auditor_headers,
    make_courier_headers,
    make_customer_headers,
    make_officer_headers,
    make_partner_manager_headers,
)
