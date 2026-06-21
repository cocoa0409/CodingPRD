"""Barrel export: framework generics + PRD-specific code.

Tests import everything from `test_helpers` so they have one consistent source
for both the runner's generic utilities and this domain's specifics.
"""
# Framework generics (re-exported for convenience)
from prd_bench_local_runner.testing import (
    validate_success, validate_error, validate_paginated,
    validate_error_is_one_of, get_success_data,
    is_valid_uuid, is_iso8601_timestamp,
    assert_cost_precision, assert_version_incremented, assert_timestamp_format,
    assert_race_outcome, assert_exactly_one_succeeds, assert_at_least_one_succeeds,
    run_race, build_user_headers, NON_EXISTENT_UUID,
    GenericApiClient,
)

# PRD-specific types
from .types import (
    UserRole,
    RandomizationMethod, TrialIrbStatus, TrialPosture,
    CriterionKind, CriterionAttribute, Comparator,
    ConsentDocumentStatus, IRBReviewScope, IRBReviewDecision,
    MatchResult, EnrollmentStatus, SafetyStatus, VisitStatus,
    AdverseEventSeverity, AdverseEventReportStatus, PaymentStatus,
    Trial, EligibilityCriterion, RandomizationArm, ConsentDocument,
    IRBReview, Participant, Screening, Enrollment, Visit,
    AdverseEvent, CompensationPayment,
)

# API client + endpoint surface
from .api_client import api_client, ApiClient

# Error catalogue (importing this module registers the HTTP-status map).
from .api_errors import ApiErrorId, HTTP_STATUS_CODES

# Assertions
from .assertions import (
    assert_trial,
    assert_criterion,
    assert_arm,
    assert_consent_document,
    assert_irb_review,
    assert_participant,
    assert_screening,
    assert_enrollment,
    assert_visit,
    assert_adverse_event,
    assert_compensation_payment,
)

# Factories
from .factories import (
    set_clock_payload,
    create_trial_payload,
    create_criterion_payload,
    create_arm_payload,
    create_consent_document_payload,
    activate_consent_payload,
    create_irb_review_payload,
    decide_irb_review_payload,
    create_participant_payload,
    update_participant_payload,
    screen_participant_payload,
    create_enrollment_payload,
    transition_payload,
    create_visit_payload,
    complete_visit_payload,
    create_adverse_event_payload,
    review_adverse_event_payload,
)

# Domain constants
from .constants import (
    INCLUSION_WEIGHT, EXCLUSION_WEIGHT, MATCH_SCORE_DECIMALS,
    BASE_VISIT_CENTS, ON_TIME_MINUTES, LATE_GRACE_MINUTES,
    ON_TIME_BONUS_CENTS, LATE_BONUS_CENTS, MILEAGE_RATE_CENTS,
    WITHHOLDING_THRESHOLD_CENTS, LOW_WITHHOLDING_RATE, HIGH_WITHHOLDING_RATE,
    TARGET_ENROLLMENT_MIN,
    PAGINATION_DEFAULT_LIMIT, PAGINATION_MIN_LIMIT,
    PAGINATION_MAX_LIMIT, PAGINATION_DEFAULT_OFFSET,
)

# User identities
from .test_users import (
    TEST_USERS,
    SPONSOR_USER_ID, IRB_REVIEWER_USER_ID, COORDINATOR_USER_ID,
    INVESTIGATOR_USER_ID, SAFETY_OFFICER_USER_ID,
    make_sponsor_headers,
    make_irb_reviewer_headers,
    make_coordinator_headers,
    make_investigator_headers,
    make_safety_officer_headers,
)

# Composite fixtures
from .fixtures import (
    # Clock
    set_clock,
    # Primitives
    create_trial,
    add_criterion,
    add_arm,
    create_consent_document,
    open_irb_review,
    decide_irb_review,
    create_participant,
    screen_participant,
    create_enrollment,
    get_trial_version,
    # IRB approval helpers
    approve_protocol,
    approve_consent,
    activate_consent,
    # Composite trial / enrollment
    setup_open_trial,
    create_eligible_screened_enrollment,
    consent_enrollment,
    randomize_enrollment,
    activate_enrollment,
    withdraw_enrollment,
    setup_consented_enrollment,
    setup_randomized_enrollment,
    setup_active_enrollment,
    # Visits
    schedule_visit,
    complete_visit,
    setup_active_enrollment_with_completed_visits,
    # Adverse events
    report_adverse_event,
    triage_adverse_event,
    adjudicate_adverse_event,
    setup_enrollment_on_hold,
    # Payments
    sweep_payment,
    pay_payment,
)
