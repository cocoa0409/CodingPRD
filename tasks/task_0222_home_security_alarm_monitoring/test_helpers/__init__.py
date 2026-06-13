"""Barrel export: framework generics + PRD-specific test infrastructure.

Tests import everything from `test_helpers` so they have a single source.
"""
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
    assert_monitoring_plan, assert_account, assert_system, assert_sensor,
    assert_alarm_event, assert_dispatch, assert_permit, assert_fine,
    assert_account_invariants,
)
from .factories import (
    create_monitoring_plan_payload, create_account_payload, create_system_payload,
    create_sensor_payload, create_alarm_event_payload, create_permit_payload,
    change_plan_payload, finalize_cancellation_payload, arm_payload, resolve_payload,
    DEFAULTS,
)
from .constants import (
    THRESHOLDS, PLAN_FEES,
    CYCLE_DAYS, POLICE_DISPATCH_FEE_CENTS, FIRE_DISPATCH_FEE_CENTS,
    MEDICAL_DISPATCH_FEE_CENTS, FREE_ALLOWANCE, WARN_BAND, WARN_FINE_CENTS,
    ESCALATED_FINE_CENTS, NO_PERMIT_SURCHARGE_CENTS, BASE_PERMIT_FEE_CENTS,
    COMMERCIAL_UPLIFT_CENTS, LATE_PCT_PER_PERIOD, LATE_PERIOD_DAYS, LATE_CAP_CENTS,
    CHECKIN_MAX_MINUTES, SIGNAL_MIN_DBM, BATTERY_MIN_PCT,
    ETF_PER_REMAINING_MONTH_CENTS, TEST_MODE_WINDOW_MINUTES, SIGNAL_DEBOUNCE_SECONDS,
)
from .test_users import (
    TEST_USERS, make_subscriber_headers, make_operator_headers, make_admin_headers,
)
from .fixtures import *  # noqa: F401,F403
