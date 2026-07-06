"""Barrel export: framework generics + parking-enforcement test helpers."""
# Framework generics (re-exported for convenience).
from prd_bench_local_runner.testing import (  # noqa: F401
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
from .types import *  # noqa: F401,F403

# API surface
from .api_client import api_client, ApiClient  # noqa: F401
from .api_errors import ApiErrorId, HTTP_STATUS_CODES  # noqa: F401

# Assertions
from .assertions import (  # noqa: F401
    assert_common_fields,
    assert_config_fields,
    assert_officer,
    assert_beat,
    assert_hearing_room,
    assert_violation_code,
    assert_shift,
    assert_vehicle,
    assert_citation,
    assert_payment,
    assert_contest,
    assert_hearing,
    assert_boot_tow_order,
    assert_registration_hold,
)

# Payload factories
from .factories import *  # noqa: F401,F403

# Domain constants
from .constants import *  # noqa: F401,F403

# Role headers / RBAC
from .test_users import (  # noqa: F401
    TEST_USERS,
    ANON_HEADERS,
    make_enforcement_officer_headers,
    make_headers,
)

# Composite setup helpers
from .fixtures import (  # noqa: F401
    set_clock,
    create_officer,
    create_beat,
    create_violation_code,
    retire_violation_code,
    create_hearing_room,
    create_vehicle,
    open_shift,
    close_shift,
    issue_citation,
    create_payment,
    settle_payment,
    refund_payment,
    void_citation,
    reassess_citation,
    apply_waiver,
    file_contest,
    schedule_hearing,
    decide_hearing,
    get_vehicle,
    get_citation,
    list_boot_tow_orders,
    list_registration_holds,
    setup_issuing_context,
    issue_in_context,
    setup_boot_eligible_vehicle,
    setup_scheduled_hearing,
)
