"""Barrel export: framework generics + PRD-specific code."""
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

# PRD-specific.
from .types import *  # noqa: F401,F403
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import (
    assert_wedding,
    assert_meal_option,
    assert_table,
    assert_guest,
    assert_plus_one,
    assert_seating_assignment,
    assert_registry_item,
    assert_purchase,
    assert_thank_you_note,
)
from .factories import (
    create_wedding_payload,
    create_meal_option_payload,
    create_table_payload,
    create_guest_payload,
    create_plus_one_payload,
    create_seating_assignment_payload,
    create_registry_item_payload,
    create_purchase_payload,
    guest_rsvp_payload,
    plus_one_rsvp_payload,
)
from .constants import (
    W_SENT,
    W_DRAFTED,
    W_PENDING,
    EMPTY_COMPLETION_PCT,
)
from .test_users import (
    TEST_USERS,
    make_couple_headers,
    make_guest_self_headers,
    make_platform_integration_headers,
    make_platform_admin_headers,
)
from .fixtures import (
    set_clock,
    create_wedding,
    create_adult_meal_option,
    create_kids_meal_option,
    add_table,
    add_guest,
    open_rsvp,
    close_rsvp,
    archive_wedding,
    guest_rsvp_attending,
    guest_rsvp_decline,
    revoke_guest_rsvp,
    add_plus_one,
    manual_seat_guest,
    manual_seat_plus_one,
    finalize_seating,
    add_registry_item,
    ingest_purchase,
    get_thank_you_note_for_purchase,
    get_wedding,
    get_registry_item,
    get_guest,
    get_plus_one,
    list_seating_assignments_for_wedding,
    bootstrap_wedding_in_draft,
    bootstrap_wedding_in_rsvp_open,
    bootstrap_wedding_with_open_registry,
    bootstrap_seated_wedding,
    bootstrap_archived_wedding,
    bootstrap_confirmed_purchase,
)
