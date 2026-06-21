"""Barrel export: framework generics + PRD-specific code."""
# Framework generics (re-exported for convenience)
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

# PRD-specific
from .types import *  # noqa: F401,F403
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import (
    assert_applicant,
    assert_school,
    assert_application,
    assert_essay,
    assert_recommendation_request,
    assert_financial_aid_profile,
    assert_aid_package,
    assert_waitlist_entry,
)
from .factories import (
    create_applicant_payload,
    create_school_payload,
    create_application_payload,
    create_essay_payload,
    create_recommendation_request_payload,
    create_financial_aid_profile_payload,
    create_aid_package_payload,
)
from .constants import (
    EFC_SHELTER_PER_PERSON_CENTS,
    EFC_INCOME_ASSESSMENT_RATE,
    EFC_ASSET_ASSESSMENT_RATE,
    WEIGHT_GPA,
    WEIGHT_SAT,
    WEIGHT_ESSAY,
    WEIGHT_REC,
    NULL_SAT_NEUTRAL,
    ON_TARGET_THRESHOLD,
    OVER_TARGET_THRESHOLD,
    WORD_COUNT_TOLERANCE,
    DEFAULT_IN_STATE_TUITION_CENTS,
    DEFAULT_OUT_OF_STATE_TUITION_CENTS,
    DEFAULT_INTERNATIONAL_TUITION_CENTS,
    DEFAULT_TARGET_CLASS_SIZE,
    DEFAULT_ASSUMED_YIELD_RATE,
    DEFAULT_HOUSEHOLD_INCOME_CENTS,
    DEFAULT_HOUSEHOLD_SIZE,
)
from .test_users import (
    TEST_USERS,
    make_applicant_headers,
    make_admissions_headers,
    make_financial_aid_headers,
    make_platform_admin_headers,
)
from .fixtures import (
    set_clock,
    create_applicant,
    create_school,
    create_financial_aid_profile,
    create_draft_application,
    create_completed_essay,
    create_submitted_recommendation,
    setup_applicant_with_fap,
    setup_ready_to_submit_application,
    setup_submitted_application,
    setup_under_review_application,
    setup_admitted_application,
    setup_aid_drafted,
    setup_aid_finalized,
    setup_waitlisted_application,
    admit_n_applications_at_school,
)
