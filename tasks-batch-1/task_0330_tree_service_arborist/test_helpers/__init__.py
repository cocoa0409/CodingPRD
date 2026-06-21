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
    WorkOrderStatus, PricingMode, HazardTier,
    EstimateStatus, ServiceType, PermitStatus,
    BookingStatus, ResourceKind, EquipmentKind,
    DisposalTicketStatus, CrewStatus, EquipmentStatus,
    ServiceArea, Crew, Equipment, WorkOrder, TreeAsset,
    Estimate, LineItem, Permit, Booking, DisposalTicket,
)

# API client + endpoint surface
from .api_client import api_client, ApiClient

# Error catalogue (importing this module registers the HTTP-status map).
from .api_errors import ApiErrorId, HTTP_STATUS_CODES

# Assertions
from .assertions import (
    assert_service_area,
    assert_crew,
    assert_equipment,
    assert_work_order,
    assert_work_order_invariants,
    assert_tree_asset,
    assert_estimate,
    assert_line_item,
    assert_permit,
    assert_booking,
    assert_disposal_ticket,
)

# Factories
from .factories import (
    create_service_area_payload,
    create_crew_payload,
    create_equipment_payload,
    create_work_order_payload,
    create_tree_payload,
    create_line_item_payload,
    create_permit_payload,
    decide_permit_payload,
    create_booking_payload,
    finalize_booking_payload,
    create_disposal_ticket_payload,
)

# Domain constants
from .constants import (
    DBH_TIER_LARGE_IN, DBH_TIER_MED_IN,
    DBH_SMALL_POINTS, DBH_MED_POINTS, DBH_LARGE_POINTS,
    LEAN_STEP_DEG, LEAN_STEP_POINTS, LEAN_CAP, DECAY_POINTS,
    TIER_SEVERE_MIN, TIER_MODERATE_MIN,
    REMOVAL_SMALL_CENTS, REMOVAL_MED_CENTS, REMOVAL_LARGE_CENTS,
    STUMP_CENTS_PER_INCH, HAUL_OFF_CENTS_PER_TON, UTILITY_LINE_ITEM_CENTS,
    HAZARD_PCT_SEVERE, HAZARD_PCT_MODERATE, UTILITY_PER_TREE_CENTS,
    EMERGENCY_MULTIPLIER, DEFAULT_HERITAGE_SURCHARGE_PCT,
    OT_THRESHOLD_HOURS, OT_MULTIPLIER,
    DEFAULT_MOBILIZATION_BUFFER_MINUTES,
    PAGINATION_DEFAULT_LIMIT, PAGINATION_MIN_LIMIT,
    PAGINATION_MAX_LIMIT, PAGINATION_DEFAULT_OFFSET,
)

# User identities
from .test_users import (
    TEST_USERS,
    DEFAULT_CLIENT_USER_ID,
    make_client_headers,
    make_dispatcher_headers,
    make_arborist_headers,
    make_finance_clerk_headers,
)

# Composite fixtures
from .fixtures import (
    create_service_area,
    create_crew,
    create_equipment,
    create_work_order,
    add_tree,
    assess,
    create_estimate,
    add_line_item,
    issue_estimate,
    accept_estimate,
    current_version,
    create_booking,
    finalize_booking,
    record_disposal_ticket,
    finalize_disposal_ticket,
    create_permit,
    submit_permit,
    decide_permit,
    setup_assessed_work_order,
    setup_estimate_with_lines,
    setup_quoted_work_order,
    setup_scheduled_work_order,
    setup_scheduled_with_crew,
    setup_permit_work_order_under_review,
)
