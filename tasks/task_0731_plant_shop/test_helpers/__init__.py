"""Barrel export: framework generics + PRD-specific code."""
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
from .types import *  # noqa: F401,F403
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import (
    assert_customer, assert_plant, assert_stock_unit, assert_care_log_entry,
    assert_delivery_driver, assert_order, assert_order_line, assert_delivery_assignment,
    assert_subscription, assert_workshop, assert_workshop_registration,
    assert_warranty_claim, assert_special_order, assert_loyalty_ledger_entry,
)
from .factories import (
    create_customer_payload, create_plant_payload, create_stock_unit_payload,
    create_delivery_driver_payload, create_order_payload, create_dispatch_payload,
    create_subscription_payload, create_workshop_payload,
    create_workshop_registration_payload, create_warranty_claim_payload,
    create_special_order_payload, create_care_log_payload,
)
from .constants import (
    DELIVERY_BASE_FEE_CENTS, ZONE_SURCHARGE_CENTS, HEAVY_SURCHARGE_CENTS,
    GIFT_SURCHARGE_CENTS, DELIVERY_MIN_FEE_CENTS, DELIVERY_MAX_FEE_CENTS,
    HEAVY_WAIVER_THRESHOLD_CENTS, TAX_RATE, TIER_MULT, TIER_THRESHOLDS,
    WARRANTY_DEDUCTION_PCT, WARRANTY_MANDATORY_CARE_INTERVAL_COUNT,
    WARRANTY_MAX_DEDUCTIONS, WARRANTY_REFUND_CAP_CENTS, WARRANTY_REFUND_CAP_WINDOW_DAYS,
    SUBSCRIPTION_MONTHLY_FEE_CENTS, SUBSCRIPTION_PLAN_PRICE_CEILING,
    SUBSCRIPTION_INTERVAL_DAYS, WORKSHOP_ROOM_BUFFER_MINUTES,
    WORKSHOP_REGISTRATION_CUTOFF_HOURS, DEFAULT_DRIVER_CAPACITY_MINUTES,
    SPECIAL_ORDER_MAX_REVISIONS, STARTUP_CLOCK_ISO,
)
from .test_users import TEST_USERS, make_customer_headers, make_delivery_driver_headers
from .fixtures import (
    set_clock, register_customer, create_driver, create_plant,
    intake_stock_unit, create_order, pay_order, dispatch_order, deliver,
    get_orderline_id_for_order, append_care_log,
    setup_customer_driver_plant, create_and_deliver_order,
    setup_delivered_orderline, setup_special_order_at_revision_count,
)
