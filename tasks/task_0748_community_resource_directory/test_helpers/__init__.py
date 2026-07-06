"""Barrel export: framework generics + PRD-specific code."""
# Framework generics — re-exported for convenience.
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

# PRD-specific.
from .types import *  # noqa: F401,F403
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import (
    assert_funder,
    assert_provider,
    assert_program,
    assert_availability_window,
    assert_client,
    assert_intake,
    assert_consent_grant,
    assert_referral,
    assert_transport_plan,
    assert_outcome_report,
    assert_funder_report,
    assert_funder_report_has_no_version_fields,
)
from .factories import (
    create_funder_payload,
    create_provider_payload,
    create_program_payload,
    create_client_payload,
    create_intake_payload,
    create_consent_grant_payload,
    create_referral_payload,
    create_transport_plan_payload,
    create_availability_window_payload,
    create_outcome_report_payload,
    create_funder_report_payload,
)
from .constants import (
    ELIGIBILITY_ACCEPT_THRESHOLD,
    INCOME_BAND_1, INCOME_BAND_2, INCOME_BAND_3,
    WEIGHT_INCOME, WEIGHT_AGE, WEIGHT_CATEGORY, WEIGHT_LANGUAGE, WEIGHT_ACCESSIBILITY,
    URGENCY_MULT_ROUTINE, URGENCY_MULT_PRIORITY, URGENCY_MULT_EMERGENCY,
    DEG_TO_KM, WINDING_FACTOR, SPEED_KPH,
    RESTRICTED_THRESHOLD_RATIO, CLOSED_THRESHOLD_RATIO,
    TRANSPORT_BUFFER_SECONDS,
    RAW_BASELINE_UNMET, RAW_BASELINE_MET, RAW_HOURS_COEFFICIENT,
    CONSENT_LIFETIME_DAYS,
)
from .test_users import (
    TEST_USERS,
    make_platform_admin_headers,
    make_caseworker_headers,
    make_provider_staff_headers,
    make_client_headers,
    make_funder_reporter_headers,
)
from .fixtures import (
    Baseline,
    set_clock,
    create_funder,
    create_provider,
    create_program,
    create_client,
    create_intake,
    screen_intake,
    create_consent_grant,
    create_referral,
    accept_referral,
    start_service,
    complete_referral,
    create_outcome_report,
    create_transport_plan,
    setup_baseline,
    setup_baseline_with_referral,
    setup_baseline_with_accepted_referral,
    setup_baseline_with_service_in_progress_referral,
    setup_program_at_capacity_utilization,
    setup_program_closed_by_capacity,
    setup_four_accepted_started_referrals,
    setup_three_unmet_outcomes_for_report,
    DEFAULT_CLOCK,
)
