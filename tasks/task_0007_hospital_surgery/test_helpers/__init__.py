"""Barrel export: framework generics + PRD-specific code."""
# Framework generics (re-exported for convenience)
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

# PRD-specific
from .types import *  # noqa: F401,F403
from .api_client import api_client, ApiClient  # noqa: F401
from .api_errors import ApiErrorId, HTTP_STATUS_CODES  # noqa: F401
from .assertions import (  # noqa: F401
    assert_operating_room,
    assert_surgical_case,
    assert_staff_member,
    assert_case_assignment,
    assert_instrument_set,
    assert_instrument_booking,
    assert_settlement,
    assert_audit_entry,
)
from .factories import (  # noqa: F401
    create_operating_room_payload,
    create_staff_payload,
    create_instrument_set_payload,
    create_surgical_case_payload,
    create_schedule_payload,
    create_emergency_insert_payload,
    create_pre_authorize_payload,
    create_itemize_payload,
    create_clock_advance_payload,
    create_complete_payload,
    make_staff_assignment,
)
from .constants import THRESHOLDS, TEST_DEFAULTS  # noqa: F401
from .test_users import TEST_USERS  # noqa: F401
from .fixtures import *  # noqa: F401,F403
