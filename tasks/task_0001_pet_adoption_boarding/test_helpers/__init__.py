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
    assert_shelter, assert_animal, assert_vaccination, assert_adopter,
    assert_home_visit, assert_adoption_application, assert_boarding_reservation,
    assert_fee_settlement, assert_shelter_slot_invariant,
)
from .factories import (
    create_shelter_payload, create_animal_payload, create_vaccination_payload,
    create_adopter_payload, create_home_visit_payload, submit_home_visit_payload,
    create_application_payload, create_reservation_payload, create_settlement_payload,
    future_iso, past_iso, now_iso,
)
from .constants import (
    HOME_VISIT_PASS_THRESHOLD, HOME_VISIT_TTL_DAYS,
    SENIOR_AGE_MONTHS, SENIOR_DISCOUNT,
    PEAK_UTILIZATION, PEAK_SURCHARGE, MEDICAL_MULTIPLIER, BEHAVIORAL_MULTIPLIER,
    EARLY_CHECKIN_GRACE_HOURS, DEFAULT_LIMIT, MIN_LIMIT, MAX_LIMIT, DEFAULT_OFFSET,
    TEST_DEFAULTS,
)
from .test_users import (
    TEST_USERS, make_inspector_headers, make_reviewer_headers,
    make_approver_headers, make_adopter_headers,
)
from .fixtures import (
    create_shelter, create_animal, fully_vaccinate_animal, create_adopter,
    required_vaccines_for_species,
    schedule_home_visit, submit_home_visit, create_adopter_with_passed_home_visit,
    setup_ready_for_approval, submit_application, walk_application_to_under_review,
    approve_application, setup_approved_application,
    create_pending_settlement, capture_settlement, create_and_capture_settlement,
    setup_finalizable_application,
    create_boardable_animal, create_reservation, setup_reservation_scenario,
    fill_shelter_to_capacity, make_adopter_headers_for,
)
