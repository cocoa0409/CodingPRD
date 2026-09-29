"""Test helpers for the Lifeline prepaid wireless eligibility and enrollment API.

Re-exports the generic framework utilities alongside the domain specific client,
factories, assertions and composite fixtures so tests import from one place.
"""

# ---------------------------------------------------------------- framework API
from prd_bench_local_runner.testing import (
    GenericApiClient,
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

# ------------------------------------------------------------------ domain API
from . import factories, fixtures
from .api_client import ApiClient
from .api_errors import ERROR_HTTP_STATUS, ApiErrorId
from .assertions import (
    address_hash_for,
    assert_audit_sample,
    assert_common_fields,
    assert_date_component,
    assert_de_enrollment_cascade,
    assert_device,
    assert_device_counters,
    assert_device_partition_conserved,
    assert_eligibility_check,
    assert_enrollment,
    assert_household_address,
    assert_instant,
    assert_instant_null,
    assert_ledger_tuple,
    assert_meta_envelope,
    assert_provider,
    assert_provider_ledger_consistent,
    assert_reimbursement_claim,
    assert_service_transfer,
    assert_subscriber,
    assert_subscriber_case,
    day_end_after,
    day_start_after,
    expected_income_threshold,
    expected_recoupment,
    expected_risk_score,
    expected_support_line,
    instants_equal,
    iso_z,
    monthly_support_rate,
    parse_instant,
    round_half_up,
    shift_instant,
)
from .constants import *  # noqa: F401,F403  (domain thresholds and enum vocabularies)
from .test_users import (
    AUDITOR_ADJUDICATOR,
    AUDITOR_ADJUDICATOR_ID,
    AUDITOR_DRAWER,
    AUDITOR_DRAWER_ID,
    EMPTY_AUTH_HEADERS,
    NATIONAL_VERIFIER,
    NATIONAL_VERIFIER_ID,
    NO_AUTH_HEADERS,
    PROGRAM_ADMIN,
    PROGRAM_ADMIN_ALT,
    PROGRAM_ADMIN_ID,
    PROGRAM_ADMIN_ID_ALT,
    REVIEWER_1,
    REVIEWER_2,
    REVIEWER_3,
    REVIEWER_4,
    UNKNOWN_ROLE_HEADERS,
    make_auditor_headers,
    make_headers_for_role,
    make_program_admin_headers,
    make_provider_agent_headers,
    make_subscriber_headers,
    make_verifier_headers,
)
from .types import ALL_ROLES, Role
