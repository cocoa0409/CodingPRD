"""Barrel export: framework generics + FMLA/PFL-specific code."""
# Framework generics (re-exported for convenience).
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    assert_cost_precision,
    assert_exactly_one_succeeds,
    assert_at_least_one_succeeds,
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

# Domain types
from .types import (  # noqa: F401
    BenefitContinuationLedger,
    CertificationRecord,
    CertificationStatus,
    Employee,
    Employer,
    EmploymentStatus,
    FmlaMethod,
    HealthcareProvider,
    LeaveCase,
    LeaveCaseStatus,
    LeaveInterval,
    LeaveIntervalStatus,
    LeaveType,
    Notice,
    NoticeType,
    PaymentStatus,
    QualifyingReason,
    StateCode,
    UserRole,
)

# API surface
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES

# Assertions
from .assertions import (
    assert_benefit_ledger,
    assert_certification_record,
    assert_common_fields,
    assert_employee,
    assert_employer,
    assert_leave_case,
    assert_leave_interval,
    assert_notice,
    assert_owes_invariant,
    assert_provider,
)

# Factories
from .factories import (
    apply_payment_payload,
    approve_case_payload,
    create_case_payload,
    create_certification_payload,
    create_employee_payload,
    create_employer_payload,
    create_interval_payload,
    create_provider_payload,
    mark_insufficient_payload,
    patch_health_enrollment_payload,
    seed_historic_interval_payload,
    set_clock_payload,
)

# Domain constants
from .constants import (
    CERT_RESPONSE_WINDOW_DAYS,
    CONCURRENT_PFL_REASONS,
    DAYS_PER_MONTH,
    DELINQUENCY_GRACE_DAYS,
    ELIGIBILITY_RESPONSE_WINDOW_DAYS,
    FMLA_ANNUAL_QUOTA_HOURS,
    FMLA_ROLLING_DAYS,
    HOURS_THRESHOLD,
    JOB_RESTORATION_DAYS,
    LEAVE_FRACTION_DP,
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_MAX_LIMIT,
    PAGINATION_MIN_LIMIT,
    PFL_ENABLED_STATES,
    PFL_QUOTA_HOURS,
    RECERT_MIN_INTERVAL_DAYS,
    REVERSE_INTERVAL_WINDOW_DAYS,
    TENURE_THRESHOLD_MONTHS,
)

# Role headers
from .test_users import (
    TEST_USERS,
    make_employee_headers,
    make_headers,
    make_hr_admin_headers,
    make_platform_admin_headers,
    make_provider_headers,
)

# Composite fixtures
from .fixtures import (
    ApprovedCaseBundle,
    apply_payment,
    approve_case,
    complete_case,
    create_employee,
    create_employer,
    create_provider,
    deny_case,
    evaluate_eligibility,
    forfeit_restoration,
    get_case,
    get_certification,
    get_employee,
    list_benefit_ledgers_for_case,
    list_notices_for_case,
    mark_certification_complete,
    mark_certification_insufficient,
    patch_health_enrollment,
    receive_certification,
    record_interval,
    request_recertification,
    restore_case,
    reverse_interval,
    seed_historic_interval,
    set_clock,
    setup_active_case_with_first_interval,
    setup_approved_case,
    setup_case_in_certification_pending,
    setup_case_in_eligibility_pending,
    setup_case_with_received_insufficient_certification,
    submit_case,
    submit_certification,
    terminate_employee,
)
