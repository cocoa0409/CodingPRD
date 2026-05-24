"""Barrel export: framework generics + PRD-specific code."""

# Framework generics — re-exported so test_suite has one import source.
from prd_bench_local_runner.testing import (
    validate_success, validate_error, validate_paginated,
    validate_error_is_one_of, get_success_data,
    is_valid_uuid, is_iso8601_timestamp,
    assert_cost_precision, assert_version_incremented, assert_timestamp_format,
    assert_race_outcome, assert_exactly_one_succeeds, assert_at_least_one_succeeds,
    run_race, build_user_headers, NON_EXISTENT_UUID,
)

# PRD-specific
from .types import (
    ApplicantProfileStatus, RecommenderInviteStatus, SchoolPosture,
    ApplicationStatus, ApplicationPlan, RecommendationLetterStatus,
    FinancialAidProfileStatus, AidOfferVariant, RecommenderRelationship,
    UserRole, DecisionType,
    Applicant, Recommender, School, Application, EssaySubmission,
    RecommendationLetter, FinancialAidProfile, AidOffer, AdmissionCycle,
)
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import (
    assert_applicant, assert_recommender, assert_school, assert_application,
    assert_essay_submission, assert_recommendation_letter,
    assert_financial_aid_profile, assert_aid_offer, assert_admission_cycle,
)
from .factories import (
    create_applicant_payload, create_recommender_payload, create_school_payload,
    create_application_payload, create_essay_payload, create_letter_payload,
    create_fa_profile_payload, create_aid_offer_payload,
    submit_letter_payload, decide_payload,
    unique_email, unique_school_name,
    LONG_LETTER_BODY,
    DEFAULT_ED_DEADLINE, DEFAULT_EA_DEADLINE, DEFAULT_RD_DEADLINE,
    DEFAULT_COOLDOWN_MS, DEFAULT_TEST_CLOCK,
)
from .constants import (
    RECOMMENDER_INPROGRESS_CAP,
    ESSAY_WORD_COUNT_MIN, ESSAY_WORD_COUNT_MAX,
    LETTER_BODY_MIN_CHARS,
    SCORE_MAX, GPA_COMPONENT_CAP, SAT_COMPONENT_CAP, LETTERS_FACTOR_CAP,
    PLAN_BONUS_ED, PLAN_BONUS_EA, PLAN_BONUS_ROLLING, PLAN_BONUS_REGULAR,
    PAGINATION_DEFAULT_LIMIT, PAGINATION_MAX_LIMIT, PAGINATION_MIN_LIMIT,
)
from .test_users import (
    TEST_USERS,
    make_applicant_headers, make_recommender_headers,
    admissions_headers, fa_officer_headers, admin_headers,
)
from .fixtures import (
    advance_clock_to, register_applicant, create_school, setup_clock_and_school,
    invite_and_accept_recommender, create_recommender_invited,
    setup_applicant_ready, create_application, create_essay,
    create_and_submit_letter, create_requested_letter,
    submit_application, start_review, decide,
    setup_admitted_application, setup_under_review_application,
    setup_draft_application, setup_waitlisted_application,
    setup_enrolled_application, setup_admitted_with_fa_profile,
    make_body_with_word_count,
)
