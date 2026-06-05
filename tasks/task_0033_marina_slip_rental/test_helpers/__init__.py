"""Barrel export: framework generics + marina-slip-rental-specific test helpers."""
# Framework generics (re-exported for convenience).
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

# Domain types
from .types import (  # noqa: F401
    SlipStatus,
    LeaseStatus,
    TenantLiveaboardStatus,
    PumpOutRequestStatus,
    TowAssistOutcome,
    TransferWaitlistStatus,
    PowerAmp,
    UserRole,
    Marina,
    Slip,
    Vessel,
    Tenant,
    Lease,
    PumpOutRequest,
    TowAssistEvent,
    TransferWaitlistEntry,
)

# API surface
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES

# Assertions
from .assertions import (
    assert_common_fields,
    assert_append_only_fields,
    assert_marina,
    assert_slip,
    assert_vessel,
    assert_tenant,
    assert_lease,
    assert_pump_out_request,
    assert_tow_assist_event,
    assert_transfer_waitlist_entry,
)

# Payload factories
from .factories import (
    create_marina_payload,
    create_slip_payload,
    create_tenant_payload,
    create_vessel_payload,
    liveaboard_application_payload,
    liveaboard_approve_payload,
    liveaboard_revoke_payload,
    create_lease_payload,
    create_pump_out_request_payload,
    create_tow_assist_event_payload,
    create_transfer_waitlist_payload,
    set_clock_payload,
)

# Domain constants
from .constants import (
    SEASONAL_MULTIPLIER_SUMMER_NUM,
    SEASONAL_MULTIPLIER_SUMMER_DEN,
    SEASONAL_MULTIPLIER_WINTER_NUM,
    SEASONAL_MULTIPLIER_WINTER_DEN,
    LIVEABOARD_SURCHARGE_NUM,
    LIVEABOARD_SURCHARGE_DEN,
    LIVEABOARD_UTILITY_FEE_PER_NIGHT_CENTS,
    PUMPOUT_PORTABLE_FEE_CENTS,
    MIN_INSURANCE_COVERAGE_CENTS,
    DEFAULT_SEASON_SUMMER_START,
    DEFAULT_SEASON_SUMMER_END,
    DEFAULT_TOW_ASSIST_RADIUS_NM,
)

# Role headers / RBAC
from .test_users import (
    TEST_USERS,
    make_tenant_headers,
    make_harbor_master_headers,
    make_marina_staff_headers,
    make_headers,
)

# Composite setup helpers
from .fixtures import (
    set_clock,
    create_marina,
    create_slip,
    create_tenant,
    create_vessel,
    apply_liveaboard,
    approve_liveaboard,
    revoke_liveaboard,
    make_tenant_approved_for_liveaboard,
    reserve_lease,
    check_in_lease,
    check_out_lease,
    cancel_lease,
    setup_simple_marina_with_slip,
    setup_tenant_with_vessel,
    setup_full_reservation,
    setup_active_lease,
    setup_ended_lease,
    create_pump_out_request,
    complete_pump_out_request,
    create_transfer_waitlist_entry,
)
