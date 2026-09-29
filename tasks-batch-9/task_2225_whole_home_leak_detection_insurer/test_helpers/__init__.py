"""Test infrastructure for the whole-home leak-detection and insurer-credit API.

Importing this package registers the PRD's error-to-HTTP-status map with the
framework, so `validate_error()` cross-checks the status code of every rejection
against the catalogue the PRD publishes.
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

from . import assertions, constants, factories, fixtures, types
from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import (
    assert_anomaly_event,
    assert_baseline_profile,
    assert_common_record_properties,
    assert_credit_attestation,
    assert_credit_ledger_identity,
    assert_decimal_places,
    assert_device,
    assert_device_transfer,
    assert_emergency_contact,
    assert_escalation_ticket,
    assert_homeowner,
    assert_insurance_policy,
    assert_integer_cents,
    assert_irrigation_window,
    assert_no_version_change,
    assert_property,
    assert_reimbursement_claim,
    assert_severity_precision,
    assert_telemetry_reading,
    assert_threshold_precision,
    assert_uptime_precision,
    assert_valve_ledger_monotonic,
)
from .constants import DEFAULT_CLOCK_UTC, FIXTURE_CLOCK_UTC, PAGINATION, TEST_DEFAULTS
from .test_users import (
    ADJUSTER_USER_ID,
    GATEWAY_USER_ID,
    INSTALLER_TECH_USER_ID,
    INSURER_ANALYST_USER_ID,
    PROGRAM_ADMIN_USER_ID,
    SECOND_ADJUSTER_USER_ID,
    SECOND_INSTALLER_TECH_USER_ID,
    SECOND_INSURER_ANALYST_USER_ID,
    TEST_USERS,
    make_claims_adjuster_headers,
    make_gateway_headers,
    make_headers,
    make_homeowner_headers,
    make_installer_tech_headers,
    make_insurer_analyst_headers,
    make_program_admin_headers,
)
from .types import UserRole
