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
    assert_claimant,
    assert_application,
    assert_work_credit,
    assert_hearing,
    assert_award,
    assert_child_auxiliary,
    assert_ssi_supplement,
    assert_cdr_review,
    assert_decision,
    assert_evidence,
)
from .factories import (
    create_claimant_payload,
    create_work_credit_payload,
    create_application_payload,
    create_evidence_payload,
    medical_decision_payload,
    schedule_hearing_payload,
    hearing_decision_payload,
    create_child_auxiliary_payload,
    complete_cdr_payload,
    set_clock_payload,
)
from .constants import (
    RECENT_QC_THRESHOLD,
    MAX_REQUIRED_TOTAL_QC,
    LOOKBACK_YEARS,
    MIN_REQUIRED_TOTAL_QC_UNDER_24,
    BEND1_CENTS,
    BEND2_CENTS,
    TIER1_RATE, TIER2_RATE, TIER3_RATE,
    AIME_DIVISOR_CAP,
    WAITING_PERIOD_MONTHS,
    MAX_RETROACTIVE_MONTHS_BEFORE_PFD,
    FBR_CENTS,
    RESOURCE_LIMIT_CENTS,
    GENERAL_EXCLUSION_CENTS,
    STATE_SUPPLEMENT_TABLE,
    CHILD_RATE,
    FAMILY_MAX_MULTIPLIER,
    MIE_MONTHS, MIP_MONTHS, MINE_MONTHS,
    HEARING_LEAD_TIME_DAYS,
    RECONSIDERATION_WINDOW_DAYS,
    CHILD_MAX_AGE_YEARS,
)
from .test_users import (
    TEST_USERS,
    make_claimant_headers,
    make_headers,
    make_unauthenticated_headers,
)
from .fixtures import (
    # clock
    set_clock,
    advance_clock,
    # claimant / credits
    create_claimant,
    post_work_credit,
    post_work_credits_for_years,
    INSURED_BASELINE_YEARS,
    setup_insured_baseline_claimant,
    # application
    create_application_for_claimant,
    submit_application,
    attach_evidence,
    setup_application_in_medical_review,
    # decisions & appeals
    submit_medical_decision,
    setup_application_awarded,
    deny_medical_setup,
    request_reconsideration,
    request_hearing,
    schedule_hearing,
    record_hearing_held,
    decide_hearing,
    setup_hearing_in_requested,
    # award / children
    get_current_award,
    create_child_auxiliary,
    suspend_award,
    reinstate_award,
    # CDR
    fetch_cdr_for_award,
    start_cdr,
    complete_cdr,
    setup_awarded_with_active_child,
)
