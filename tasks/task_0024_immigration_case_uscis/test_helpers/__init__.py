"""Barrel export: framework generics + USCIS-specific code."""
# Framework generics (re-exported for convenience).
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

# Domain types
from .types import (  # noqa: F401
    CaseStatus,
    CaseType,
    PreferenceCategory,
    Country,
    ChartType,
    BiometricsStatus,
    InterviewStatus,
    InterviewDecision,
    RFEStatus,
    CaseEventType,
    UserRole,
    Applicant,
    Attorney,
    Case,
    BiometricsAppointment,
    RFE,
    InterviewAppointment,
    VisaBulletinEntry,
    CaseEvent,
    ClockState,
)

# API surface
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES

# Assertions
from .assertions import (
    assert_applicant,
    assert_attorney,
    assert_case,
    assert_filed_case,
    assert_biometrics,
    assert_rfe,
    assert_interview,
    assert_visa_bulletin_entry,
    assert_case_event,
    assert_workload_response,
)

# Payload factories
from .factories import (
    create_applicant_payload,
    create_attorney_payload,
    create_case_payload,
    create_biometrics_payload,
    reschedule_biometrics_payload,
    issue_rfe_payload,
    rfe_respond_payload,
    schedule_interview_payload,
    complete_interview_payload,
    decide_case_payload,
    visa_bulletin_payload,
    set_clock_payload,
)

# Domain constants
from .constants import (
    BASE_FEE_CENTS,
    BIOMETRICS_SURCHARGE_CENTS,
    CHILD_DISCOUNT_PCT,
    RFE_DEADLINE_DAYS,
    MAX_RFE_ROUNDS,
    APPT_LEAD_DAYS,
    APPT_WINDOW_MINUTES,
    NO_SHOW_GRACE_HOURS,
    STATUS_WEIGHTS,
    WORKLOAD_MULTIPLIER_DAYS_PER_UNIT,
    WORKLOAD_MULTIPLIER_CAP,
    RECEIPT_NUMBER_PATTERN,
    ALIEN_NUMBER_PATTERN,
    SERVICE_CENTER_PREFIXES,
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_MIN_LIMIT,
    PAGINATION_MAX_LIMIT,
)

# Role headers / RBAC
from .test_users import (
    TEST_USERS,
    make_applicant_headers,
    make_attorney_headers,
    make_officer_headers,
    make_admin_headers,
    make_headers,
)

# Composite setup helpers
from .fixtures import (
    set_clock,
    publish_visa_bulletin,
    register_applicant,
    register_attorney,
    create_draft_case,
    file_case,
    setup_filed_case,
    setup_under_review_i130,
    schedule_biometrics_for,
    setup_biometrics_scheduled_i485,
    setup_under_review_i485,
    issue_rfe_on,
    setup_rfe_pending_i130,
    respond_to_rfe,
    setup_interview_completed_i485,
    setup_officer_two_case_pool,
)
