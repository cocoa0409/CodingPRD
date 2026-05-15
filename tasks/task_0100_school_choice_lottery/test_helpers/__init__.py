"""Barrel export: framework generics + PRD-specific test infrastructure.

Tests import everything from `test_helpers` and never reach into
sub-modules directly.

PRD §2.1 identity rules:
- SystemOperator is OPAQUE — the shared TEST_USERS constant is canonical
  for SystemOperator headers.
- DistrictAdmin (X-User-ID == District.id) and FamilyUser (X-User-ID ==
  Family.id) are ENTITY-BACKED — every ownership-gated call MUST mint
  headers via make_district_admin_headers(district["id"]) /
  make_family_user_headers(family["id"]). The shared fallback constants
  are reserved for tests that do not exercise ownership.
"""
from __future__ import annotations

# Framework generics — re-exported for convenience.
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    GenericApiClient,
    assert_at_least_one_succeeds,
    assert_cost_precision,
    assert_exactly_one_succeeds,
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

# PRD-specific.
from .api_client import ApiClient, api_client
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import (
    assert_application,
    assert_clock,
    assert_district,
    assert_family,
    assert_lottery_ordering,
    assert_lottery_run,
    assert_lottery_weight_matches_prd,
    assert_program,
    assert_program_invariants,
    assert_school,
    assert_student,
    assert_transfer_request,
    assert_waitlist_event,
    expected_lottery_weight,
    find_by_id,
)
from .constants import (
    CHOICE_RANK_DECAY,
    CLOCK_SINGLETON_ID,
    DEFAULT_ACCEPTS_INTER_DISTRICT_TRANSFERS,
    DEFAULT_POVERTY_INDEX_THRESHOLD,
    LOTTERY_SCORE_PRECISION_DECIMALS,
    LOTTERY_WEIGHT_BASE,
    LOTTERY_WEIGHT_PRECISION_DECIMALS,
    MAX_CHOICE_RANK,
    MAX_CHOICES_PER_STUDENT,
    MAX_GRADE_LEVEL,
    MIN_CHOICE_RANK,
    MIN_GRADE_LEVEL,
    OFFER_RESPONSE_HOURS,
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_MAX_LIMIT,
    PAGINATION_MIN_LIMIT,
    POVERTY_BOOST_PER_DECILE,
    PRIORITY_RANK,
    TEST_DEFAULTS,
    WAITLIST_BACKFILL_OFFER_HOURS,
    WITHDRAW_GRACE_DAYS,
)
from .factories import (
    DEFAULT_BASE_CLOCK,
    advance_clock_payload,
    create_application_payload,
    create_district_payload,
    create_family_payload,
    create_program_payload,
    create_school_payload,
    create_student_payload,
    create_transfer_request_payload,
    iso_offset,
    iso_utc,
    patch_district_payload,
    patch_program_payload,
    utc,
)
from .fixtures import (
    SYSTEM_OPERATOR,
    accept_application,
    advance_clock_iso,
    advance_clock_to,
    approve_transfer_request,
    close_program_window,
    create_application,
    create_district,
    create_family,
    create_program,
    create_school,
    create_student,
    create_transfer_request,
    decline_application,
    deny_transfer_request,
    draw_lottery,
    get_application,
    get_family,
    get_program,
    get_transfer_request_via_list,
    make_cross_district_application_with_approved_transfer,
    open_program_window,
    revoke_transfer_request,
    setup_accepted_application_with_anchor,
    setup_cross_district_setup,
    setup_district_with_school_and_program,
    setup_drawn_program_with_offer_and_one_waitlisted,
    setup_drawn_program_with_single_offer,
    setup_family_at_threshold_exactly,
    setup_family_with_student,
    setup_open_program_with_one_application,
    setup_post_grace_accepted_application,
    setup_two_families_threshold_pair,
    submit_application,
    submit_via_window,
    withdraw_application,
)
from .test_users import (
    DISTRICT_ADMIN_FALLBACK_ID,
    FAMILY_USER_FALLBACK_ID,
    SYSTEM_OPERATOR_ID,
    SYSTEM_OPERATOR_ID_ALT,
    TEST_USERS,
    make_district_admin_headers,
    make_family_user_headers,
    make_system_operator_headers,
)
from .types import (
    Application,
    ApplicationStatus,
    Clock,
    District,
    Family,
    LotteryRun,
    PriorityCategory,
    Program,
    ProgramWindowStatus,
    School,
    SchoolType,
    Student,
    TransferRequest,
    TransferRequestStatus,
    UserRole,
    WaitlistEvent,
)
