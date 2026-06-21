"""Barrel export: framework generics + PRD-specific code."""
# Framework generics (re-exported for convenience)
from prd_bench_local_runner.testing import (
    validate_success, validate_error, validate_paginated,
    validate_error_is_one_of, get_success_data,
    is_valid_uuid, is_iso8601_timestamp,
    assert_cost_precision, assert_version_incremented, assert_timestamp_format,
    assert_race_outcome, assert_exactly_one_succeeds, assert_at_least_one_succeeds,
    run_race, build_user_headers, NON_EXISTENT_UUID,
)

# PRD-specific
from .types import *  # noqa: F401,F403
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import (
    assert_department,
    assert_requisition,
    assert_candidate,
    assert_application,
    assert_interview,
    assert_interview_feedback,
    assert_offer,
    assert_background_check,
    assert_referral_bonus,
    assert_diversity_goal,
    assert_committed_offer_nonneg,
    assert_filled_count_consistent,
)
from .factories import (
    create_department_payload,
    create_requisition_payload,
    create_candidate_payload,
    create_referral_candidate_payload,
    create_application_payload,
    create_interview_payload,
    create_interview_feedback_payload,
    create_offer_payload,
    approve_offer_payload,
    cancel_requisition_payload,
    resolve_background_check_payload,
    create_diversity_goal_payload,
    set_clock_payload,
)
from .constants import (
    LEVEL_BASE_CENTS,
    BAND_THRESHOLD_LOW,
    BAND_THRESHOLD_MID,
    BAND_THRESHOLD_HIGH,
    DIVERSITY_UPLIFT,
    UNDERREPRESENTED_ETHNICITIES,
    DECAY_30, DECAY_60, DECAY_90, DECAY_CUTOFF_DAYS,
    THRESH_STRONG_HIRE, THRESH_HIRE, THRESH_NO_HIRE,
    OFFER_EXPIRY_DAYS,
    PANEL_MIN, PANEL_MAX, PANELIST_BUFFER_MINUTES, INTERVIEW_MIN_DURATION,
    DIVERSITY_PCT_DECIMALS, INTERVIEW_SCORE_DECIMALS,
)
from .test_users import TEST_USERS, make_headers, make_unauthenticated_headers
from .fixtures import (
    set_clock,
    create_department,
    create_requisition,
    submit_requisition,
    approve_requisition,
    create_approved_requisition,
    create_candidate,
    create_application,
    screen_application,
    setup_approved_req_with_screened_app,
    create_offer,
    comp_approve_offer,
    vp_approve_offer,
    fully_approve_offer,
    extend_offer,
    accept_offer,
    setup_offer_in_state,
    fetch_background_check_for_offer,
    fetch_referral_bonuses_for_offer,
    start_background_check,
    resolve_background_check,
    schedule_interview,
    submit_interview_feedback,
    complete_interview,
    setup_interview_with_feedback,
    create_diversity_goal,
    read_diversity_goal,
    cancel_requisition_with_version,
    current_requisition_version,
    current_offer_version,
    current_department_committed,
)
