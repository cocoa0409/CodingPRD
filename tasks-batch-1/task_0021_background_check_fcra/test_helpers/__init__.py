"""Barrel export: framework generics + PRD-specific code."""

# Framework generics (re-exported for convenience).
from prd_bench_local_runner.testing import (
    validate_success, validate_error, validate_paginated,
    validate_error_is_one_of, get_success_data,
    is_valid_uuid, is_iso8601_timestamp,
    assert_cost_precision, assert_version_incremented, assert_timestamp_format,
    assert_race_outcome, assert_exactly_one_succeeds, assert_at_least_one_succeeds,
    run_race, build_user_headers, NON_EXISTENT_UUID,
)

# PRD-specific types.
from .types import (
    ApplicationStatus,
    ConsentStatus,
    BackgroundCheckOrderStatus,
    OverallResult,
    VerificationType,
    VerificationStatus,
    VerificationResult,
    AdverseActionStatus,
    UserRole,
    RiskScoreVariant,
    Jurisdiction,
    Applicant,
    Application,
    ConsentDisclosure,
    BackgroundCheckOrder,
    Verification,
    AdverseAction,
    SystemClock,
    AuditLog,
    RiskScoreResponse,
)

from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import (
    assert_common_fields,
    assert_lighter_common_fields,
    assert_jurisdiction,
    assert_applicant,
    assert_application,
    assert_consent,
    assert_order,
    assert_verification,
    assert_adverse_action,
    assert_no_version_on_lighter_entity,
)
from .factories import (
    create_jurisdiction_payload,
    create_applicant_payload,
    create_application_payload,
    create_consent_payload,
    create_order_payload,
    create_verification_payload,
    report_verification_payload,
    dispute_verification_payload,
    resolve_verification_payload,
)
from .constants import (
    FEDERAL_WAITING_DAY_FLOOR,
    CRIMINAL_WEIGHT,
    MVR_WEIGHT,
    EDUCATION_WEIGHT,
    RISK_THRESHOLD,
    DEFAULT_PAGE_LIMIT,
    MIN_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    DEFAULT_PAGE_OFFSET,
)
from .test_users import (
    TEST_USERS,
    make_applicant_headers,
    make_recruiter_headers,
    make_compliance_officer_headers,
)
from .fixtures import (
    PA, REC, REC_B, CO, CO_B, VP,
    set_clock,
    create_jurisdiction,
    create_applicant,
    create_application,
    create_consent,
    grant_consent,
    submit_application,
    conditional_offer,
    create_order,
    create_verification,
    report_verification,
    dispute_verification,
    resolve_verification,
    create_applicant_and_application,
    application_in_submitted,
    application_in_conditional_offer,
    order_with_three_pending_verifications,
    order_complete_with_results,
    order_complete_consider_with_adverse_action,
)
