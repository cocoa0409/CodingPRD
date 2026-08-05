"""Barrel export: framework generics + PRD-specific code.

Tests import everything from ``test_helpers`` for one consistent source.
"""
from prd_bench_local_runner.testing import (
    validate_success, validate_error, validate_paginated,
    validate_error_is_one_of, get_success_data,
    is_valid_uuid, is_iso8601_timestamp,
    assert_cost_precision, assert_version_incremented, assert_timestamp_format,
    assert_race_outcome, assert_exactly_one_succeeds, assert_at_least_one_succeeds,
    run_race, build_user_headers, NON_EXISTENT_UUID,
    GenericApiClient,
)

from .types import *  # noqa: F401,F403
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import (
    assert_community,
    assert_resident,
    assert_vehicle,
    assert_decal,
    assert_pass,
    assert_gate_event,
    assert_amenity,
    assert_reservation,
    assert_patrol,
    assert_incident,
    assert_violation,
)
from .factories import (
    set_clock_payload,
    create_community_payload,
    create_resident_payload,
    create_vehicle_payload,
    create_decal_payload,
    create_pass_payload,
    create_gate_event_payload,
    create_amenity_payload,
    create_reservation_payload,
    create_patrol_payload,
    create_incident_payload,
    create_violation_payload,
)
from .constants import (
    DELINQUENCY_THRESHOLD_CENTS,
    REPEAT_WINDOW_DAYS,
    DELINQUENT_SURCHARGE_CENTS,
    FINE_CAP_CENTS,
    TIER_MULTIPLIERS,
    TIER_MULTIPLIER_MAX,
    LATE_FEE_PCT,
    GUEST_HOURLY_CENTS,
    VENDOR_HOURLY_CENTS,
    OVERSTAY_SURCHARGE_CENTS_PER_HOUR,
    OVERAGE_MULTIPLIER,
    PATROL_BUFFER_MINUTES,
    CLOCK_STARTUP_DEFAULT,
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_MIN_LIMIT,
    PAGINATION_MAX_LIMIT,
    PAGINATION_DEFAULT_OFFSET,
    NON_EXISTENT_UUID as NON_EXISTENT_UUID_LOCAL,
)
from .test_users import (
    TEST_USERS,
    ANONYMOUS_HEADERS,
    make_admin_headers,
    make_officer_headers,
    make_resident_headers,
)
from .fixtures import (
    ADMIN,
    OFFICER,
    DEFAULT_ISSUER_ID,
    set_clock,
    create_community,
    create_resident,
    create_vehicle,
    issue_decal,
    create_pass,
    authorize_pass,
    record_gate_event,
    create_amenity,
    book_reservation,
    transition_reservation,
    create_patrol,
    create_incident,
    issue_violation,
    appeal_violation,
    transition_resident,
    setup_community_and_resident,
    setup_approved_vendor_pass_onsite,
    setup_reservation_checked_in,
)
