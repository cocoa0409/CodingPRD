"""Barrel export: framework generics + PRD-specific code."""
# Framework generics (re-exported for convenience)
from prd_bench_local_runner.testing import (
    validate_success,
    validate_error,
    validate_paginated,
    validate_error_is_one_of,
    get_success_data,
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
    assert_version_incremented,
    assert_timestamp_format,
    assert_race_outcome,
    assert_exactly_one_succeeds,
    assert_at_least_one_succeeds,
    run_race,
    build_user_headers,
    NON_EXISTENT_UUID,
)

# PRD-specific
from .types import *  # noqa: F401,F403
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import (
    assert_store,
    assert_customer,
    assert_picker,
    assert_product,
    assert_slot,
    assert_order,
    assert_order_line,
    assert_substitution,
    assert_payment,
    assert_age_check,
    assert_refund,
    assert_refund_has_no_version_fields,
    assert_split_tender_invariants,
    assert_net_captured_identity,
)
from .factories import (
    create_store_payload,
    create_customer_payload,
    create_picker_payload,
    create_product_payload,
    create_slot_payload,
    create_order_payload,
    order_line_entry,
    create_order_line_payload,
    create_substitution_payload,
    pick_payload,
    claim_payload,
    create_age_check_payload,
)
from .constants import (
    MIN_AGE_YEARS,
    DEFAULT_COLD_CHAIN_HOLD_MINUTES,
    DEFAULT_WINDOW_COOLDOWN_MINUTES,
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    THRESHOLDS,
    TEST_DEFAULTS,
)
from .test_users import (
    TEST_USERS,
    make_platform_admin_headers,
    make_store_ops_headers,
    make_customer_headers,
    make_picker_headers,
)
from .fixtures import (
    set_clock,
    create_store,
    create_customer,
    create_picker,
    create_product,
    create_slot,
    discontinue_product,
    close_slot,
    close_store,
    suspend_customer,
    place_order,
    get_line_ids,
    get_slot_version,
    provision_store_customer_picker,
    claim_order,
    pick_line,
    stage_order,
    capture_order,
    handoff_order,
    setup_single_unit_order_picking,
    setup_single_unit_order_staged,
    setup_single_unit_order_captured,
    ADMIN,
    OPS,
)
