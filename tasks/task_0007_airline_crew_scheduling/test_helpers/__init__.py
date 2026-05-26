"""Barrel export: framework generics + PRD-specific helpers."""

# Framework generics — re-exported so tests have one import source.
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

from .types import (
    UserRole,
    CrewRank,
    LineType,
    CrewStatus,
    PairingState,
    LegType,
    BidState,
    AssignmentState,
    AssignmentSource,
    SickCallState,
    SickReasonCode,
    ReserveCallupState,
    TripTradeState,
    CrewMember,
    Pairing,
    FlightLeg,
    Bid,
    Assignment,
    SickCall,
    ReserveCallup,
    TripTrade,
)

from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import (
    assert_crew_member,
    assert_pairing,
    assert_flight_leg,
    assert_bid,
    assert_assignment,
    assert_sick_call,
    assert_reserve_callup,
    assert_trip_trade,
    assert_version_advanced,
)
from .factories import (
    create_crew_member_payload,
    create_pairing_payload,
    create_flight_leg_payload,
    create_bid_payload,
    create_sick_call_payload,
    create_trip_trade_payload,
)
from .constants import (
    FAA_DUTY_CAP_7D_MIN,
    FAA_FLIGHT_CAP_7D_MIN,
    WINDOW_HOURS,
    MIN_REST_MINUTES,
    REPORT_BUFFER_MIN,
    DEBRIEF_BUFFER_MIN,
    MAX_CALLUP_ATTEMPTS,
)
from .test_users import (
    TEST_USERS,
    make_crew_member_headers,
    make_unauthenticated_headers,
)
from .fixtures import (
    # Low-level
    set_clock,
    create_crew_member,
    create_pairing,
    add_revenue_leg,
    open_bidding,
    close_bidding,
    submit_bid,
    award_pairing,
    complete_pairing,
    cancel_pairing,
    confirm_assignment,
    report_sick_call,
    acknowledge_sick_call,
    get_pairing,
    get_crew_member,
    get_assignment,
    get_sick_call,
    get_reserve_callup,
    get_trip_trade,
    list_assignments_for,
    list_reserve_callups_for,
    first_assignment_for,
    # Composites
    setup_clean_world,
    setup_pairing_in_bid_open,
    setup_scheduled_captain_assignment,
    setup_confirmed_captain_assignment,
    setup_completed_pairing_for_crew,
    setup_two_crew_with_confirmed_assignments,
    setup_sick_call_with_reserve_offered,
    setup_trip_trade_in_state,
    setup_crew_with_accumulated_duty,
)
