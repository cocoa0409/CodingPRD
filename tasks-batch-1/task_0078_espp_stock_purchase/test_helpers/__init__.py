"""Barrel export: framework generics + ESPP-specific code.

Tests import everything from `test_helpers`. The PRD-bench local runner sets
PYTHONPATH so this package is importable.
"""
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
    ParticipantStatus,
    OfferingPeriodStatus,
    PurchasePeriodStatus,
    EnrollmentStatus,
    ContributionStatus,
    PurchaseStatus,
    ShareLotStatus,
    DispositionType,
    UserRole,
    Participant,
    Plan,
    OfferingPeriod,
    PurchasePeriod,
    Enrollment,
    Contribution,
    Purchase,
    ShareLot,
    Disposition,
    Form3922,
    AccrualLedger,
)

# API surface
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES

# Assertions
from .assertions import (
    assert_participant,
    assert_plan,
    assert_offering,
    assert_purchase_period,
    assert_enrollment,
    assert_contribution,
    assert_purchase,
    assert_share_lot,
    assert_disposition,
    assert_form_3922,
    assert_accrual_ledger,
)

# Payload factories
from .factories import (
    create_participant_payload,
    create_plan_payload,
    create_offering_payload,
    create_purchase_period_payload,
    create_enrollment_payload,
    create_contribution_payload,
    create_disposition_payload,
    run_purchase_payload,
)

# Domain constants
from .constants import (
    DEFAULT_MAX_CONTRIBUTION_RATE_PCT,
    DEFAULT_DISCOUNT_PCT,
    DEFAULT_ANNUAL_PURCHASE_LIMIT_USD,
    OFFERING_DURATION_MIN_MONTHS,
    OFFERING_DURATION_MAX_MONTHS,
    QUALIFY_GRANT_YEARS,
    QUALIFY_PURCHASE_YEARS,
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_MIN_LIMIT,
    PAGINATION_MAX_LIMIT,
)

# Role headers / RBAC
from .test_users import (
    TEST_USERS,
    make_participant_headers,
    make_admin_headers,
    make_officer_headers,
    make_headers,
)

# Composite setup helpers
from .fixtures import (
    ADMIN,
    ADMIN2,
    OFFICER,
    create_plan,
    create_participant,
    create_offering,
    enroll,
    contribute,
    create_purchase_period,
    close_enrollment,
    open_batch,
    certify_batch,
    run_batch,
    setup_open_offering,
    setup_enrolled_participant,
    setup_certified_batch,
    setup_settled_purchase,
)
